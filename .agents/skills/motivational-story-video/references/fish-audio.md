# Fish Audio TTS integration

Verified against the official Fish Audio documentation on 2026-09-05.

Authoritative pages:

- https://docs.fish.audio/api-reference/endpoint/openapi-v1/text-to-speech
- https://docs.fish.audio/developer-guide/models-pricing/models-overview
- https://docs.fish.audio/developer-guide/getting-started/quickstart
- Canonical schema: https://api.fish.audio/openapi.json

## Current REST contract

- Endpoint: `POST https://api.fish.audio/v1/tts`
- Authentication: `Authorization: Bearer <FISH_API_KEY>`
- Content type: `application/json`
- Model selector: required HTTP header `model: s2-pro`
- Voice selector: JSON field `reference_id`, populated from `FISH_VOICE_ID`
- Output: binary audio body; request `format: mp3`

Fish Audio currently calls the recommended Pro model **S2-Pro**; its API identifier is `s2-pro`. Do not substitute the obsolete `s2` string.

The bundled helper sends a single scene at a time with high-quality MP3 settings and normal latency. It uses only the Python standard library, never writes secrets to disk, retries transient HTTP/network failures at most three times, and writes each response atomically before renaming it to the final numbered MP3.

## Environment file

Read the project-root `.env`:

```dotenv
FISH_API_KEY=replace_with_your_api_key
FISH_VOICE_ID=replace_with_your_voice_reference_id
```

Never commit a populated `.env` or echo these values. If either key is absent or blank, stop before calling the API.

## Maintenance rule

Before changing the endpoint, model header, request body, or authentication scheme, re-check the official endpoint page and canonical OpenAPI schema. Keep `s2-pro` unless Fish Audio's official current documentation explicitly changes the recommended Pro model identifier.
