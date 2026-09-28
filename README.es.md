# videomotival

**🇧🇷 [Português](README.md) · 🇺🇸 [English](README.en.md) · 🇪🇸 [Español](README.es.md)**

## 📖 Guía de uso

Guía completa (landing + paso a paso): **https://inematds.github.io/videomotival/guia/es/**

Canal motivacional automatizado, con costo cero y ejecución local:

```
TEMA → HISTORIA (LLM) → ESCENAS → VOZ por escena (inemavox) → ILUSTRACIONES (flux2-klein) → ffprobe → FFmpeg → MP4 16:9
```

Implementación del tutorial *"Build a $0 Motivational YouTube Channel Automation with Codex Skills"*
adaptada al ecosistema de esta máquina. El zip original del tutorial (skill Codex + `video_pipeline.py`)
se conserva en `.agents/skills/motivational-story-video/` y `docs/tutorial-original/`.

Tres formas de usarlo, todas sobre el mismo pipeline:

| Modo | Cómo |
|---|---|
| **Interfaz web** | `python3 -m videomotival serve` → http://127.0.0.1:8030 |
| **CLI** | `python3 -m videomotival create --topic "…" --duration 75 --auto` |
| **Skill de Claude Code** | `.claude/skills/motivational-story-video/SKILL.md` — "haz un video motivacional de 90 s sobre X" |

## Requisitos

- `ffmpeg` / `ffprobe`, Python 3.12, Pillow (título de la escena 1), FastAPI + uvicorn (solo para la web).
- **inemavox** ejecutándose en `localhost:8010` (voz: `chatterbox` + `rachel` por defecto; `edge` para pruebas sin GPU).
- **inemaimg** ejecutándose en `localhost:8000` con `flux2-klein` (imágenes 1920x1080, ~12 s cada una).
- Una clave de LLM para la historia, leída en tiempo de ejecución desde `~/projetos/openpcbotv2/.env` o `~/projetos/wifi/.env`
  (`OPENROUTER_API_KEY` → `GROQ_API_KEY` → alternativa Ollama local). No hay claves en este repo.

```bash
pip install -r requirements.txt
python3 -m videomotival check        # comprueba todo sin imprimir secretos
```

## Flujo (igual que el tutorial, paso a paso)

```bash
# 1–3. tema → guion + escenas (se detiene para revisión)
python3 -m videomotival create --topic "Deja de esperar la motivación" --duration 75
#    → ~/projetos/output/videomotival/<run-id>/work/{story.md,transcript.md,scenes.json}

# 4–5. narración por escena (001.mp3, 002.mp3…) + medición con ffprobe
python3 -m videomotival tts --run <run-id>

# 6. una ilustración por escena (001.png, 002.png…), personaje consistente
python3 -m videomotival images --run <run-id>

# 7. escena = imagen + audio con zoom lento; concat → final.mp4
python3 -m videomotival render --run <run-id> [--music trilha.mp3]

# 8. todo de una vez, sin pausas
python3 -m videomotival create --topic "Por qué el progreso pequeño vence a la gran motivación" --duration 90 --auto
```

Otros comandos: `build` (tts+images+render), `recompose` (después de editar `scenes.json` a mano: recompone
los prompts e invalida solo las escenas modificadas), `regen-image --scene N`, `status`, `list`, `voices`.
Cada etapa omite lo que ya existe; `--force` lo rehace.

## Estructura de una ejecución

```
~/projetos/output/videomotival/<timestamp>-<slug>/
├── metadata.json        estado (status, progreso, error) — la web lo lee desde aquí
├── manifest.json        resultado verificado (1920x1080, duración, escenas)
├── final.mp4
└── work/
    ├── story.md, transcript.md, scenes.json, story_raw.txt, durations.json, log.txt
    ├── audio/001.mp3 …   images/001.png …   video/001.mp4 …
    └── title.png         título de la escena 1 (Pillow → overlay ffmpeg)
```

## Decisiones que difieren del tutorial

- **Voz**: inemavox (chatterbox/rachel) en lugar de Fish Audio. El proveedor `fish` sigue
  implementado (`TTS_PROVIDER=fish`, `FISH_VOICE_ID` en `.env`, `FISH_API_KEY` en los archivos de secretos).
- **Imágenes**: flux2-klein local en lugar de "Codex image generation". La consistencia del personaje =
  biblia textual idéntica en cada prompt + seed fija por ejecución (sin imagen de referencia).
- **Título de la escena 1**: lo graba ffmpeg a partir de un PNG de Pillow (texto exacto); no se le pide al
  generador de imágenes (flux es débil con las letras; drawtext de ffmpeg 6.1 corta los acentos).
- **Umbral de duración**: `DURATION_GATE=warn` por defecto (el tutorial se niega a renderizar fuera de ±8 %).
  El wpm medido se guarda en `output/videomotival/calibration.json` y retroalimenta al guionista.
- **Idioma**: `pt` por defecto; `--lang en` reproduce el tutorial.
- **Pausa**: 0,45 s de silencio al final de cada narración (`AUDIO_PAD_SECONDS`).
- **Música de fondo** opcional en el montaje (`--music`, aprox. -18 dB, fade).

## Configuración

Copia `.env.example` a `.env` y ajústalo. Todo lo que hay allí no es secreto (proveedores, voz, urls, puertos).
Las variables de entorno del proceso prevalecen sobre el archivo.

## Versión

`videomotival/__init__.py` → `1.0.0`.
