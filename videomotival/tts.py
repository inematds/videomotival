"""Etapa 2 — uma narração por cena (work/audio/001.mp3, 002.mp3...).

Providers:
- inemavox (default): daemon local em :8010, engine chatterbox (clone por ref .wav) ou edge.
- fish: Fish Audio /v1/tts (fiel ao tutorial). Precisa de FISH_API_KEY nos arquivos de segredo
  e FISH_VOICE_ID no .env do projeto.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable

from .config import Settings, voice_ref_path
from .util import PipelineError, http_bytes, http_json, require_binary, run_process, say, service_alive

ProgressFn = Callable[[int, int, str], None]


def _wav_to_mp3(wav: Path, mp3: Path, pad_seconds: float, log: Path | None) -> None:
    ffmpeg = require_binary("ffmpeg")
    audio_filter = f"apad=pad_dur={pad_seconds:.2f}" if pad_seconds > 0 else "anull"
    run_process(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(wav), "-af", audio_filter,
         "-ar", "44100", "-ac", "1", "-c:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", str(mp3)],
        f"Converter {wav.name} para mp3",
        log,
    )


# ---------------------------------------------------------------- inemavox


def _inemavox_job(settings: Settings, text: str, lang: str, voice: str, engine: str) -> bytes:
    base = settings.get("INEMAVOX_URL").rstrip("/")
    config: dict[str, Any] = {"text": text, "lang": lang, "engine": engine}
    if engine.startswith("chatterbox"):
        ref = voice_ref_path(settings, voice)
        if ref is None:
            raise PipelineError(f"Voz '{voice}' não encontrada em {settings.get('VOICE_REFS_DIR')} (esperava {voice}.wav)")
        config["ref_audio"] = str(ref)
    elif engine == "edge":
        config["voice"] = voice
    else:
        raise PipelineError(f"TTS_ENGINE desconhecida: {engine}")
    job = http_json(f"{base}/api/jobs/tts", config, timeout=60)
    job_id = job.get("id")
    if not job_id:
        raise PipelineError(f"inemavox não devolveu id de job: {str(job)[:200]}")
    started = time.time()
    while True:
        time.sleep(2.5)
        state = http_json(f"{base}/api/jobs/{job_id}", timeout=30, retries=5)
        status = state.get("status")
        if status == "completed":
            break
        if status in ("failed", "cancelled"):
            raise PipelineError(f"inemavox job {job_id} {status}: {str(state.get('error') or '')[:300]}")
        if time.time() - started > 900:
            raise PipelineError(f"inemavox job {job_id} demorou mais de 15 min")
    return http_bytes(f"{base}/api/jobs/{job_id}/audio", timeout=120)


# ---------------------------------------------------------------- fish audio (tutorial)


def _fish_tts(settings: Settings, text: str) -> bytes:
    api_key = Settings.secret("FISH_API_KEY")
    voice_id = settings.get("FISH_VOICE_ID").strip() or Settings.secret("FISH_VOICE_ID")
    if not api_key or not voice_id:
        raise PipelineError("TTS_PROVIDER=fish precisa de FISH_API_KEY (arquivos de segredo) e FISH_VOICE_ID (.env)")
    body = {
        "text": text,
        "reference_id": voice_id,
        "format": "mp3",
        "sample_rate": 44100,
        "mp3_bitrate": 192,
        "normalize": True,
        "latency": "normal",
        "chunk_length": 300,
        "prosody": {"speed": 1.0, "volume": 0, "normalize_loudness": True},
    }
    audio = http_bytes(
        "https://api.fish.audio/v1/tts",
        headers={"Authorization": f"Bearer {api_key}", "model": settings.get("FISH_MODEL")},
        timeout=600,
        body=body,
    )
    if len(audio) < 1024:
        raise PipelineError("Fish Audio devolveu áudio suspeitamente pequeno")
    return audio


# ---------------------------------------------------------------- orquestração


def check_tts(settings: Settings) -> str:
    provider = settings.get("TTS_PROVIDER").strip().lower()
    if provider == "inemavox":
        base = settings.get("INEMAVOX_URL").rstrip("/")
        if not service_alive(f"{base}/api/jobs"):
            raise PipelineError(f"inemavox fora do ar em {base} (daemon da API, porta 8010)")
        engine = settings.get("TTS_ENGINE")
        if engine.startswith("chatterbox") and voice_ref_path(settings) is None:
            raise PipelineError(f"Voz '{settings.get('TTS_VOICE')}' sem .wav de referência em {settings.get('VOICE_REFS_DIR')}")
        return f"inemavox ok ({engine}/{settings.get('TTS_VOICE')})"
    if provider == "fish":
        if not Settings.has_secret("FISH_API_KEY"):
            raise PipelineError("FISH_API_KEY ausente nos arquivos de segredo")
        if not (settings.get("FISH_VOICE_ID") or Settings.secret("FISH_VOICE_ID")):
            raise PipelineError("FISH_VOICE_ID ausente")
        return "fish audio ok"
    raise PipelineError(f"TTS_PROVIDER desconhecido: {provider} (use inemavox|fish)")


def synthesize_scenes(run_dir: Path, settings: Settings, plan: dict[str, Any], force: bool = False, progress: ProgressFn | None = None, only: set[int] | None = None) -> list[Path]:
    provider = settings.get("TTS_PROVIDER").strip().lower()
    engine = settings.get("TTS_ENGINE")
    voice = settings.get("TTS_VOICE")
    lang = plan.get("lang") or settings.get("STORY_LANG")
    pad = settings.get_float("AUDIO_PAD_SECONDS")
    audio_dir = run_dir / "work" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "work" / "log.txt"
    scenes = plan["scenes"]
    outputs: list[Path] = []
    for scene in scenes:
        number = int(scene["scene_number"])
        output = audio_dir / f"{number:03d}.mp3"
        outputs.append(output)
        if only is not None and number not in only:
            continue
        if output.is_file() and output.stat().st_size >= 1024 and not force:
            say(f"[tts] cena {number:03d} já existe, pulando")
            if progress:
                progress(number, len(scenes), "skip")
            continue
        say(f"[tts] cena {number:03d}/{len(scenes):03d} ({provider}/{engine}/{voice})")
        if progress:
            progress(number, len(scenes), "start")
        partial = output.with_name(f"{number:03d}.part.mp3")
        if provider == "inemavox":
            wav_bytes = _inemavox_job(settings, scene["narration"], lang, voice, engine)
            raw = audio_dir / f"{number:03d}.raw.wav"
            raw.write_bytes(wav_bytes)
            _wav_to_mp3(raw, partial, pad, log)
            raw.unlink(missing_ok=True)
        elif provider == "fish":
            partial.write_bytes(_fish_tts(settings, scene["narration"]))
            if pad > 0:
                padded = output.with_name(f"{number:03d}.pad.mp3")
                _wav_to_mp3(partial, padded, pad, log)
                padded.replace(partial)
        else:
            raise PipelineError(f"TTS_PROVIDER desconhecido: {provider}")
        partial.replace(output)
        if progress:
            progress(number, len(scenes), "done")
    return outputs
