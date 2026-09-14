"""Etapa 1 — tema → história original + plano de cenas (scenes.json).

Providers: openrouter | groq | ollama | manual (auto = tenta nessa ordem).
O LLM só escreve a parte criativa. Estilo visual, bíblia do personagem e o bloco
"sem texto" são anexados em código para não depender do modelo obedecer.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from .config import NO_TEXT_BLOCK, STYLE_BLOCK, Settings
from .util import PipelineError, extract_json_object, http_json, load_json, say, write_json

LANG_NAMES = {"pt": "português do Brasil", "en": "English", "es": "español", "fr": "français", "it": "italiano", "de": "Deutsch"}


def estimate_words(duration_seconds: int, wpm: float) -> int:
    return max(40, int(round(duration_seconds / 60.0 * wpm)))


def estimate_scene_count(duration_seconds: int) -> int:
    # cenas de ~8–14 s (o tutorial sugere 8–18 s); mínimo 3
    return max(3, int(round(duration_seconds / 11.0)))


def build_prompt(topic: str, duration_seconds: int, lang: str, wpm: float, extra: str = "") -> tuple[str, str]:
    lang_name = LANG_NAMES.get(lang, lang)
    words = estimate_words(duration_seconds, wpm)
    scenes = estimate_scene_count(duration_seconds)
    per_scene = max(12, words // scenes)
    system = (
        "You are a writer of short original motivational stories for an illustrated YouTube channel "
        "(hand-painted stick-figure illustrations on paper). You always answer with ONE valid JSON object "
        "and nothing else — no markdown fences, no commentary."
    )
    user = f"""
Write an ORIGINAL motivational story about the topic: "{topic}".

Hard constraints:
- Narration language: {lang_name}. Everything the audience hears must be in {lang_name}. Field names stay in English.
- Target spoken duration: {duration_seconds} seconds ≈ {words} words total at {wpm:.0f} words/minute. Stay within ±10% of {words} words.
- Split into exactly {scenes} scenes (±1). Each scene narration ≈ {per_scene} words, self-contained, speakable aloud, second person or a named character, emotionally varied.
- Story arc: (1) a specific human moment as hook, (2) relatable obstacle, (3) escalation / doubt, (4) believable pivot through a choice and an action (no magic), (5) concrete progress and payoff, (6) closing insight that invites action.
- No quotes from real motivational speakers, no listicles, no hollow slogans, no unsupported promises.
- Protagonist: ONE stick-figure character kept identical in every scene. Describe it in `character_bible` using only visible, repeatable traits (body proportion, ONE muted clothing accent colour such as an ochre scarf, ONE simple prop or feature, posture, line weight). The bible is written in English because it feeds an image model.
- `image_prompt` for each scene: in English, 1–3 sentences, ONLY the scene-specific composition: what the stick figure is doing, the visual metaphor, environment, camera framing, mood, where the negative space is. Do NOT describe the painting style (it is appended automatically). Do NOT ask for any text, letters, signs or labels in the image. For scene 1 leave the upper third of the frame empty (a title will be overlaid there).
- `visual_description`: in {lang_name}, one sentence for the human reviewer.
- `title`: short original title in {lang_name} (max 6 words), suitable to print on the first frame.
{extra}

