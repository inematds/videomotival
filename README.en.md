# videomotival

**🇧🇷 [Português](README.md) · 🇺🇸 [English](README.en.md) · 🇪🇸 [Español](README.es.md)**

## 📖 User Guide

Complete guide (landing page + step-by-step instructions): **https://inematds.github.io/videomotival/guia/en/**

Automated motivational channel, zero cost, running locally:

```
TOPIC → STORY (LLM) → SCENES → VOICE per scene (inemavox) → ILLUSTRATIONS (flux2-klein) → ffprobe → FFmpeg → MP4 16:9
```

Implementation of the tutorial *"Build a $0 Motivational YouTube Channel Automation with Codex Skills"*
adapted to this machine’s ecosystem. The original tutorial zip (Codex skill + `video_pipeline.py`)
is preserved in `.agents/skills/motivational-story-video/` and `docs/tutorial-original/`.

Three ways to use it, all on the same pipeline:

| Mode | How |
|---|---|
| **Web interface** | `python3 -m videomotival serve` → http://127.0.0.1:8030 |
| **CLI** | `python3 -m videomotival create --topic "…" --duration 75 --auto` |
| **Claude Code skill** | `.claude/skills/motivational-story-video/SKILL.md` — "make a 90 s motivational video about X" |

## Requirements

- `ffmpeg` / `ffprobe`, Python 3.12, Pillow (scene 1 title), FastAPI + uvicorn (web only).
- **inemavox** running at `localhost:8010` (voice: `chatterbox` + `rachel` by default; `edge` for tests without a GPU).
- **inemaimg** running at `localhost:8000` with `flux2-klein` (1920x1080 images, ~12 s each).
- An LLM key for the story, read at runtime from `~/projetos/openpcbotv2/.env` or `~/projetos/wifi/.env`
  (`OPENROUTER_API_KEY` → `GROQ_API_KEY` → local Ollama fallback). No keys in this repo.

```bash
pip install -r requirements.txt
python3 -m videomotival check        # checks everything without printing secrets
```

## Workflow (same as the tutorial, step by step)

```bash
# 1–3. topic → script + scenes (pauses for review)
python3 -m videomotival create --topic "Stop waiting for motivation" --duration 75
#    → ~/projetos/output/videomotival/<run-id>/work/{story.md,transcript.md,scenes.json}

# 4–5. narration per scene (001.mp3, 002.mp3…) + ffprobe measurement
python3 -m videomotival tts --run <run-id>

# 6. one illustration per scene (001.png, 002.png…), consistent character
python3 -m videomotival images --run <run-id>

# 7. scene = image + audio with a slow zoom; concat → final.mp4
python3 -m videomotival render --run <run-id> [--music trilha.mp3]

# 8. everything at once, without pauses
python3 -m videomotival create --topic "Why small progress beats big motivation" --duration 90 --auto
```

Other commands: `build` (tts+images+render), `recompose` (after manually editing `scenes.json`: recomposes
prompts and invalidates only the changed scenes), `regen-image --scene N`, `status`, `list`, `voices`.
Each step skips what already exists; `--force` reruns it.

## Structure of a Run

```
~/projetos/output/videomotival/<timestamp>-<slug>/
├── metadata.json        state (status, progress, error) — the web app reads this
├── manifest.json        verified result (1920x1080, duration, scenes)
├── final.mp4
└── work/
    ├── story.md, transcript.md, scenes.json, story_raw.txt, durations.json, log.txt
    ├── audio/001.mp3 …   images/001.png …   video/001.mp4 …
    └── title.png         scene 1 title (Pillow → ffmpeg overlay)
```

## Decisions That Differ from the Tutorial

- **Voice**: inemavox (chatterbox/rachel) instead of Fish Audio. The `fish` provider remains
  implemented (`TTS_PROVIDER=fish`, `FISH_VOICE_ID` in `.env`, `FISH_API_KEY` in the secret files).
- **Images**: local flux2-klein instead of "Codex image generation." Character consistency =
  verbatim bible in every prompt + fixed seed per run (no reference image).
- **Scene 1 title**: rendered by ffmpeg from a Pillow PNG (exact text), not requested from the
  image generator (flux is weak with lettering; ffmpeg 6.1 drawtext clips accents).
- **Duration gate**: `DURATION_GATE=warn` by default (the tutorial refuses to render outside ±8 %).
  Measured wpm is saved to `output/videomotival/calibration.json` and feeds back into the scriptwriter.
- **Language**: `pt` by default; `--lang en` reproduces the tutorial.
- **Breathing room**: 0.45 s of silence at the end of each narration (`AUDIO_PAD_SECONDS`).
- **Background music** is optional in assembly (`--music`, approx. -18 dB, fade).

## Configuration

Copy `.env.example` to `.env` and adjust. Everything in it is non-secret (providers, voice, URLs, ports).
Process environment variables take precedence over the file.

## Version

`videomotival/__init__.py` → `1.0.0`.
