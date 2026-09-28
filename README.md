# videomotival

**🇧🇷 [Português](README.md) · 🇺🇸 [English](README.en.md) · 🇪🇸 [Español](README.es.md)**

## 📖 Guia de uso

Guia completo (landing + passo a passo): **https://inematds.github.io/videomotival/guia/**

Canal motivacional automatizado, custo zero, rodando local:

```
TEMA → HISTÓRIA (LLM) → CENAS → VOZ por cena (inemavox) → ILUSTRAÇÕES (flux2-klein) → ffprobe → FFmpeg → MP4 16:9
```

Implementação do tutorial *"Build a $0 Motivational YouTube Channel Automation with Codex Skills"*
adaptada ao ecossistema desta máquina. O zip original do tutorial (skill Codex + `video_pipeline.py`)
está preservado em `.agents/skills/motivational-story-video/` e `docs/tutorial-original/`.

Três jeitos de usar, todos sobre o mesmo pipeline:

| Modo | Como |
|---|---|
| **Interface web** | `python3 -m videomotival serve` → http://127.0.0.1:8030 |
| **CLI** | `python3 -m videomotival create --topic "…" --duration 75 --auto` |
| **Skill do Claude Code** | `.claude/skills/motivational-story-video/SKILL.md` — "faz um vídeo motivacional de 90 s sobre X" |

## Requisitos

- `ffmpeg` / `ffprobe`, Python 3.12, Pillow (título da cena 1), FastAPI + uvicorn (só para o web).
- **inemavox** rodando em `localhost:8010` (voz: `chatterbox` + `rachel` por padrão; `edge` para testes sem GPU).
- **inemaimg** rodando em `localhost:8000` com `flux2-klein` (imagens 1920x1080, ~12 s cada).
- Uma chave de LLM para a história, lida em runtime de `~/projetos/openpcbotv2/.env` ou `~/projetos/wifi/.env`
  (`OPENROUTER_API_KEY` → `GROQ_API_KEY` → fallback Ollama local). Nada de chave neste repo.

```bash
pip install -r requirements.txt
python3 -m videomotival check        # confere tudo sem imprimir segredos
```

## Fluxo (igual ao tutorial, etapa por etapa)

```bash
# 1–3. tema → roteiro + cenas (para em revisão)
python3 -m videomotival create --topic "Pare de esperar a motivação" --duration 75
#    → ~/projetos/output/videomotival/<run-id>/work/{story.md,transcript.md,scenes.json}

# 4–5. narração por cena (001.mp3, 002.mp3…) + medição ffprobe
python3 -m videomotival tts --run <run-id>

# 6. uma ilustração por cena (001.png, 002.png…), personagem consistente
python3 -m videomotival images --run <run-id>

# 7. cena = imagem + áudio com zoom lento; concat → final.mp4
python3 -m videomotival render --run <run-id> [--music trilha.mp3]

# 8. tudo de uma vez, sem paradas
python3 -m videomotival create --topic "Por que o progresso pequeno vence a motivação grande" --duration 90 --auto
```

Outros comandos: `build` (tts+images+render), `recompose` (depois de editar `scenes.json` à mão: recompõe
prompts e invalida só as cenas alteradas), `regen-image --scene N`, `status`, `list`, `voices`.
Cada etapa pula o que já existe; `--force` refaz.

## Estrutura de uma corrida

```
~/projetos/output/videomotival/<timestamp>-<slug>/
├── metadata.json        estado (status, progresso, erro) — a web lê daqui
├── manifest.json        resultado verificado (1920x1080, duração, cenas)
├── final.mp4
└── work/
    ├── story.md, transcript.md, scenes.json, story_raw.txt, durations.json, log.txt
    ├── audio/001.mp3 …   images/001.png …   video/001.mp4 …
    └── title.png         título da cena 1 (Pillow → overlay ffmpeg)
```

## Decisões que diferem do tutorial

- **Voz**: inemavox (chatterbox/rachel) no lugar de Fish Audio. O provedor `fish` continua
  implementado (`TTS_PROVIDER=fish`, `FISH_VOICE_ID` no `.env`, `FISH_API_KEY` nos arquivos de segredo).
- **Imagens**: flux2-klein local no lugar de "Codex image generation". Consistência do personagem =
  bíblia verbatim em todo prompt + seed fixa por corrida (sem imagem de referência).
- **Título da cena 1**: gravado pelo ffmpeg a partir de PNG do Pillow (texto exato), não pedido ao
  gerador de imagem (flux é fraco em letras; o drawtext do ffmpeg 6.1 corta acentos).
- **Portão de duração**: `DURATION_GATE=warn` por padrão (o tutorial recusa renderizar fora de ±8 %).
  O wpm medido é gravado em `output/videomotival/calibration.json` e realimenta o roteirista.
- **Idioma**: `pt` por padrão; `--lang en` reproduz o tutorial.
- **Respiro**: 0,45 s de silêncio ao fim de cada narração (`AUDIO_PAD_SECONDS`).
- **Música de fundo** opcional na montagem (`--music`, -18 dB aprox., fade).

## Configuração

Copie `.env.example` para `.env` e ajuste. Tudo ali é não secreto (provedores, voz, urls, portas).
Variáveis de ambiente do processo vencem o arquivo.

## Versão

`videomotival/__init__.py` → `1.0.0`.
