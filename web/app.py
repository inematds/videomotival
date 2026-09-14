"""Interface web local do videomotival (FastAPI).

Rodar: python3 -m videomotival serve --port 8030
Estado das corridas vive em disco (metadata.json) — o servidor só orquestra threads.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from videomotival import __version__, pipeline, runner  # noqa: E402
from videomotival.config import Settings, list_voices  # noqa: E402
from videomotival.util import PipelineError, load_json  # noqa: E402

app = FastAPI(title="videomotival", version=__version__)
STATIC = Path(__file__).resolve().parent / "static"


class CreateRun(BaseModel):
    topic: str
    duration: int = 75
    lang: str = "pt"
    story_provider: str | None = None
    tts_engine: str | None = None
    voice: str | None = None
    gate: str | None = None
    auto: bool = False
    extra: str = ""


class RunStages(BaseModel):
    stages: list[str]
    force: bool = False
    music: str | None = None
    only: int | list[int] | None = None


class RegenImage(BaseModel):
    seed: int | None = None


def _run_dir(run_id: str) -> Path:
    try:
        return runner.resolve_run(Settings(), run_id)
    except PipelineError as exc:
        raise HTTPException(404, str(exc)) from exc


def _run_payload(run_dir: Path) -> dict[str, Any]:
    meta = runner.read_metadata(run_dir)
    plan_path = pipeline.scene_plan_path(run_dir)
    plan = load_json(plan_path) if plan_path.is_file() else {}
    scenes = []
    durations: dict[int, float] = {}
    dur_path = run_dir / "work" / "durations.json"
    if dur_path.is_file():
        try:
            durations = {int(r["scene_number"]): float(r["duration_seconds"]) for r in load_json(dur_path).get("scenes", [])}
        except Exception:  # noqa: BLE001
            durations = {}
    for scene in plan.get("scenes") or []:
        n = int(scene["scene_number"])
        scenes.append(
            {
                **scene,
                "audio": (run_dir / "work" / "audio" / f"{n:03d}.mp3").is_file(),
                "image": (run_dir / "work" / "images" / f"{n:03d}.png").is_file(),
                "video": (run_dir / "work" / "video" / f"{n:03d}.mp4").is_file(),
                "duration_seconds": durations.get(n),
            }
        )
    log_path = run_dir / "work" / "log.txt"
    log_tail = ""
    if log_path.is_file():
        log_tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:])
    return {
        **meta,
        "path": str(run_dir),
        "counts": pipeline.status(run_dir),
        "plan": {k: v for k, v in plan.items() if k != "scenes"},
        "scenes": scenes,
        "final": (run_dir / "final.mp4").is_file(),
        "log_tail": log_tail,
        "running": runner.run_lock(run_dir.name).locked(),
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/api/config")
def config() -> dict[str, Any]:
    settings = Settings()
    checks: list[str] = []
    problems: list[str] = []
    try:
        checks = runner.check_environment(settings)
    except PipelineError as exc:
        problems.append(str(exc))
    return {"version": __version__, "settings": settings.public(), "voices": list_voices(settings), "checks": checks, "problems": problems}


@app.get("/api/runs")
def runs() -> list[dict[str, Any]]:
    return runner.list_runs(Settings())


@app.post("/api/runs")
def create(body: CreateRun) -> dict[str, Any]:
    overrides = {
        "STORY_PROVIDER": body.story_provider,
        "TTS_ENGINE": body.tts_engine,
        "TTS_VOICE": body.voice,
        "DURATION_GATE": body.gate,
    }
    try:
        run_dir = runner.create_run(Settings(overrides), body.topic, body.duration, body.lang, overrides)
    except PipelineError as exc:
        raise HTTPException(400, str(exc)) from exc
    stages = ["plan", "tts", "images", "render"] if body.auto else ["plan"]
    runner.start_background(run_dir, stages, extra=body.extra)
    return _run_payload(run_dir)


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return _run_payload(_run_dir(run_id))


@app.put("/api/runs/{run_id}/plan")
def save_plan(run_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    if runner.run_lock(run_dir.name).locked():
        raise HTTPException(409, "Corrida em execução; espere terminar para editar")
    try:
        current = load_json(pipeline.scene_plan_path(run_dir))
        current.update({k: v for k, v in plan.items() if k in ("title", "character_bible", "scenes", "title_overlay")})
        runner.save_plan(run_dir, current)
    except PipelineError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _run_payload(run_dir)


@app.post("/api/runs/{run_id}/run")
def run_stages(run_id: str, body: RunStages) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    bad = [s for s in body.stages if s not in runner.STAGES]
    if bad:
        raise HTTPException(400, f"Etapas desconhecidas: {bad}")
    if runner.run_lock(run_dir.name).locked():
        raise HTTPException(409, "Corrida já em execução")
    only = None
    if body.only is not None:
        only = {int(body.only)} if isinstance(body.only, int) else {int(n) for n in body.only}
    runner.start_background(run_dir, body.stages, force=body.force, music=body.music, only=only)
    return {"ok": True}


@app.post("/api/runs/{run_id}/scenes/{scene}/regen-image")
def regen(run_id: str, scene: int, body: RegenImage) -> dict[str, Any]:
    run_dir = _run_dir(run_id)
    if runner.run_lock(run_dir.name).locked():
        raise HTTPException(409, "Corrida em execução")
    try:
        runner.regen_image(run_dir, scene, body.seed)
    except (PipelineError, StopIteration) as exc:
        raise HTTPException(400, str(exc) or "Cena não encontrada") from exc
    return _run_payload(run_dir)


@app.get("/api/runs/{run_id}/file/{rel:path}")
def run_file(run_id: str, rel: str):
    run_dir = _run_dir(run_id)
    target = (run_dir / rel).resolve()
    if run_dir.resolve() not in target.parents or not target.is_file():
        raise HTTPException(404, "Arquivo não encontrado")
    return FileResponse(target)


@app.exception_handler(PipelineError)
def pipeline_error(_, exc: PipelineError) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=400)