Return exactly this JSON shape:
{{
  "title": "...",
  "character_bible": "...",
  "scenes": [
    {{"scene_number": 1, "narration": "...", "visual_description": "...", "image_prompt": "..."}}
  ]
}}
""".strip()
    return system, user


# ---------------------------------------------------------------- providers


def _chat_openai_compatible(url: str, key: str, model: str, system: str, user: str, json_mode: bool = True) -> str:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.8,
        "max_tokens": 4000,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    data = http_json(url, body, headers={"Authorization": f"Bearer {key}"}, timeout=180)
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise PipelineError(f"Resposta inesperada do provedor: {str(data)[:300]}") from exc


def _provider_openrouter(settings: Settings, system: str, user: str) -> str:
    key = Settings.secret("OPENROUTER_API_KEY")
    if not key:
        raise PipelineError("OPENROUTER_API_KEY ausente")
    model = settings.get("OPENROUTER_MODEL")
    say(f"[story] openrouter/{model}")
    return _chat_openai_compatible("https://openrouter.ai/api/v1/chat/completions", key, model, system, user)


def _provider_groq(settings: Settings, system: str, user: str) -> str:
    key = Settings.secret("GROQ_API_KEY")
    if not key:
        raise PipelineError("GROQ_API_KEY ausente")
    model = settings.get("GROQ_MODEL")
    say(f"[story] groq/{model}")
    return _chat_openai_compatible("https://api.groq.com/openai/v1/chat/completions", key, model, system, user)


def _provider_ollama(settings: Settings, system: str, user: str) -> str:
    model = settings.get("OLLAMA_MODEL")
    say(f"[story] ollama/{model}")
    body = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "stream": False,
        "format": "json",
        "think": False,
        "options": {"temperature": 0.8, "num_predict": 4000},
    }
    data = http_json(settings.get("OLLAMA_URL").rstrip("/") + "/api/chat", body, timeout=900, retries=1)
    try:
        return data["message"]["content"]
    except (KeyError, TypeError) as exc:
        raise PipelineError(f"Resposta inesperada do Ollama: {str(data)[:300]}") from exc


PROVIDERS = {"openrouter": _provider_openrouter, "groq": _provider_groq, "ollama": _provider_ollama}
AUTO_ORDER = ("openrouter", "groq", "ollama")


def generate_raw(settings: Settings, system: str, user: str) -> tuple[str, str]:
    provider = settings.get("STORY_PROVIDER").strip().lower() or "auto"
    order = AUTO_ORDER if provider == "auto" else (provider,)
    errors: list[str] = []
    for name in order:
        func = PROVIDERS.get(name)
        if func is None:
            raise PipelineError(f"STORY_PROVIDER desconhecido: {name} (use auto|openrouter|groq|ollama|manual)")
        try:
            return name, func(settings, system, user)
        except PipelineError as exc:
            errors.append(f"{name}: {exc}")
            say(f"[story] {name} falhou: {str(exc)[:160]}")
    raise PipelineError("Nenhum provedor de história respondeu — " + " || ".join(errors))


# ---------------------------------------------------------------- pós-processamento


def finalize_plan(raw: dict[str, Any], topic: str, duration_seconds: int, lang: str, provider: str, image_seed: int) -> dict[str, Any]:
    scenes_in = raw.get("scenes")
    if not isinstance(scenes_in, list) or not scenes_in:
        raise PipelineError("O modelo não devolveu a lista `scenes`")
    bible = str(raw.get("character_bible", "")).strip()
    if not bible:
        raise PipelineError("O modelo não devolveu `character_bible`")
    title = str(raw.get("title", "")).strip() or topic
    scenes: list[dict[str, Any]] = []
    for index, item in enumerate(scenes_in, start=1):
        if not isinstance(item, dict):
            raise PipelineError(f"Cena {index} não é um objeto")
        narration = str(item.get("narration", "")).strip()
        composition = str(item.get("image_prompt", "")).strip()
        if not narration or not composition:
            raise PipelineError(f"Cena {index} sem narration ou image_prompt")
        scenes.append(
            {
                "scene_number": index,
                "narration": narration,
                "visual_description": str(item.get("visual_description", "")).strip() or composition,
                "composition": composition,
                "image_prompt": compose_image_prompt(composition, bible, index),
            }
        )
    return {
        "title": title,
        "topic": topic,
        "lang": lang,
        "target_duration_seconds": duration_seconds,
        "character_bible": bible,
        "visual_style": STYLE_BLOCK,
        "image_seed": image_seed,
        "title_overlay": True,
        "story_provider": provider,
        "scenes": scenes,
    }


def compose_image_prompt(composition: str, bible: str, scene_number: int) -> str:
    parts = [STYLE_BLOCK, f"Main character (keep identical in every scene): {bible}", f"Scene: {composition}"]
    if scene_number == 1:
        parts.append("Leave the upper third of the frame as empty paper (clean negative space for a title added later).")
    parts.append(NO_TEXT_BLOCK)
    return " ".join(parts)


def refresh_image_prompts(plan: dict[str, Any]) -> dict[str, Any]:
    """Recompõe image_prompt a partir de composition + bíblia (após edição humana)."""
    bible = plan["character_bible"]
    for scene in plan["scenes"]:
        composition = scene.get("composition") or scene.get("image_prompt", "")
        scene["composition"] = composition
        scene["image_prompt"] = compose_image_prompt(composition, bible, scene["scene_number"])
    plan["visual_style"] = STYLE_BLOCK
    return plan


def write_story_files(run_dir: Path, plan: dict[str, Any]) -> None:
    work = run_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    write_json(work / "scenes.json", plan)
    transcript = "\n\n".join(scene["narration"] for scene in plan["scenes"])
    (work / "transcript.md").write_text(f"# {plan['title']}\n\n{transcript}\n", encoding="utf-8")
    lines = [f"# {plan['title']}", "", f"Tema: {plan['topic']}", f"Duração alvo: {plan['target_duration_seconds']} s", "", "## Personagem", "", plan["character_bible"], ""]
    for scene in plan["scenes"]:
        lines += [f"## Cena {scene['scene_number']}", "", f"**Narração:** {scene['narration']}", "", f"**Visual:** {scene['visual_description']}", ""]
    (work / "story.md").write_text("\n".join(lines), encoding="utf-8")


def load_calibration(settings: Settings) -> float:
    path = settings.output_root / "calibration.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        wpm = float(data.get("words_per_minute", 0))
        if 60 <= wpm <= 260:
            return wpm
    except Exception:
        pass
    return settings.get_float("WORDS_PER_MINUTE")


def save_calibration(settings: Settings, words: int, seconds: float, lang: str, voice: str) -> None:
    if words <= 0 or seconds <= 0:
        return
    path = settings.output_root / "calibration.json"
    previous = load_calibration(settings)
    measured = words / seconds * 60.0
    # média móvel suave para não oscilar com uma corrida atípica
    blended = round(previous * 0.5 + measured * 0.5, 1)
    write_json(path, {"words_per_minute": blended, "last_measured": round(measured, 1), "lang": lang, "voice": voice})


def generate_plan(run_dir: Path, settings: Settings, topic: str, duration_seconds: int, lang: str, image_seed: int, extra: str = "") -> dict[str, Any]:
    provider_setting = settings.get("STORY_PROVIDER").strip().lower()
    if provider_setting == "manual":
        plan_path = run_dir / "work" / "scenes.json"
        plan = load_json(plan_path)
        if not plan.get("scenes"):
            raise PipelineError(f"STORY_PROVIDER=manual: escreva o plano em {plan_path} antes (ver templates/scenes.template.json)")
        plan.setdefault("image_seed", image_seed)
        plan.setdefault("title_overlay", True)
        plan.setdefault("lang", lang)
        plan = refresh_image_prompts(plan)
        write_story_files(run_dir, plan)
        return plan
    wpm = load_calibration(settings)
    system, user = build_prompt(topic, duration_seconds, lang, wpm, extra)
    provider, text = generate_raw(settings, system, user)
    (run_dir / "work" / "story_raw.txt").write_text(text, encoding="utf-8")
    raw = extract_json_object(text)
    plan = finalize_plan(raw, topic, duration_seconds, lang, provider, image_seed)
    words = sum(len(scene["narration"].split()) for scene in plan["scenes"])
    plan["estimated_words"] = words
    plan["words_per_minute_used"] = wpm
    plan["estimated_seconds"] = round(words / wpm * 60.0, 1)
    write_story_files(run_dir, plan)
    say(f"[story] {len(plan['scenes'])} cenas, {words} palavras (~{plan['estimated_seconds']} s a {wpm:.0f} wpm)")
    return plan
