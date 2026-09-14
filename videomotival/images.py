"""Etapa 3 — uma ilustração 16:9 por cena (work/images/001.png...).

Provider: inemaimg (flux2-klein na GPU local, :8000). Consistência do personagem =
bíblia verbatim em todo prompt + seed fixa da corrida. Cenas ruins: `regen` com outra seed.
"""

from __future__ import annotations

import base64
import struct
from pathlib import Path
from typing import Any, Callable

from .config import Settings
from .util import PipelineError, http_json, say, service_alive

ProgressFn = Callable[[int, int, str], None]


def _png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        raise PipelineError("Resposta do gerador não é um PNG válido")
    width, height = struct.unpack(">II", data[16:24])
    return width, height


def check_images(settings: Settings) -> str:
    provider = settings.get("IMAGE_PROVIDER").strip().lower()
    if provider != "inemaimg":
        raise PipelineError(f"IMAGE_PROVIDER desconhecido: {provider} (use inemaimg)")
    base = settings.get("INEMAIMG_URL").rstrip("/")
    if not service_alive(f"{base}/health"):
        raise PipelineError(f"inemaimg fora do ar em {base} — suba com docker-compose em ~/projetos/inemaimg")
    health = http_json(f"{base}/health", timeout=10, retries=1)
    loaded = health.get("loaded_model")
    wanted = settings.get("IMAGE_MODEL")
    note = "" if loaded == wanted else f" (carregado: {loaded}; pedir {wanted} recarrega pesos)"
    return f"inemaimg ok {wanted}{note}"


def generate_image(settings: Settings, prompt: str, seed: int) -> bytes:
    base = settings.get("INEMAIMG_URL").rstrip("/")
    body = {
        "model": settings.get("IMAGE_MODEL"),
        "prompt": prompt,
        "steps": settings.get_int("IMAGE_STEPS"),
        "seed": int(seed),
        "width": settings.get_int("IMAGE_WIDTH"),
        "height": settings.get_int("IMAGE_HEIGHT"),
    }
    data = http_json(f"{base}/generate", body, timeout=900, retries=3)
    b64 = data.get("image")
    if not isinstance(b64, str) or len(b64) < 100:
        raise PipelineError(f"inemaimg respondeu sem o campo 'image'. Chaves: {list(data.keys())}")
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    png = base64.b64decode(b64)
    width, height = _png_size(png)
    if width < 1024 or abs(width / height - 16 / 9) > 0.08:
        raise PipelineError(f"Imagem fora do 16:9 esperado: {width}x{height}")
    return png


def scene_seed(plan: dict[str, Any], scene: dict[str, Any]) -> int:
    if scene.get("image_seed") is not None:
        return int(scene["image_seed"])
    return int(plan.get("image_seed", 7))


def generate_scene_images(run_dir: Path, settings: Settings, plan: dict[str, Any], force: bool = False, progress: ProgressFn | None = None, only: set[int] | None = None) -> list[Path]:
    images_dir = run_dir / "work" / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    scenes = plan["scenes"]
    outputs: list[Path] = []
    for scene in scenes:
        number = int(scene["scene_number"])
        output = images_dir / f"{number:03d}.png"
        outputs.append(output)
        if only is not None and number not in only:
            continue
        if output.is_file() and output.stat().st_size > 0 and not force:
            say(f"[img] cena {number:03d} já existe, pulando")
            if progress:
                progress(number, len(scenes), "skip")
            continue
        seed = scene_seed(plan, scene)
        say(f"[img] cena {number:03d}/{len(scenes):03d} seed={seed}")
        if progress:
            progress(number, len(scenes), "start")
        png = generate_image(settings, scene["image_prompt"], seed)
        partial = output.with_name(f"{number:03d}.part.png")
        partial.write_bytes(png)
        partial.replace(output)
        if progress:
            progress(number, len(scenes), "done")
    return outputs
