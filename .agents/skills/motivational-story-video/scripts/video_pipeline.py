#!/usr/bin/env python3
"""Deterministic production helper for the motivational-story-video skill."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


FISH_TTS_URL = "https://api.fish.audio/v1/tts"
FISH_MODEL = "s2-pro"
FPS = 30
WIDTH = 1920
HEIGHT = 1080
REQUIRED_SCENE_FIELDS = (
    "scene_number",
    "narration",
    "visual_description",
    "image_prompt",
)
NO_TEXT_MARKERS = (
    "no captions",
    "no subtitles",
    "no labels",
    "no logos",
    "no watermarks",
)


class PipelineError(RuntimeError):
    pass


def say(message: str) -> None:
    print(message, flush=True)


def load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PipelineError(f"Missing required file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PipelineError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PipelineError(f"Expected a JSON object in {path}")
    return data


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug[:54].rstrip("-") or "motivational-video")


def project_root_from_run(run_dir: Path) -> Path:
    resolved = run_dir.resolve()
    if resolved.parent.name != "output":
        raise PipelineError("Run directory must be a direct child of the project output/ folder")
    return resolved.parent.parent


def scene_plan_path(run_dir: Path) -> Path:
    return run_dir / "work" / "scenes.json"


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def resolve_credentials(project_root: Path, env_file: Path | None = None) -> tuple[str, str]:
    file_values = load_env_file(env_file or (project_root / ".env"))
    api_key = os.environ.get("FISH_API_KEY") or file_values.get("FISH_API_KEY", "")
    voice_id = os.environ.get("FISH_VOICE_ID") or file_values.get("FISH_VOICE_ID", "")
    missing = [
        name
        for name, value in (("FISH_API_KEY", api_key), ("FISH_VOICE_ID", voice_id))
        if not value.strip()
    ]
    if missing:
        raise PipelineError(
            f"Missing {', '.join(missing)} in {env_file or (project_root / '.env')}"
        )
    return api_key.strip(), voice_id.strip()


def require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise PipelineError(f"Required executable not found on PATH: {name}")
    return path


def validate_plan_data(plan: dict[str, Any], require_no_text_markers: bool = True) -> list[dict[str, Any]]:
    for field in ("title", "topic", "target_duration_seconds", "character_bible", "visual_style", "scenes"):
        if field not in plan:
            raise PipelineError(f"Scene plan is missing top-level field: {field}")
    if not isinstance(plan["target_duration_seconds"], (int, float)) or plan["target_duration_seconds"] <= 0:
        raise PipelineError("target_duration_seconds must be positive")
    if not isinstance(plan["character_bible"], str) or not plan["character_bible"].strip():
        raise PipelineError("character_bible must be a non-empty string")
    if not isinstance(plan["visual_style"], str) or not plan["visual_style"].strip():
        raise PipelineError("visual_style must be a non-empty string")
    scenes = plan["scenes"]
    if not isinstance(scenes, list) or not scenes:
        raise PipelineError("scenes must be a non-empty array")
    for expected, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise PipelineError(f"Scene {expected} must be an object")
        missing = [field for field in REQUIRED_SCENE_FIELDS if field not in scene]
        if missing:
            raise PipelineError(f"Scene {expected} is missing: {', '.join(missing)}")
        if scene["scene_number"] != expected:
            raise PipelineError(
                f"Scene numbers must be consecutive from 1; expected {expected}, got {scene['scene_number']}"
            )
        for field in REQUIRED_SCENE_FIELDS[1:]:
            if not isinstance(scene[field], str) or not scene[field].strip():
                raise PipelineError(f"Scene {expected} field {field} must be non-empty text")
        if expected > 1 and require_no_text_markers:
            prompt = scene["image_prompt"].lower()
            absent = [marker for marker in NO_TEXT_MARKERS if marker not in prompt]
            if absent:
                raise PipelineError(
                    f"Scene {expected} image_prompt must explicitly include all no-text safeguards: {', '.join(absent)}"
                )
    return scenes


def command_check(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    require_binary("python3")
    require_binary("ffmpeg")
    require_binary("ffprobe")
    resolve_credentials(root, Path(args.env_file).resolve() if args.env_file else None)
    say("Prerequisites OK: python3, ffmpeg, ffprobe, and both Fish Audio environment values are available.")


def command_init(args: argparse.Namespace) -> None:
    root = Path(args.project_root).resolve()
    if args.duration_seconds < 15:
        raise PipelineError("Target duration must be at least 15 seconds")
    timestamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = args.run_id or f"{timestamp}-{slugify(args.topic)}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
        raise PipelineError("run-id may contain only letters, digits, dots, underscores, and hyphens")
    run_dir = root / "output" / run_id
    if run_dir.exists():
        raise PipelineError(f"Run directory already exists: {run_dir}")
    for relative in ("work/audio", "work/images", "work/video"):
        (run_dir / relative).mkdir(parents=True, exist_ok=False)
    metadata = {
        "run_id": run_id,
        "topic": args.topic,
        "target_duration_seconds": args.duration_seconds,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "status": "initialized",
    }
    write_json(run_dir / "metadata.json", metadata)
    template_path = Path(__file__).resolve().parents[1] / "assets" / "scenes.template.json"
    plan = load_json(template_path)
    plan["title"] = args.topic.strip()
    plan["topic"] = args.topic.strip()
    plan["target_duration_seconds"] = args.duration_seconds
    write_json(scene_plan_path(run_dir), plan)
    say(str(run_dir))


def command_validate_plan(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    plan = load_json(scene_plan_path(run_dir))
    scenes = validate_plan_data(plan)
    say(f"Plan OK: {len(scenes)} consecutive scenes.")


def request_tts(text: str, api_key: str, voice_id: str) -> bytes:
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
    request = urllib.request.Request(
        FISH_TTS_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "model": FISH_MODEL,
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                audio = response.read()
            if len(audio) < 1024:
                raise PipelineError("Fish Audio returned an unexpectedly small audio response")
            return audio
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            if exc.code not in {408, 429, 500, 502, 503, 504} or attempt == 3:
                raise PipelineError(f"Fish Audio HTTP {exc.code}: {detail}") from exc
            last_error = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt == 3:
                break
        time.sleep(2 ** (attempt - 1))
    raise PipelineError(f"Fish Audio request failed after 3 attempts: {last_error}")


def command_tts(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    root = project_root_from_run(run_dir)
    plan = load_json(scene_plan_path(run_dir))
    scenes = validate_plan_data(plan)
    env_file = Path(args.env_file).resolve() if args.env_file else None
    api_key, voice_id = resolve_credentials(root, env_file)
    audio_dir = run_dir / "work" / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for scene in scenes:
        number = scene["scene_number"]
        output = audio_dir / f"{number:03d}.mp3"
        if output.is_file() and output.stat().st_size >= 1024 and not args.force:
            say(f"Skip existing {output.name}")
            continue
        say(f"Synthesizing scene {number:03d}/{len(scenes):03d}")
        audio = request_tts(scene["narration"], api_key, voice_id)
        partial = output.with_suffix(".mp3.part")
        partial.write_bytes(audio)
        partial.replace(output)
    say(f"Narration complete: {audio_dir}")


def probe_duration(path: Path) -> float:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        duration = float(result.stdout.strip())
    except ValueError as exc:
        raise PipelineError(f"Could not read duration for {path}") from exc
    if duration <= 0:
        raise PipelineError(f"Non-positive duration for {path}")
    return duration


def probe_final_media(path: Path) -> dict[str, Any]:
    ffprobe = require_binary("ffprobe")
    result = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise PipelineError("Final MP4 must contain both a video stream and an audio stream")
    if video.get("width") != WIDTH or video.get("height") != HEIGHT:
        raise PipelineError(
            f"Final MP4 has wrong dimensions: {video.get('width')}x{video.get('height')}"
        )
    duration = float(data.get("format", {}).get("duration", 0))
    if duration <= 0:
        raise PipelineError("Final MP4 has no positive duration")
    return {"duration_seconds": duration, "video": video, "audio": audio}


def collect_durations(run_dir: Path, scenes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for scene in scenes:
        number = scene["scene_number"]
        audio = run_dir / "work" / "audio" / f"{number:03d}.mp3"
        if not audio.is_file():
            raise PipelineError(f"Missing narration: {audio}")
        records.append(
            {
                "scene_number": number,
                "audio_file": str(audio.relative_to(run_dir)),
                "duration_seconds": round(probe_duration(audio), 6),
            }
        )
    return records


def duration_report(plan: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    actual = sum(record["duration_seconds"] for record in records)
    target = float(plan["target_duration_seconds"])
    tolerance = max(5.0, target * 0.08)
    return {
        "target_duration_seconds": target,
        "actual_duration_seconds": round(actual, 6),
        "difference_seconds": round(actual - target, 6),
        "tolerance_seconds": round(tolerance, 6),
        "within_tolerance": abs(actual - target) <= tolerance,
        "scenes": records,
    }


def enforce_duration(report: dict[str, Any]) -> None:
    if not report["within_tolerance"]:
        raise PipelineError(
            f"Narration duration is outside tolerance by "
            f"{abs(report['difference_seconds']):.2f}s; revise narration, "
            "rerun TTS with --force, and probe again"
        )


def command_probe(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    plan = load_json(scene_plan_path(run_dir))
    scenes = validate_plan_data(plan)
    records = collect_durations(run_dir, scenes)
    report = duration_report(plan, records)
    write_json(run_dir / "work" / "durations.json", report)
    say(
        f"Measured {len(records)} narration files: "
        f"{report['actual_duration_seconds']:.2f}s total for a "
        f"{report['target_duration_seconds']:.2f}s target."
    )
    enforce_duration(report)


def run_process(command: list[str], label: str) -> None:
    try:
        subprocess.run(command, check=True)
    except subprocess.CalledProcessError as exc:
        raise PipelineError(f"{label} failed with exit code {exc.returncode}") from exc


def motion_filter(scene_number: int, frame_count: int) -> str:
    frames = max(frame_count, 1)
    if scene_number % 2:
        zoom = f"min(1.035,1+0.035*on/{frames})"
    else:
        zoom = f"max(1.0,1.035-0.035*on/{frames})"
    return (
        f"scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH}:{HEIGHT},"
        f"zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d=1:s={WIDTH}x{HEIGHT}:fps={FPS},format=yuv420p"
    )


def command_render(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    plan = load_json(scene_plan_path(run_dir))
    scenes = validate_plan_data(plan)
    durations = collect_durations(run_dir, scenes)
    report = duration_report(plan, durations)
    write_json(run_dir / "work" / "durations.json", report)
    enforce_duration(report)
    ffmpeg = require_binary("ffmpeg")
    video_dir = run_dir / "work" / "video"
    video_dir.mkdir(parents=True, exist_ok=True)
    for scene, record in zip(scenes, durations):
        number = scene["scene_number"]
        image = run_dir / "work" / "images" / f"{number:03d}.png"
        audio = run_dir / "work" / "audio" / f"{number:03d}.mp3"
        output = video_dir / f"{number:03d}.mp4"
        if not image.is_file():
            raise PipelineError(f"Missing scene image: {image}")
        if output.is_file() and output.stat().st_size > 0 and not args.force:
            say(f"Skip existing {output.name}")
            continue
        duration = float(record["duration_seconds"])
        frames = max(1, round(duration * FPS))
        say(f"Rendering scene {number:03d}/{len(scenes):03d}")
        run_process(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "warning",
                "-y",
                "-loop",
                "1",
                "-framerate",
                str(FPS),
                "-i",
                str(image),
                "-i",
                str(audio),
                "-vf",
                motion_filter(number, frames),
                "-t",
                f"{duration:.6f}",
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-r",
                str(FPS),
                "-c:a",
                "aac",
                "-af",
                "aresample=async=1:first_pts=0",
                "-b:a",
                "192k",
                "-ar",
                "44100",
                "-ac",
                "1",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                "-avoid_negative_ts",
                "make_zero",
                "-shortest",
                str(output),
            ],
            f"Render scene {number:03d}",
        )
    say(f"Rendered {len(scenes)} scene videos: {video_dir}")


def command_assemble(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    plan = load_json(scene_plan_path(run_dir))
    scenes = validate_plan_data(plan)
    ffmpeg = require_binary("ffmpeg")
    work_dir = run_dir / "work"
    lines: list[str] = []
    for scene in scenes:
        relative = Path("video") / f"{scene['scene_number']:03d}.mp4"
        clip = work_dir / relative
        if not clip.is_file() or clip.stat().st_size == 0:
            raise PipelineError(f"Missing rendered scene: {clip}")
        lines.append(f"file '{relative.as_posix()}'")
    concat_file = work_dir / "concat.txt"
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    final_path = run_dir / "final.mp4"
    run_process(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            "-avoid_negative_ts",
            "make_zero",
            str(final_path),
        ],
        "Final assembly",
    )
    final_media = probe_final_media(final_path)
    final_duration = float(final_media["duration_seconds"])
    durations = collect_durations(run_dir, scenes)
    manifest = {
        "run_id": run_dir.name,
        "title": plan["title"],
        "topic": plan["topic"],
        "target_duration_seconds": plan["target_duration_seconds"],
        "actual_duration_seconds": round(final_duration, 6),
        "scene_count": len(scenes),
        "resolution": f"{WIDTH}x{HEIGHT}",
        "fps": FPS,
        "video_stream": final_media["video"],
        "audio_stream": final_media["audio"],
        "fish_audio_model": FISH_MODEL,
        "final_file": "final.mp4",
        "scenes": durations,
        "completed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    write_json(run_dir / "manifest.json", manifest)
    metadata_path = run_dir / "metadata.json"
    metadata = load_json(metadata_path)
    metadata["status"] = "complete"
    metadata["completed_at"] = manifest["completed_at"]
    write_json(metadata_path, metadata)
    say(str(final_path))


def command_build(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    project_root = project_root_from_run(run_dir)
    check_args = argparse.Namespace(project_root=str(project_root), env_file=args.env_file)
    command_check(check_args)
    command_tts(args)
    command_probe(args)
    command_render(args)
    command_assemble(args)


def command_status(args: argparse.Namespace) -> None:
    run_dir = Path(args.run).resolve()
    scenes = validate_plan_data(load_json(scene_plan_path(run_dir)))
    groups = {
        "audio": run_dir / "work" / "audio",
        "images": run_dir / "work" / "images",
        "video": run_dir / "work" / "video",
    }
    for label, directory in groups.items():
        suffix = {"audio": ".mp3", "images": ".png", "video": ".mp4"}[label]
        present = sum((directory / f"{scene['scene_number']:03d}{suffix}").is_file() for scene in scenes)
        say(f"{label}: {present}/{len(scenes)}")
    say(f"final: {'present' if (run_dir / 'final.mp4').is_file() else 'missing'}")


def command_self_test(_: argparse.Namespace) -> None:
    sample = {
        "title": "Small Steps",
        "topic": "persistence",
        "target_duration_seconds": 60,
        "character_bible": "A small stick figure with a muted ochre scarf.",
        "visual_style": "Hand-painted editorial illustration.",
        "scenes": [
            {
                "scene_number": 1,
                "narration": "A traveler stopped at the foot of a hill.",
                "visual_description": "The traveler faces one steep hill.",
                "image_prompt": "No captions, no subtitles, no labels, no logos, no watermarks.",
            },
            {
                "scene_number": 2,
                "narration": "Then one small step changed the journey.",
                "visual_description": "One footprint appears on the path.",
                "image_prompt": "No captions, no subtitles, no labels, no logos, no watermarks.",
            },
        ],
    }
    validate_plan_data(sample)
    assert slugify("  Keep Going!  ") == "keep-going"
    say("Self-test OK.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="Check executables and Fish Audio environment values")
    check.add_argument("--project-root", default=".")
    check.add_argument("--env-file")
    check.set_defaults(func=command_check)

    init = subparsers.add_parser("init", help="Create a unique output run folder")
    init.add_argument("--project-root", default=".")
    init.add_argument("--topic", required=True)
    init.add_argument("--duration-seconds", required=True, type=int)
    init.add_argument("--run-id")
    init.set_defaults(func=command_init)

    validate = subparsers.add_parser("validate-plan", help="Validate work/scenes.json")
    validate.add_argument("--run", required=True)
    validate.set_defaults(func=command_validate_plan)

    tts = subparsers.add_parser("tts", help="Generate per-scene Fish Audio narration")
    tts.add_argument("--run", required=True)
    tts.add_argument("--env-file")
    tts.add_argument("--force", action="store_true")
    tts.set_defaults(func=command_tts)

    probe = subparsers.add_parser("probe", help="Measure every narration with ffprobe")
    probe.add_argument("--run", required=True)
    probe.set_defaults(func=command_probe)

    render = subparsers.add_parser("render", help="Render one subtle-motion MP4 per image/audio pair")
    render.add_argument("--run", required=True)
    render.add_argument("--force", action="store_true")
    render.set_defaults(func=command_render)

    assemble = subparsers.add_parser("assemble", help="Concatenate scene videos into final.mp4")
    assemble.add_argument("--run", required=True)
    assemble.set_defaults(func=command_assemble)

    build = subparsers.add_parser("build", help="Run TTS, probe, render, and assemble")
    build.add_argument("--run", required=True)
    build.add_argument("--env-file")
    build.add_argument("--force", action="store_true")
    build.set_defaults(func=command_build)

    status = subparsers.add_parser("status", help="Show artifact completion counts")
    status.add_argument("--run", required=True)
    status.set_defaults(func=command_status)

    self_test = subparsers.add_parser("self-test", help="Run offline helper sanity checks")
    self_test.set_defaults(func=command_self_test)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"ERROR: command failed with exit code {exc.returncode}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
