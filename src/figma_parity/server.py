"""HTTP surface for the parity service.

Binds 127.0.0.1 by design: this process holds an API key and runs an agent
with file-write and shell access. There is no authentication because nothing
off-machine can reach it. If you ever change the bind address, add auth first.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .config import ConfigError, settings
from .runner import RunResult, run_parity

app = FastAPI(title="figma-parity", version="0.1.0")

_DONE = object()


@dataclass
class Run:
    id: str
    figma_url: str
    project_path: Path
    status: str = "running"
    result: RunResult | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    queues: list[asyncio.Queue] = field(default_factory=list)

    async def publish(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        for q in self.queues:
            await q.put(event)

    async def close(self) -> None:
        for q in self.queues:
            await q.put(_DONE)


# ponytail: in-memory run registry. Runs do not survive a restart; swap for
# sqlite the day that actually matters.
RUNS: dict[str, Run] = {}


class RunRequest(BaseModel):
    figma_url: str = Field(..., description="Figma design URL, ideally with a node-id")
    project_path: str = Field(..., description="Directory to implement into")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "ok": True,
        "api_key_configured": bool(settings.api_key),
        "allowed_roots": [str(r) for r in settings.allowed_roots],
        "model": settings.model,
        "effort": settings.effort,
    }


@app.post("/runs")
async def create_run(req: RunRequest) -> dict[str, Any]:
    # Trust boundary. Validate before anything is started, not inside the agent.
    try:
        settings.require_api_key()
        project_path = settings.validate_project_path(req.project_path)
    except ConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if "figma.com" not in req.figma_url:
        raise HTTPException(status_code=400, detail="figma_url is not a figma.com URL")

    run = Run(id=uuid.uuid4().hex[:12], figma_url=req.figma_url, project_path=project_path)
    RUNS[run.id] = run

    async def drive() -> None:
        try:
            run.result = await run_parity(
                run.figma_url, run.project_path, on_event=run.publish
            )
            run.status = "verified" if run.result.verified else "unverified"
        except Exception as exc:  # noqa: BLE001 — reported, never swallowed
            run.status = "error"
            await run.publish({"type": "error", "text": f"{type(exc).__name__}: {exc}"})
        finally:
            await run.close()

    asyncio.create_task(drive())
    return {"run_id": run.id, "status": run.status, "project_path": str(project_path)}


@app.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="no such run")

    payload: dict[str, Any] = {
        "run_id": run.id,
        "status": run.status,
        "figma_url": run.figma_url,
        "project_path": str(run.project_path),
        "event_count": len(run.events),
    }
    if run.result:
        led = run.result.ledger
        payload["verified"] = run.result.verified
        payload["cost_usd"] = run.result.cost_usd
        payload["turns"] = run.result.turns
        payload["error"] = run.result.error
        payload["report"] = run.result.report()
        if led:
            payload["ledger"] = {
                "complete": led.complete,
                "total": led.total,
                "done": led.done,
                "todo": led.todo,
                "deviations": led.deviations,
                "blocked": led.blocked,
                "unjustified": len(led.unjustified),
                "nodes_extracted": led.nodes_extracted,
                "nodes_total": led.nodes_total,
                "coverage_complete": led.coverage_complete,
            }
    return payload


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> StreamingResponse:
    run = RUNS.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="no such run")

    async def gen():
        queue: asyncio.Queue = asyncio.Queue()
        for past in run.events:  # replay so a late subscriber sees the whole run
            await queue.put(past)
        if run.status == "running":
            run.queues.append(queue)
        else:
            await queue.put(_DONE)

        try:
            while True:
                item = await queue.get()
                if item is _DONE:
                    yield f"event: end\ndata: {json.dumps({'status': run.status})}\n\n"
                    return
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            if queue in run.queues:
                run.queues.remove(queue)

    return StreamingResponse(gen(), media_type="text/event-stream")


def main() -> None:
    import uvicorn

    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
