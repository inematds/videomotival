"""Etapas 4–6 — ffprobe (duração), ffmpeg (cena = imagem + áudio com zoom lento), concat final.

Adaptado do video_pipeline.py do tutorial (skill Codex). Diferenças:
- título da cena 1 gravado por drawtext (texto exato) em vez de pedir letras ao gerador;
- portão de duração configurável (warn | strict);
- música de fundo opcional na montagem final.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any

from .config import NO_TEXT_BLOCK, Settings
from .util import PipelineError, load_json, probe_duration, require_binary, run_process, say, write_json

WIDTH = 1920
HEIGHT = 1080
REQUIRED_SCENE_FIELDS = ("scene_number", "narration", "visual_description", "image_prompt")
NO_TEXT_MARKERS = ("no captions", "no subtitles", "no labels", "no logos", "no watermarks")


def scene_plan_path(run_dir: Path) -> Path:
    return run_dir / "work" / "scenes.json"


def validate_plan_data(plan: dict[str, Any]) -> list[dict[str, Any]]:
    for field in ("title", "topic", "target_duration_seconds", "character_bible", "visual_style", "scenes"):
        if field not in plan:
            raise PipelineError(f"scenes.json sem o campo: {field}")
    if not isinstance(plan["target_duration_seconds"], (int, float)) or plan["target_duration_seconds"] <= 0:
        raise PipelineError("target_duration_seconds deve ser positivo")
    if not str(plan["character_bible"]).strip():
        raise PipelineError("character_bible vazio")
    scenes = plan["scenes"]
    if not isinstance(scenes, list) or not scenes:
        raise PipelineError("scenes deve ser uma lista não vazia")
    for expected, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise PipelineError(f"Cena {expected} não é um objeto")
        missing = [f for f in REQUIRED_SCENE_FIELDS if f not in scene]
        if missing:
            raise PipelineError(f"Cena {expected} sem: {', '.join(missing)}")
        if int(scene["scene_number"]) != expected:
            raise PipelineError(f"Numeração das cenas precisa ser consecutiva a partir de 1; esperava {expected}, veio {scene['scene_number']}")
        for field in REQUIRED_SCENE_FIELDS[1:]:
            if not str(scene[field]).strip():
                raise PipelineError(f"Cena {expected}: campo {field} vazio")
        prompt = str(scene["image_prompt"]).lower()
        absent = [m for m in NO_TEXT_MARKERS if m not in prompt]
        if absent:
            raise PipelineError(f"Cena {expected}: image_prompt sem as salvaguardas de texto: {', '.join(absent)} (bloco esperado: '{NO_TEXT_BLOCK[:40]}...')")
    return scenes


def collect_durations(run_dir: Path, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for scene in scenes:
        number = int(scene["scene_number"])
        audio = run_dir / "work" / "audio" / f"{number:03d}.mp3"
        if not audio.is_file():
            raise PipelineError(f"Narração ausente: {audio}")
        records.append({"scene_number": number, "audio_file": f"work/audio/{number:03d}.mp3", "duration_seconds": round(probe_duration(audio), 6), "words": len(str(scene["narration"]).split())})
    return records


def duration_report(plan: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    actual = sum(r["duration_seconds"] for r in records)
    target = float(plan["target_duration_seconds"])
    tolerance = max(5.0, target * 0.08)
    words = sum(r["words"] for r in records)
    return {
        "target_duration_seconds": target,
        "actual_duration_seconds": round(actual, 6),
        "difference_seconds": round(actual - target, 6),
        "tolerance_seconds": round(tolerance, 6),
        "within_tolerance": abs(actual - target) <= tolerance,
        "words": words,
        "measured_words_per_minute": round(words / actual * 60.0, 1) if actual > 0 else None,
        "scenes": records,
    }


def probe_run(run_dir: Path, settings: Settings, plan: dict[str, Any]) -> dict[str, Any]:
    scenes = validate_plan_data(plan)
    report = duration_report(plan, collect_durations(run_dir, scenes))
    write_json(run_dir / "work" / "durations.json", report)
    say(f"[probe] {len(scenes)} narrações: {report['actual_duration_seconds']:.1f}s medidos para alvo de {report['target_duration_seconds']:.0f}s (wpm real {report['measured_words_per_minute']})")
    if not report["within_tolerance"]:
        message = f"Duração fora da tolerância em {abs(report['difference_seconds']):.1f}s (tolerância ±{report['tolerance_seconds']:.1f}s)"
        if settings.get("DURATION_GATE").strip().lower() == "strict":
            raise PipelineError(message + " — DURATION_GATE=strict: revise a narração, refaça o TTS com --force e meça de novo")
        say(f"[probe] AVISO: {message} (DURATION_GATE=warn, seguindo)")
    return report


# ---------------------------------------------------------------- render


def motion_filter(scene_number: int, frame_count: int, fps: int) -> str:
    frames = max(frame_count, 1)
    if scene_number % 2:
        zoom = f"min(1.035,1+0.035*on/{frames})"
    else:
        zoom = f"max(1.0,1.035-0.035*on/{frames})"
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={WIDTH}x{HEIGHT}:fps={fps},format=yuv420p"
    )


def _wrap_title(title: str, max_chars: int = 16) -> str:
    words = title.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:3])


def render_title_png(run_dir: Path, plan: dict[str, Any], settings: Settings) -> Path | None:
    """Título da cena 1 como PNG transparente (Pillow lida com UTF-8; o drawtext do ffmpeg 6.1
    corta caracteres finais quando há acentos). Tinta escura sobre caixa cor de papel."""
    font_path = settings.get("TITLE_FONT")
    if not Path(font_path).is_file():
        say(f"[render] fonte {font_path} não encontrada; título da cena 1 desativado")
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        say("[render] Pillow ausente (pip install pillow); título da cena 1 desativado")
        return None
    lines = _wrap_title(str(plan["title"]).upper()).split("\n")
    size = 96 if len(lines) == 1 else (84 if len(lines) == 2 else 68)
    font = ImageFont.truetype(font_path, size)
    pad_x, pad_y, gap = 34, 18, int(size * 0.28)
    boxes = []
    for line in lines:
        left, top, right, bottom = font.getbbox(line)
        boxes.append((line, right - left, bottom - top, left, top))
    canvas = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    y = int(HEIGHT * 0.07)
    for line, width, height, off_x, off_y in boxes:
        x = (WIDTH - width) // 2
        draw.rounded_rectangle((x - pad_x, y - pad_y, x + width + pad_x, y + height + pad_y), radius=10, fill=(244, 241, 234, 190))
        draw.text((x - off_x, y - off_y), line, font=font, fill=(42, 42, 42, 236))
        y += height + pad_y * 2 + gap
    out = run_dir / "work" / "title.png"
    canvas.save(out)
    return out


def render_scenes(run_dir: Path, settings: Settings, plan: dict[str, Any], report: dict[str, Any], force: bool = False, progress=None) -> list[Path]:
    scenes = validate_plan_data(plan)
    fps = settings.get_int("FPS")
    ffmpeg = require_binary("ffmpeg")
    video_dir = run_dir / "work" / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    log = run_dir / "work" / "log.txt"
    overlay = plan.get("title_overlay", True) and settings.get_bool("TITLE_OVERLAY")
    outputs: list[Path] = []
    for scene, record in zip(scenes, report["scenes"]):
        number = int(scene["scene_number"])
        image = run_dir / "work" / "images" / f"{number:03d}.png"
        audio = run_dir / "work" / "audio" / f"{number:03d}.mp3"
        output = video_dir / f"{number:03d}.mp4"
        outputs.append(output)
        if not image.is_file():
            raise PipelineError(f"Imagem da cena ausente: {image}")
        if output.is_file() and output.stat().st_size > 0 and not force:
            say(f"[render] cena {number:03d} já existe, pulando")
            continue
        duration = float(record["duration_seconds"])
        frames = max(1, round(duration * fps))
        vf = motion_filter(number, frames, fps)
        title_png = render_title_png(run_dir, plan, settings) if (number == 1 and overlay) else None
        say(f"[render] cena {number:03d}/{len(scenes):03d} ({duration:.1f}s{' + título' if title_png else ''})")
        if progress:
            progress(number, len(scenes), "start")
        inputs = ["-loop", "1", "-framerate", str(fps), "-i", str(image), "-i", str(audio)]
        if title_png:
            inputs += ["-loop", "1", "-framerate", str(fps), "-i", str(title_png)]
            graph = ["-filter_complex", f"[0:v]{vf}[bg];[bg][2:v]overlay=0:0:format=auto,format=yuv420p[v]", "-map", "[v]"]
        else:
            graph = ["-vf", vf, "-map", "0:v:0"]
        run_process(
            [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                *inputs, *graph, "-t", f"{duration:.6f}",
                "-map", "1:a:0",
                "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-r", str(fps),
                "-c:a", "aac", "-af", "aresample=async=1:first_pts=0", "-b:a", "192k", "-ar", "44100", "-ac", "1",
                "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-avoid_negative_ts", "make_zero", "-shortest",
                str(output),
            ],
            f"Render cena {number:03d}",
            log,
        )
        if progress:
            progress(number, len(scenes), "done")
    return outputs


def probe_final_media(path: Path) -> dict[str, Any]:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels", "-show_entries", "format=duration", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise PipelineError("MP4 final precisa ter vídeo e áudio")
    if video.get("width") != WIDTH or video.get("height") != HEIGHT:
        raise PipelineError(f"MP4 final com dimensões erradas: {video.get('width')}x{video.get('height')}")
    duration = float(data.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise PipelineError("MP4 final sem duração positiva")
    return {"duration_seconds": duration, "video": video, "audio": audio}


def assemble(run_dir: Path, settings: Settings, plan: dict[str, Any], report: dict[str, Any], music: Path | None = None, music_volume: float = 0.12) -> Path:
    scenes = validate_plan_data(plan)
    ffmpeg = require_binary("ffmpeg")
    work = run_dir / "work"
    log = work / "log.txt"
    lines = []
    for scene in scenes:
        clip = work / "video" / f"{int(scene['scene_number']):03d}.mp4"
        if not clip.is_file() or clip.stat().st_size == 0:
            raise PipelineError(f"Cena renderizada ausente: {clip}")
        lines.append(f"file 'video/{int(scene['scene_number']):03d}.mp4'")
    concat = work / "concat.txt"
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    final_path = run_dir / "final.mp4"
    if music and Path(music).is_file():
        total = sum(r["duration_seconds"] for r in report["scenes"])
        run_process(
            [
                ffmpeg, "-hide_banner", "-loglevel", "warning", "-y",
                "-f", "concat", "-safe", "0", "-i", str(concat),
                "-stream_loop", "-1", "-i", str(music),
                "-filter_complex",
                f"[1:a]volume={music_volume},afade=t=in:st=0:d=2,afade=t=out:st={max(0.0, total - 3):.2f}:d=3[m];[0:a][m]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[a]",
                "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", "-shortest", str(final_path),
            ],
            "Montagem final com música", log,
        )
    else:
        run_process(
            [ffmpeg, "-hide_banner", "-loglevel", "warning", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", "-movflags", "+faststart", "-avoid_negative_ts", "make_zero", str(final_path)],
            "Montagem final", log,
        )
    media = probe_final_media(final_path)
    manifest = {
        "run_id": run_dir.name,
        "title": plan["title"],
        "topic": plan["topic"],
        "lang": plan.get("lang"),
        "target_duration_seconds": plan["target_duration_seconds"],
        "actual_duration_seconds": round(float(media["duration_seconds"]), 6),
        "scene_count": len(scenes),
        "resolution": f"{WIDTH}x{HEIGHT}",
        "fps": settings.get_int("FPS"),
        "video_stream": media["video"],
        "audio_stream": media["audio"],
        "story_provider": plan.get("story_provider"),
        "tts": f"{settings.get('TTS_PROVIDER')}/{settings.get('TTS_ENGINE')}/{settings.get('TTS_VOICE')}",
        "images": f"{settings.get('IMAGE_PROVIDER')}/{settings.get('IMAGE_MODEL')}",
        "music": str(music) if music else None,
        "final_file": "final.mp4",
        "scenes": report["scenes"],
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(run_dir / "manifest.json", manifest)
    say(f"[assemble] {final_path} ({media['duration_seconds']:.1f}s)")
    return final_path


def status(run_dir: Path) -> dict[str, Any]:
    plan = load_json(scene_plan_path(run_dir)) if scene_plan_path(run_dir).is_file() else {}
    scenes = plan.get("scenes") or []
    counts = {}
    for label, suffix in (("audio", ".mp3"), ("images", ".png"), ("video", ".mp4")):
        directory = run_dir / "work" / label
        counts[label] = sum((directory / f"{int(s['scene_number']):03d}{suffix}").is_file() for s in scenes)
    return {"scenes": len(scenes), **counts, "final": (run_dir / "final.mp4").is_file()}
