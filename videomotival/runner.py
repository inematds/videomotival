"""Orquestração de uma corrida (run). Estado persistido em metadata.json — o web e o CLI
leem e escrevem no disco, então reiniciar o servidor não perde nada.

Etapas: plan → tts → images → render (probe + cenas + montagem).
Status: created | planning | review | tts | images | render | done | failed
"""

from __future__ import annotations

import datetime as dt
import random
import re
import threading
import traceback
from pathlib import Path
from typing import Any

from . import images as images_mod
from . import pipeline, story, tts
from .config import Settings, voice_ref_path
from .util import PipelineError, load_json, require_binary, say, slugify, write_json

STAGES = ("plan", "tts", "images", "render")
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def run_lock(run_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(run_id, threading.Lock())


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def metadata_path(run_dir: Path) -> Path:
    return run_dir / "metadata.json"


def read_metadata(run_dir: Path) -> dict[str, Any]:
    return load_json(metadata_path(run_dir))


def update_metadata(run_dir: Path, **changes: Any) -> dict[str, Any]:
    meta = read_metadata(run_dir)
    meta.update(changes)
    meta["updated_at"] = now_iso()
    write_json(metadata_path(run_dir), meta)
    return meta


def append_log(run_dir: Path, line: str, quiet: bool = False) -> None:
    if not quiet:
        say(line)
    with (run_dir / "work" / "log.txt").open("a", encoding="utf-8") as handle:
        handle.write(f"[{dt.datetime.now().strftime('%H:%M:%S')}] {line}\n")


def settings_for_run(run_dir: Path) -> Settings:
    meta = read_metadata(run_dir)
    return Settings(meta.get("settings") or {})


def list_runs(settings: Settings) -> list[dict[str, Any]]:
    root = settings.output_root
    runs = []
    if not root.is_dir():
        return runs
    for path in sorted(root.iterdir(), reverse=True):
        if not (path / "metadata.json").is_file():
            continue
        try:
            meta = read_metadata(path)
        except PipelineError:
            continue
        meta["counts"] = pipeline.status(path)
        runs.append(meta)
    return runs


def resolve_run(settings: Settings, run: str) -> Path:
    path = Path(run).expanduser()
    if path.is_dir() and (path / "metadata.json").is_file():
        return path.resolve()
    candidate = settings.output_root / run
    if (candidate / "metadata.json").is_file():
        return candidate.resolve()
    raise PipelineError(f"Corrida não encontrada: {run}")


# ---------------------------------------------------------------- criação


def create_run(settings: Settings, topic: str, duration_seconds: int, lang: str | None = None, overrides: dict[str, Any] | None = None, run_id: str | None = None, seed: int | None = None) -> Path:
    topic = topic.strip()
    if not topic:
        raise PipelineError("Informe um tema")
    if duration_seconds < 15:
        raise PipelineError("Duração alvo mínima: 15 segundos")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = run_id or f"{stamp}-{slugify(topic)}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise PipelineError("run-id só pode ter letras, dígitos, ponto, _ e -")
    run_dir = settings.output_root / run_id
    if run_dir.exists():
        raise PipelineError(f"Corrida já existe: {run_dir}")
    for rel in ("work/audio", "work/images", "work/video"):
        (run_dir / rel).mkdir(parents=True)
    snapshot = {k: v for k, v in (overrides or {}).items() if v not in (None, "")}
    if lang:
        snapshot["STORY_LANG"] = lang
    meta = {
        "run_id": run_id,
        "topic": topic,
        "target_duration_seconds": int(duration_seconds),
        "lang": lang or settings.get("STORY_LANG"),
        "image_seed": seed if seed is not None else random.randint(1, 2**31 - 1),
        "settings": snapshot,
        "status": "created",
        "stage": None,
        "progress": {},
        "error": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "final_file": None,
    }
    write_json(metadata_path(run_dir), meta)
    template = load_json(Path(__file__).resolve().parents[1] / "templates" / "scenes.template.json")
    template["title"] = topic
    template["topic"] = topic
    template["target_duration_seconds"] = int(duration_seconds)
    template["lang"] = meta["lang"]
    template["image_seed"] = meta["image_seed"]
    write_json(pipeline.scene_plan_path(run_dir), template)
    say(str(run_dir))
    return run_dir


# ---------------------------------------------------------------- checks


def check_environment(settings: Settings, need_tts: bool = True, need_images: bool = True, need_story: bool = True) -> list[str]:
    notes = []
    for binary in ("ffmpeg", "ffprobe"):
        require_binary(binary)
    notes.append("ffmpeg/ffprobe ok")
    if need_story:
        provider = settings.get("STORY_PROVIDER").lower()
        if provider == "manual":
            notes.append("história: manual (scenes.json escrito pelo agente/usuário)")
        else:
            available = [n for n in ("openrouter", "groq") if Settings.has_secret(f"{n.upper()}_API_KEY")]
            available.append("ollama")
            if provider != "auto" and provider not in available:
                raise PipelineError(f"STORY_PROVIDER={provider} sem chave disponível")
            notes.append(f"história: {provider} (disponíveis: {', '.join(available)})")
    if need_tts:
        notes.append(tts.check_tts(settings))
    if need_images:
        notes.append(images_mod.check_images(settings))
    return notes


# ---------------------------------------------------------------- etapas


def _progress_writer(run_dir: Path, key: str):
    def update(number: int, total: int, state: str) -> None:
        meta = read_metadata(run_dir)
        progress = meta.get("progress") or {}
        done = progress.get(key, {}).get("done", 0)
        if state == "done" or state == "skip":
            done = max(done, number)
        progress[key] = {"current": number, "total": total, "done": done, "state": state}
        update_metadata(run_dir, progress=progress)

    return update


def stage_plan(run_dir: Path, extra: str = "") -> dict[str, Any]:
    settings = settings_for_run(run_dir)
    meta = update_metadata(run_dir, status="planning", stage="plan", error=None)
    append_log(run_dir, f"[plan] tema: {meta['topic']} / {meta['target_duration_seconds']}s / {meta['lang']}")
    plan = story.generate_plan(run_dir, settings, meta["topic"], int(meta["target_duration_seconds"]), meta["lang"], int(meta["image_seed"]), extra)
    write_json(applied_plan_path(run_dir), plan)
    update_metadata(run_dir, status="review", stage="plan", title=plan["title"], scene_count=len(plan["scenes"]), estimated_seconds=plan.get("estimated_seconds"))
    append_log(run_dir, f"[plan] pronto: '{plan['title']}' com {len(plan['scenes'])} cenas — revise em work/scenes.json")
    return plan


def applied_plan_path(run_dir: Path) -> Path:
    return run_dir / "work" / "scenes.applied.json"


def load_plan(run_dir: Path) -> dict[str, Any]:
    plan = load_json(pipeline.scene_plan_path(run_dir))
    if not plan.get("scenes"):
        raise PipelineError("Plano vazio — rode a etapa `plan` (ou escreva work/scenes.json) antes")
    pipeline.validate_plan_data(plan)
    return plan


def save_plan(run_dir: Path, plan: dict[str, Any]) -> dict[str, Any]:
    """Salva um plano editado (web, CLI `recompose` ou agente): recompõe prompts, reescreve
    story/transcript e invalida áudio/imagem/clipe das cenas cujo texto mudou."""
    plan = story.refresh_image_prompts(plan)
    for index, scene in enumerate(plan["scenes"], start=1):
        scene["scene_number"] = index
    pipeline.validate_plan_data(plan)
    # Diff contra o último plano MATERIALIZADO (scenes.applied.json), não contra scenes.json —
    # assim edições feitas à mão no próprio scenes.json também são detectadas.
    previous: dict[str, Any] = {}
    try:
        previous = load_json(applied_plan_path(run_dir))
    except PipelineError:
        pass
    old_scenes = {int(s.get("scene_number", 0)): s for s in previous.get("scenes") or []}
    bible_changed = bool(old_scenes) and previous.get("character_bible") != plan["character_bible"]
    stale: set[int] = set()
    for scene in plan["scenes"]:
        number = int(scene["scene_number"])
        old = old_scenes.get(number)
        if old is None:
            continue
        if old.get("narration") != scene["narration"]:
            (run_dir / "work" / "audio" / f"{number:03d}.mp3").unlink(missing_ok=True)
            stale.add(number)
        if bible_changed or (old.get("composition") or old.get("image_prompt")) != scene["composition"]:
            (run_dir / "work" / "images" / f"{number:03d}.png").unlink(missing_ok=True)
            stale.add(number)
    for number in set(old_scenes) - {int(s["scene_number"]) for s in plan["scenes"]}:
        for rel in (f"audio/{number:03d}.mp3", f"images/{number:03d}.png", f"video/{number:03d}.mp4"):
            (run_dir / "work" / rel).unlink(missing_ok=True)
        stale.add(number)
    story.write_story_files(run_dir, plan)
    write_json(applied_plan_path(run_dir), plan)
    update_metadata(run_dir, title=plan["title"], scene_count=len(plan["scenes"]))
    if stale:
        _invalidate_clips(run_dir, plan, stale)
        append_log(run_dir, f"[plan] cenas alteradas {sorted(stale)}: áudio/imagem/clipe invalidados", quiet=True)
        update_metadata(run_dir, status="review")
    return plan


def _invalidate_clips(run_dir: Path, plan: dict[str, Any], only: set[int] | None) -> None:
    """Áudio ou imagem refeitos → a cena renderizada e o final ficam velhos."""
    numbers = only if only else {int(s["scene_number"]) for s in plan["scenes"]}
    for number in numbers:
        (run_dir / "work" / "video" / f"{number:03d}.mp4").unlink(missing_ok=True)
    (run_dir / "final.mp4").unlink(missing_ok=True)
    update_metadata(run_dir, final_file=None)


def stage_tts(run_dir: Path, force: bool = False, only: set[int] | None = None) -> None:
    settings = settings_for_run(run_dir)
    plan = load_plan(run_dir)
    update_metadata(run_dir, status="tts", stage="tts", error=None)
    append_log(run_dir, f"[tts] {settings.get('TTS_PROVIDER')}/{settings.get('TTS_ENGINE')}/{settings.get('TTS_VOICE')}" + (f" (só cenas {sorted(only)})" if only else ""))
    if force:
        _invalidate_clips(run_dir, plan, only)
    tts.synthesize_scenes(run_dir, settings, plan, force=force, progress=_progress_writer(run_dir, "tts"), only=only)
    report = pipeline.probe_run(run_dir, settings, plan)
    story.save_calibration(settings, report["words"], report["actual_duration_seconds"], plan.get("lang", ""), settings.get("TTS_VOICE"))
    update_metadata(run_dir, status="review", measured_seconds=report["actual_duration_seconds"], within_tolerance=report["within_tolerance"])
    append_log(run_dir, f"[tts] concluído: {report['actual_duration_seconds']:.1f}s medidos")


def stage_images(run_dir: Path, force: bool = False, only: set[int] | None = None) -> None:
    settings = settings_for_run(run_dir)
    plan = load_plan(run_dir)
    update_metadata(run_dir, status="images", stage="images", error=None)
    append_log(run_dir, f"[img] {settings.get('IMAGE_PROVIDER')}/{settings.get('IMAGE_MODEL')} seed base {plan.get('image_seed')}")
    if force:
        _invalidate_clips(run_dir, plan, only)
    images_mod.generate_scene_images(run_dir, settings, plan, force=force, progress=_progress_writer(run_dir, "images"), only=only)
    update_metadata(run_dir, status="review")
    append_log(run_dir, "[img] concluído")


def regen_image(run_dir: Path, scene_number: int, seed: int | None = None) -> Path:
    settings = settings_for_run(run_dir)
    plan = load_plan(run_dir)
    scene = next(s for s in plan["scenes"] if int(s["scene_number"]) == scene_number)
    scene["image_seed"] = seed if seed is not None else random.randint(1, 2**31 - 1)
    write_json(pipeline.scene_plan_path(run_dir), plan)
    append_log(run_dir, f"[img] regenerando cena {scene_number:03d} com seed {scene['image_seed']}")
    images_mod.generate_scene_images(run_dir, settings, plan, force=True, only={scene_number})
    clip = run_dir / "work" / "video" / f"{scene_number:03d}.mp4"
    clip.unlink(missing_ok=True)  # força re-render dessa cena
    (run_dir / "final.mp4").unlink(missing_ok=True)
    update_metadata(run_dir, status="review", final_file=None)
    return run_dir / "work" / "images" / f"{scene_number:03d}.png"


def stage_render(run_dir: Path, force: bool = False, music: str | None = None) -> Path:
    settings = settings_for_run(run_dir)
    plan = load_plan(run_dir)
    update_metadata(run_dir, status="render", stage="render", error=None)
    report = pipeline.probe_run(run_dir, settings, plan)
    pipeline.render_scenes(run_dir, settings, plan, report, force=force, progress=_progress_writer(run_dir, "render"))
    music_path = Path(music).expanduser() if music else None
    final = pipeline.assemble(run_dir, settings, plan, report, music=music_path)
    update_metadata(run_dir, status="done", stage="render", final_file="final.mp4", completed_at=now_iso(), measured_seconds=report["actual_duration_seconds"])
    append_log(run_dir, f"[render] FINAL: {final}")
    return final


def run_stages(run_dir: Path, stages: list[str], force: bool = False, music: str | None = None, extra: str = "", only: set[int] | None = None) -> None:
    """Executa etapas em sequência; falha vira status=failed com a mensagem em metadata.json."""
    lock = run_lock(run_dir.name)
    if not lock.acquire(blocking=False):
        raise PipelineError("Essa corrida já está em execução")
    try:
        for stage in stages:
            if stage == "plan":
                stage_plan(run_dir, extra)
            elif stage == "tts":
                stage_tts(run_dir, force=force, only=only)
            elif stage == "images":
                stage_images(run_dir, force=force, only=only)
            elif stage == "render":
                stage_render(run_dir, force=force, music=music)
            else:
                raise PipelineError(f"Etapa desconhecida: {stage}")
    except PipelineError as exc:
        update_metadata(run_dir, status="failed", error=str(exc))
        append_log(run_dir, f"ERRO: {exc}", quiet=True)
        raise
    except Exception as exc:  # noqa: BLE001 — registra e propaga
        update_metadata(run_dir, status="failed", error=f"{type(exc).__name__}: {exc}")
        append_log(run_dir, "ERRO inesperado:\n" + traceback.format_exc(), quiet=True)
        raise
    finally:
        lock.release()


def start_background(run_dir: Path, stages: list[str], force: bool = False, music: str | None = None, extra: str = "", only: set[int] | None = None) -> threading.Thread:
    def target() -> None:
        try:
            run_stages(run_dir, stages, force=force, music=music, extra=extra, only=only)
        except Exception:  # noqa: BLE001 — já registrado em metadata
            pass

    thread = threading.Thread(target=target, name=f"run-{run_dir.name}", daemon=True)
    thread.start()
    return thread
