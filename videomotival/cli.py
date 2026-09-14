"""CLI: python3 -m videomotival <comando>.

  check                         verifica ffmpeg, provedores e chaves (sem imprimir segredos)
  create --topic T --duration S [--lang pt] [--auto]   cria a corrida (e, com --auto, faz tudo)
  plan   --run R                gera história + cenas (para em review)
  tts    --run R [--force]      narração por cena + medição
  images --run R [--force]      ilustração por cena
  render --run R [--music M]    probe + cenas + MP4 final
  build  --run R                tts + images + render
  recompose --run R             após editar scenes.json à mão
  regen-image --run R --scene N [--seed S]
  status --run R
  list
  serve [--port 8030]           interface web
"""

from __future__ import annotations

import argparse
import json
import sys

from . import __version__, pipeline, runner
from .config import Settings, list_voices
from .util import PipelineError, say


def _overrides(args: argparse.Namespace) -> dict[str, str]:
    mapping = {
        "story_provider": "STORY_PROVIDER",
        "tts_provider": "TTS_PROVIDER",
        "engine": "TTS_ENGINE",
        "voice": "TTS_VOICE",
        "image_model": "IMAGE_MODEL",
        "gate": "DURATION_GATE",
    }
    return {env: getattr(args, attr) for attr, env in mapping.items() if getattr(args, attr, None)}


def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--story-provider", choices=["auto", "openrouter", "groq", "ollama", "manual"])
    parser.add_argument("--tts-provider", choices=["inemavox", "fish"])
    parser.add_argument("--engine", choices=["chatterbox", "chatterbox-vc", "edge"])
    parser.add_argument("--voice")
    parser.add_argument("--image-model")
    parser.add_argument("--gate", choices=["warn", "strict"])


def cmd_check(args: argparse.Namespace) -> None:
    settings = Settings(_overrides(args))
    for note in runner.check_environment(settings):
        say("OK  " + note)
    say(f"saída: {settings.output_root}")


def cmd_create(args: argparse.Namespace) -> None:
    overrides = _overrides(args)
    settings = Settings(overrides)
    run_dir = runner.create_run(settings, args.topic, args.duration, args.lang, overrides, args.run_id, args.seed)
    if args.auto:
        runner.run_stages(run_dir, ["plan", "tts", "images", "render"], music=args.music)
        say(str(run_dir / "final.mp4"))
    elif not args.no_plan:
        runner.run_stages(run_dir, ["plan"])


def cmd_stage(stage: str):
    def handler(args: argparse.Namespace) -> None:
        settings = Settings()
        run_dir = runner.resolve_run(settings, args.run)
        stages = ["tts", "images", "render"] if stage == "build" else [stage]
        runner.run_stages(run_dir, stages, force=getattr(args, "force", False), music=getattr(args, "music", None), extra=getattr(args, "extra", "") or "")
        if stage in ("render", "build"):
            say(str(run_dir / "final.mp4"))

    return handler


def cmd_recompose(args: argparse.Namespace) -> None:
    run_dir = runner.resolve_run(Settings(), args.run)
    from .util import load_json
    plan = load_json(pipeline.scene_plan_path(run_dir))
    runner.save_plan(run_dir, plan)
    say(f"Plano recomposto: {len(plan['scenes'])} cenas — {pipeline.status(run_dir)}")


def cmd_regen(args: argparse.Namespace) -> None:
    run_dir = runner.resolve_run(Settings(), args.run)
    say(str(runner.regen_image(run_dir, args.scene, args.seed)))


def cmd_status(args: argparse.Namespace) -> None:
    run_dir = runner.resolve_run(Settings(), args.run)
    meta = runner.read_metadata(run_dir)
    say(json.dumps({"run": str(run_dir), "status": meta.get("status"), "error": meta.get("error"), **pipeline.status(run_dir)}, indent=2, ensure_ascii=False))


def cmd_list(args: argparse.Namespace) -> None:
    for meta in runner.list_runs(Settings()):
        c = meta["counts"]
        say(f"{meta['run_id']:<50} {meta.get('status', '?'):<9} cenas={c['scenes']} a={c['audio']} i={c['images']} v={c['video']} final={'sim' if c['final'] else 'não'}")


def cmd_voices(args: argparse.Namespace) -> None:
    for voice in list_voices(Settings()):
        say(f"{voice['id']:<36} {voice['engine']}")


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run("web.app:app", host=args.host, port=args.port, reload=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="videomotival", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"videomotival {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("check"); add_common(p); p.set_defaults(func=cmd_check)

    p = sub.add_parser("create")
    p.add_argument("--topic", required=True)
    p.add_argument("--duration", required=True, type=int, help="segundos")
    p.add_argument("--lang", default=None, help="pt | en | es ...")
    p.add_argument("--run-id")
    p.add_argument("--seed", type=int)
    p.add_argument("--auto", action="store_true", help="roda tudo sem parar para revisão")
    p.add_argument("--no-plan", action="store_true", help="só cria a pasta (para STORY_PROVIDER=manual)")
    p.add_argument("--music", help="arquivo de música de fundo (opcional)")
    add_common(p); p.set_defaults(func=cmd_create)

    for stage in ("plan", "tts", "images", "render", "build"):
        p = sub.add_parser(stage)
        p.add_argument("--run", required=True, help="run-id ou caminho da pasta")
        if stage != "plan":
            p.add_argument("--force", action="store_true")
        if stage in ("render", "build"):
            p.add_argument("--music")
        if stage == "plan":
            p.add_argument("--extra", help="instruções adicionais para o roteirista")
        p.set_defaults(func=cmd_stage(stage))

    p = sub.add_parser("recompose", help="após editar work/scenes.json à mão: recompõe prompts e invalida cenas alteradas"); p.add_argument("--run", required=True); p.set_defaults(func=cmd_recompose)
    p = sub.add_parser("regen-image"); p.add_argument("--run", required=True); p.add_argument("--scene", required=True, type=int); p.add_argument("--seed", type=int); p.set_defaults(func=cmd_regen)
    p = sub.add_parser("status"); p.add_argument("--run", required=True); p.set_defaults(func=cmd_status)
    p = sub.add_parser("list"); p.set_defaults(func=cmd_list)
    p = sub.add_parser("voices"); p.set_defaults(func=cmd_voices)
    p = sub.add_parser("serve"); p.add_argument("--host", default="127.0.0.1"); p.add_argument("--port", type=int, default=8030); p.set_defaults(func=cmd_serve)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except PipelineError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
