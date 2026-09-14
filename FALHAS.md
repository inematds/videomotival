# Changelog de falhas — videomotival

| data | o que quebrou | menor correção | prompt \| infra |
|---|---|---|---|
| 2026-09-13 | `recompose` não detectava edição feita à mão no `scenes.json` (diff era contra o próprio arquivo) e `_invalidate_clips` sumiu numa substituição de bloco (NameError) | diff contra `work/scenes.applied.json` (último plano materializado) + função reposta | prompt |
| 2026-09-13 | portas 8020 e 8021 já ocupadas por outros serviços locais; `serve` morria com "address already in use" | default do `serve` para 8030 + checar `ss -ltn` antes de escolher porta | infra |
| 2026-09-13 | `glm-5.2` (OpenRouter) devolveu `{\n{...}` — brace solto antes do JSON; parser pegava do 1º `{` e falhava | `extract_json_object` tenta `raw_decode` a partir de cada `{` e aceita o primeiro objeto com `scenes` | prompt |
| 2026-09-13 | título da cena 1 cortado ("A MOTIVAÇÃO V"): drawtext do ffmpeg 6.1 perde N caracteres finais quando há N acentos (UTF-8 contado em bytes) | renderizar o título com Pillow em PNG transparente e sobrepor com `overlay` | infra |
| 2026-09-13 | ffmpeg recusou saída temporária `001.part` ("Unable to choose an output format") | temporário com extensão real (`001.part.mp3`) + `-f mp3` explícito | infra |
| 2026-09-13 | Groq: HTTP 403 Cloudflare `1010` com o User-Agent padrão do urllib; depois 404 porque `llama-3.3-70b-versatile` saiu do catálogo | `User-Agent` próprio em toda chamada (verificado: 403 sumiu) + `GROQ_MODEL=openai/gpt-oss-120b` | infra |
