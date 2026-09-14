# Story, scene, and image workflow

Use this reference for every new video run.

## Story planning

Aim for roughly 130–145 spoken English words per minute. Use the target duration to estimate the transcript length, then favor natural pacing over exact word-count padding. A useful default is 138 words per minute.

Choose enough scenes that each narration usually lasts about 8–18 seconds. Use fewer, longer scenes for reflective topics and more scenes for energetic topics. The story should have a clear arc:

1. A human hook grounded in a specific moment.
2. A relatable obstacle or internal conflict.
3. Escalation through failed attempts, doubt, or pressure.
4. A believable pivot based on choice and action rather than magic.
5. Concrete progress and emotional payoff.
6. A memorable closing insight that invites action.

Write an original story. Do not imitate or quote a living motivational speaker. Avoid generic listicles, unsupported promises, and hollow slogans. Keep narration speakable, emotionally varied, and suitable for the chosen target duration.

Save the prose version to `work/story.md` and the narration-only continuous version to `work/transcript.md`.

## Scene plan contract

Replace the initialized `work/scenes.json` with valid UTF-8 JSON in this shape:

```json
{
  "title": "A concise original title",
  "topic": "The user's topic",
  "target_duration_seconds": 180,
  "character_bible": "One precise, reusable protagonist description",
  "visual_style": "The stable style block",
  "scenes": [
    {
      "scene_number": 1,
      "narration": "Narration for this scene only.",
      "visual_description": "What the audience sees and why it supports the narration.",
      "image_prompt": "Complete standalone 16:9 image prompt."
    }
  ]
}
```

Scene numbers must start at 1 and be consecutive. Every narration must be self-contained because it is synthesized separately.

## Stable protagonist

Before writing image prompts, create one exact character bible. Specify only visible, repeatable traits, for example:

- stick-figure body and head proportions;
- a single muted clothing accent or scarf color;
- one simple identifying feature or prop;
- the character's baseline age impression and posture;
- line weight and facial-mark convention.

Copy the character bible verbatim into every image prompt. Do not add new identity traits later. Other figures should be visually secondary and should not share the protagonist's distinguishing accent.

## Stable style block

Include this block verbatim in every image prompt:

> 16:9 landscape motivational editorial illustration. Hand-painted, simple expressive stick-figure characters, slightly imperfect black ink brush strokes, soft off-white textured paper background, subtle watercolor and gouache paint, minimal composition, simple visual metaphor, limited muted colors, generous negative space, emotional handmade editorial illustration. Flat paper texture, restrained detail. Not photorealistic, not 3D, not vector-clean, not glossy.

Then add the scene-specific composition, emotion, metaphor, camera framing, and the exact character bible.

For every scene, append:

> No captions, no subtitles, no labels, no logos, no signatures, no watermarks, no random letters or typographic marks.

This no-text rule applies to all scenes by default. Scene 1 may instead contain exactly one large title only when exact title rendering is intentionally requested and can be verified. Scenes 2 onward never contain text.

## Image generation and review

Generate scene 1 first and inspect it before continuing. It establishes the visual anchor. For scenes 2 onward:

- reference `work/images/001.png` with the image-generation tool whenever supported;
- repeat the complete style and character blocks even when using a reference;
- save the returned image to the exact zero-padded scene filename;
- inspect at full enough detail to detect letters, watermarks, identity drift, and aspect-ratio mistakes;
- regenerate only the failed scene, keeping accepted work intact.

Do not proceed to final assembly until the image count exactly matches the scene count.

## Run layout

Each run lives at `output/<timestamp>-<topic-slug>/`:

```text
output/<run-id>/
|-- metadata.json
|-- manifest.json
|-- final.mp4
`-- work/
    |-- story.md
    |-- transcript.md
    |-- scenes.json
    |-- durations.json
    |-- audio/001.mp3
    |-- images/001.png
    `-- video/001.mp4
```

The helper is resumable: existing non-empty audio and scene-video files are preserved unless `--force` is supplied.
