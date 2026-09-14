"""Configuração e segredos.

Regras:
- Configuração NÃO secreta vive em `<projeto>/.env` (providers, voz, idioma, urls).
- Segredos (GROQ_API_KEY, OPENROUTER_API_KEY, FISH_API_KEY...) são lidos em runtime de
  ~/projetos/openpcbotv2/.env e ~/projetos/wifi/.env (regra global do usuário). Nunca são
  copiados nem impressos.
- Variáveis de ambiente do processo vencem os arquivos.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[1]
HOME = Path.home()

SECRET_FILES = [
    HOME / "projetos" / "openpcbotv2" / ".env",
    HOME / "projetos" / "wifi" / ".env",
]

STYLE_BLOCK = (
    "16:9 landscape motivational editorial illustration. Hand-painted, simple expressive "
    "stick-figure characters, slightly imperfect black ink brush strokes, soft off-white "
    "textured paper background, subtle watercolor and gouache paint, minimal composition, "
    "simple visual metaphor, limited muted colors, generous negative space, emotional "
    "handmade editorial illustration. Flat paper texture, restrained detail. "
    "Not photorealistic, not 3D, not vector-clean, not glossy."
)

NO_TEXT_BLOCK = (
    "No captions, no subtitles, no labels, no logos, no signatures, no watermarks, "
    "no random letters or typographic marks, no numbers or digits (clock faces without numerals), no text of any kind."
)

DEFAULTS: dict[str, Any] = {
    # saída
    "OUTPUT_ROOT": str(HOME / "projetos" / "output" / "videomotival"),
    # história
    "STORY_PROVIDER": "auto",  # auto | openrouter | groq | ollama | manual
    "STORY_LANG": "pt",  # pt | en | es ...
    "WORDS_PER_MINUTE": "140",
    "OPENROUTER_MODEL": "z-ai/glm-5.2",
    "GROQ_MODEL": "openai/gpt-oss-120b",
    "OLLAMA_URL": "http://localhost:11434",
    "OLLAMA_MODEL": "qwen3.8:27b",
    # voz
    "TTS_PROVIDER": "inemavox",  # inemavox | fish
    "TTS_ENGINE": "chatterbox",  # chatterbox | chatterbox-vc | edge (só inemavox)
    "TTS_VOICE": "rachel",  # nome da ref em VOICE_REFS_DIR (chatterbox) ou voz edge (pt-BR-FranciscaNeural)
    "VOICE_REFS_DIR": str(HOME / "projetos" / "timesmkt3" / "media" / "voice-refs"),
    "INEMAVOX_URL": "http://localhost:8010",
    "AUDIO_PAD_SECONDS": "0.45",  # silêncio no fim de cada cena (respiro entre cortes)
    "FISH_MODEL": "s2-pro",
    "FISH_VOICE_ID": "",
    # imagens
    "IMAGE_PROVIDER": "inemaimg",
    "INEMAIMG_URL": "http://localhost:8000",
    "IMAGE_MODEL": "flux2-klein",
    "IMAGE_STEPS": "4",
    "IMAGE_WIDTH": "1920",
    "IMAGE_HEIGHT": "1080",
    # render
    "TITLE_OVERLAY": "1",  # 1 = grava o título na cena 1 via ffmpeg drawtext (texto exato, sem alucinação)
    "TITLE_FONT": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DURATION_GATE": "warn",  # warn | strict (strict = recusa renderizar fora da tolerância, como no tutorial)
    "FPS": "30",
}

SECRET_KEYS = ("GROQ_API_KEY", "OPENROUTER_API_KEY", "FISH_API_KEY", "GEMINI_API_KEY")


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


class Settings:
    """Snapshot de configuração. `get()` nunca devolve segredos; use `secret()`."""

    def __init__(self, overrides: dict[str, Any] | None = None):
        self._values: dict[str, str] = dict(DEFAULTS)
        self._values.update({k: v for k, v in load_env_file(PROJECT_DIR / ".env").items() if k not in SECRET_KEYS})
        for key in DEFAULTS:
            if os.environ.get(key):
                self._values[key] = os.environ[key]
        if overrides:
            self._values.update({k: str(v) for k, v in overrides.items() if v not in (None, "")})

    def get(self, key: str, default: str | None = None) -> str:
        return self._values.get(key, default if default is not None else "")

    def get_int(self, key: str) -> int:
        return int(float(self.get(key)))

    def get_float(self, key: str) -> float:
        return float(self.get(key))

    def get_bool(self, key: str) -> bool:
        return self.get(key).strip().lower() in ("1", "true", "yes", "on", "sim")

    def public(self) -> dict[str, str]:
        return {k: v for k, v in self._values.items() if k not in SECRET_KEYS}

    @property
    def output_root(self) -> Path:
        return Path(os.path.expanduser(self.get("OUTPUT_ROOT")))

    @staticmethod
    def secret(key: str) -> str:
        """Lê um segredo do ambiente ou dos arquivos autorizados. Nunca logar o valor."""
        if os.environ.get(key):
            return os.environ[key].strip()
        project_env = load_env_file(PROJECT_DIR / ".env")
        if project_env.get(key):
            return project_env[key].strip()
        for path in SECRET_FILES:
            value = load_env_file(path).get(key, "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def has_secret(key: str) -> bool:
        return bool(Settings.secret(key))


def voice_ref_path(settings: Settings, voice: str | None = None) -> Path | None:
    name = (voice or settings.get("TTS_VOICE")).strip()
    if not name:
        return None
    candidate = Path(os.path.expanduser(name))
    if candidate.suffix and candidate.is_file():
        return candidate
    refs = Path(os.path.expanduser(settings.get("VOICE_REFS_DIR")))
    for ext in ("wav", "mp3", "m4a", "ogg"):
        path = refs / f"{name}.{ext}"
        if path.is_file():
            return path
    return None


def list_voices(settings: Settings) -> list[dict[str, str]]:
    voices: list[dict[str, str]] = []
    refs = Path(os.path.expanduser(settings.get("VOICE_REFS_DIR")))
    if refs.is_dir():
        for path in sorted(refs.glob("*.wav")):
            voices.append({"id": path.stem, "engine": "chatterbox", "label": f"{path.stem} (clone chatterbox)"})
    for edge in ("pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural", "pt-BR-AntonioNeural", "en-US-AriaNeural", "en-US-GuyNeural"):
        voices.append({"id": edge, "engine": "edge", "label": f"{edge} (edge, sem GPU)"})
    return voices
