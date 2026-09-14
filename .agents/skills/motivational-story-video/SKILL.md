---
name: motivational-story-video
description: Create a complete 16:9 illustrated motivational YouTube video from a topic and target duration. Use when the user asks for a motivational story video, inspirational narrative video, or a full topic-to-video workflow with original writing, per-scene Fish Audio narration, consistent image generation, and FFmpeg assembly.
---

# Motivational Story Video

Create the finished video, not only a script or storyboard. The normal inputs are `topic` and `target video duration`; infer reasonable creative choices without asking extra questions.

## Before running

1. Resolve this skill directory from the loaded `SKILL.md`; do not assume the current directory.
2. Treat the current project root as the directory containing `.env` and `output/`.
3. Read [references/workflow.md](references/workflow.md) before planning or generating a video.
4. Read [references/fish-audio.md](references/fish-audio.md) before changing or debugging the Fish Audio integration. The bundled script already implements the verified API contract.
5. Confirm `python3`, `ffmpeg`, and `ffprobe` are available. Confirm `.env` contains `FISH_API_KEY` and `FISH_VOICE_ID` without printing either value.

Run the helper with an absolute path derived from this skill directory:

```bash
python3 <skill-dir>/scripts/video_pipeline.py check --project-root <project-root>
```

If a prerequisite is missing, report exactly what is missing and stop before any paid API request.

## Required workflow

1. Convert the requested duration to seconds. Reject only non-positive or unusably short targets; otherwise proceed.
2. Initialize a unique run folder:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py init \
     --project-root <project-root> \
     --topic "<topic>" \
     --duration-seconds <seconds>
   ```

   Capture the printed run path. Every artifact for this video belongs under that run folder.
3. Write an original motivational story, transcript, character bible, and scene plan according to [references/workflow.md](references/workflow.md). Save:

   - `work/story.md`
   - `work/transcript.md`
   - `work/scenes.json`

4. Validate the plan before generating paid media:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py validate-plan --run <run-dir>
   ```

5. Generate one 16:9 image per scene with Codex image generation. Use the exact stable character bible and style block in every prompt. Save images as `work/images/001.png`, `002.png`, and so on.
6. Use the first accepted scene image as the character/style reference for every later image when the image tool supports local references. Inspect every image. Regenerate any image that contains unwanted text, a logo, watermark, random letters, photorealism, an inconsistent protagonist, or the wrong aspect ratio.
7. Generate each narration separately with Fish Audio S2-Pro:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py tts --run <run-dir>
   ```

   This reads `FISH_API_KEY` and `FISH_VOICE_ID` from the project `.env` and saves `work/audio/001.mp3`, `002.mp3`, and so on. Do not expose secrets in logs or generated files.
8. Measure every narration with ffprobe:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py probe --run <run-dir>
   ```

   The probe enforces a practical duration tolerance: within 8% of the target or 5 seconds, whichever is larger. If it fails, revise narration lengths proportionally, update `story.md`, `transcript.md`, and `scenes.json`, regenerate narration with `tts --force`, and probe again before rendering.

9. Render numbered image/audio pairs into scene videos with subtle motion, then assemble the final MP4:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py render --run <run-dir>
   python3 <skill-dir>/scripts/video_pipeline.py assemble --run <run-dir>
   ```

   After images exist, `build` may replace steps 7–9. It applies the same duration gate before rendering:

   ```bash
   python3 <skill-dir>/scripts/video_pipeline.py build --run <run-dir>
   ```

10. Verify the final manifest, final duration, 1920x1080 dimensions, playable audio, scene count, and absence of intermediate failures. Return the absolute final MP4 path and a concise artifact summary.

## Non-negotiable visual rules

- Use a hand-painted motivational editorial illustration style: simple expressive stick figures, slightly imperfect black ink brush strokes, soft off-white textured paper, subtle watercolor and gouache, minimal compositions, simple visual metaphors, limited muted colors, generous negative space, and emotional storytelling.
- Never use photorealism.
- Keep one clearly specified protagonist consistent throughout. Do not drift clothing accent, proportions, face marks, or distinguishing prop.
- Scene 1 may contain one large video title. Default to no generated text because generated lettering is unreliable; add a title only when it can be made exact and clean.
- Scenes 2 onward must contain absolutely no text: no captions, subtitles, labels, logos, random letters, signatures, or watermarks.
- Never add burned-in captions or subtitles.
- Motion must remain subtle: slow zoom or slow pan only, with no distracting cuts, shakes, spins, or parallax.

## Completion standard

Do not claim completion if any required scene image/audio pair is missing, if the scene numbering is non-contiguous, or if the final MP4 has not been probed successfully. Preserve completed artifacts on recoverable failures so a later run can resume without repeating paid work.
