---
name: motivational-story-video
description: Cria um vídeo motivacional ilustrado 16:9 completo (história original → narração por cena → ilustrações stick-figure consistentes → MP4 via FFmpeg) a partir de um tema e uma duração alvo. Use quando o usuário pedir "vídeo motivacional", "vídeo do canal motivacional", "história motivacional em vídeo", ou der um tema + duração para o pipeline videomotival.
---

# motivational-story-video (videomotival)

Versão Claude Code do tutorial "Motivational YouTube Channel Automation". O pipeline
determinístico vive em `videomotival/` deste projeto; esta skill só orquestra.

Entradas normais: **tema** e **duração alvo** (segundos ou "75s", "1m30"). Idioma padrão `pt`.
Não faça perguntas extras — escolhas criativas são suas.

## Antes de rodar

```bash
cd /home/nmaldaner/projetos/videomotival
python3 -m videomotival check
```

Se algo faltar (inemavox :8010, inemaimg :8000, ffmpeg), reporte exatamente o que e pare.
Não caia para provedor pago sem perguntar.

## Fluxo padrão (com revisão)

1. Criar a corrida e gerar o roteiro (para em `review`):
   ```bash
   python3 -m videomotival create --topic "<tema>" --duration <segundos> --lang pt
   ```
   O comando imprime a pasta da corrida em `~/projetos/output/videomotival/<run-id>/`.
2. Ler `work/scenes.json` e `work/story.md`. Revise você mesmo: arco em 6 movimentos
   (gancho humano → obstáculo → escalada → virada por escolha e ação → progresso concreto → insight final),
   narrações autocontidas, nenhuma cena pedindo texto na imagem.
   Para reescrever cenas, edite `narration` / `composition` / `visual_description` direto no JSON e rode
   `python3 -m videomotival recompose --run <run-id>` — recompõe os `image_prompt` e invalida áudio/imagem
   das cenas alteradas (as demais ficam). Funciona em qualquer momento, antes ou depois de gerar mídia.
   Se o usuário pediu para revisar antes, mostre o roteiro e **pare aqui**.
3. Produzir:
   ```bash
   python3 -m videomotival build --run <run-id>      # voz → medição → imagens → render → final.mp4
   ```
   Ou por etapa: `tts`, `images`, `render` (cada uma aceita `--force`).
4. Inspecionar `work/images/*.png` (Read). Regenerar a que tiver texto, logo, letras, fotorrealismo,
   protagonista diferente ou proporção errada:
   ```bash
   python3 -m videomotival regen-image --run <run-id> --scene <n>   # nova seed; apaga a cena renderizada
   python3 -m videomotival render --run <run-id>
   ```
5. Verificar `manifest.json` (1920x1080, áudio presente, duração ≈ soma das narrações) e devolver:
   caminho absoluto do `final.mp4`, pasta da corrida, `work/transcript.md`.

## Fluxo automático (sem paradas)

```bash
python3 -m videomotival create --topic "<tema>" --duration <segundos> --auto
```

Só interrompa se houver erro real. Ao final, devolva os três caminhos.

## Escrever a história você mesmo (sem LLM externo)

```bash
python3 -m videomotival create --topic "<tema>" --duration <s> --story-provider manual --no-plan
```
Escreva `work/scenes.json` no formato de `templates/scenes.template.json` (campos por cena:
`scene_number`, `narration`, `visual_description`, `composition`), depois
`python3 -m videomotival plan --run <run-id>` (recompõe prompts e gera story/transcript) e siga do passo 3.
Ritmo: ~140–150 palavras/min em pt com a voz `rachel` (`~/projetos/output/videomotival/calibration.json`
guarda o wpm medido nas corridas anteriores). Cenas de 8–14 s.

## Regras visuais inegociáveis

- Estilo: ilustração editorial pintada à mão, stick figures expressivos, tinta preta imperfeita, papel
  off-white texturizado, aquarela/guache sutil, composição mínima, metáfora visual simples, cores
  mudas limitadas, muito espaço negativo. Nunca fotorrealismo, 3D ou vetor limpo.
- Um protagonista, bíblia copiada verbatim em todo prompt (o pipeline faz isso). Consistência com
  flux2-klein é por prompt + seed fixa da corrida — sem referência de imagem. Drifts pequenos são
  esperados; regenere a cena quando o drift for grosseiro.
- Cena 1 pode ter o título — ele é gravado pelo ffmpeg (texto exato), não pedido ao gerador.
- Cenas 2+ sem texto algum. O bloco anti-texto é anexado em código a todo prompt.
- Sem legendas queimadas. Movimento só zoom lento alternado (3,5%).

## Padrão de conclusão

Não declare concluído se faltar par imagem/áudio de alguma cena, se a numeração não for contígua
ou se `final.mp4` não tiver sido verificado pelo ffprobe (o `assemble` já verifica e escreve `manifest.json`).
Artefatos concluídos são preservados: rerodar uma etapa pula o que já existe (use `--force` para refazer).

## Onde está cada coisa

- Configuração não secreta: `.env` do projeto (ver `.env.example`). Segredos: `~/projetos/openpcbotv2/.env` / `~/projetos/wifi/.env`, lidos em runtime.
- Voz padrão: inemavox `chatterbox` + `rachel`. Rápido para testes: `--engine edge --voice pt-BR-FranciscaNeural`.
- Imagens: inemaimg `flux2-klein` (GPU local, $0, ~12 s por imagem 1920x1080).
- Interface web: `python3 -m videomotival serve` → http://127.0.0.1:8030
