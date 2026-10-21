"""FastAPI app – streaming endpoint, Stop / Finish now controls, replay, and static files."""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import MAX_UPLOAD_MB, RUNS_DIR
from app.events import EventBus
from app.flow import RUN_REGISTRY, run_flow_async
from app.tools.documents import parse_document

app = FastAPI(title="ScholarSwarm", version="2.0.0")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@app.get("/health")
def health() -> dict:
    return {"ok": True, "version": "2.0.0"}


@app.post("/api/run/{run_id}/finish")
def finish_run(run_id: str) -> dict:
    """Signal a running pipeline to finish verification and proceed to ranking immediately."""
    entry = RUN_REGISTRY.get(run_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Run not found or already finished")
    entry["finish_event"].set()
    return {"ok": True, "message": f"Run {run_id} signaled to finish verification now"}


@app.post("/api/run/{run_id}/stop")
def stop_run(run_id: str) -> dict:
    """Abort a running pipeline."""
    entry = RUN_REGISTRY.get(run_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Run not found or already finished")
    entry["abort_event"].set()
    return {"ok": True, "message": f"Run {run_id} cancelled"}


@app.get("/api/replay/{run_id}")
async def replay_run(run_id: str, speed: float = Query(2.0, ge=0.5, le=10.0)) -> StreamingResponse:
    """Replay a recorded run with original relative timing."""
    run_file = RUNS_DIR / f"{run_id}.json"
    if not run_file.exists():
        raise HTTPException(status_code=404, detail="Run not found")

    payload = json.loads(run_file.read_text(encoding="utf-8"))
    events = payload.get("events", [])

    async def _stream():
        prev_dt = None
        for evt in events:
            # Parse timestamp to calculate delay
            ts_str = evt.get("ts")
            if ts_str and prev_dt:
                try:
                    curr_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    diff = (curr_dt - prev_dt).total_seconds()
                    delay = max(0.01, min(diff / speed, 2.0))
                    await asyncio.sleep(delay)
                    prev_dt = curr_dt
                except Exception:
                    await asyncio.sleep(0.05)
            elif ts_str:
                try:
                    prev_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    pass

            yield json.dumps(evt) + "\n"

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@app.post("/api/run")
async def api_run(
    request: Request,
    name: str = Form(""),
    target_level: str = Form(""),
    target_fields: str = Form(""),
    target_countries: str = Form(""),
    citizenship: str = Form("International"),
    residency_status: str = Form("Non-Resident"),
    funding_need: str = Form("full"),
    github_url: str = Form(""),
    linkedin_url: str = Form(""),
    portfolio_url: str = Form(""),
    extra_links: str = Form(""),
    resume_text: str = Form(""),
    marksheet_text: str = Form(""),
    chaos: bool = Form(False),
    resume: UploadFile | None = File(None),
    marksheet: UploadFile | None = File(None),
) -> StreamingResponse:
    """Run the streaming v2 pipeline, outputting events as NDJSON."""

    r_text = resume_text
    m_text = marksheet_text

    if resume and resume.filename:
        content = await resume.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            return JSONResponse({"error": "Resume exceeds maximum size"}, status_code=400)  # type: ignore[return-value]
        try:
            r_text = parse_document(content, resume.filename)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)  # type: ignore[return-value]

    if marksheet and marksheet.filename:
        content = await marksheet.read()
        if len(content) > MAX_UPLOAD_MB * 1024 * 1024:
            return JSONResponse({"error": "Marksheet exceeds maximum size"}, status_code=400)  # type: ignore[return-value]
        try:
            m_text = parse_document(content, marksheet.filename)
        except ValueError as e:
            return JSONResponse({"error": str(e)}, status_code=400)  # type: ignore[return-value]

    form_fields = {
        "name": name,
        "target_level": target_level,
        "target_fields": [f.strip() for f in target_fields.split(",") if f.strip()],
        "target_countries": [c.strip() for c in target_countries.split(",") if c.strip()],
        "citizenship": citizenship.strip() or "International",
        "residency_status": residency_status.strip() or "Non-Resident",
        "funding_need": funding_need,
    }
    links = [link.strip() for link in extra_links.replace(",", "\n").split("\n") if link.strip()]
    if linkedin_url and linkedin_url.strip():
        links.append(linkedin_url.strip())
    if portfolio_url and portfolio_url.strip():
        links.append(portfolio_url.strip())

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"_{str(uuid.uuid4())[:6]}"
    bus = EventBus(run_id=run_id)

    # Launch pipeline task in the asyncio event loop
    pipeline_task = asyncio.create_task(
        run_flow_async(
            resume_text=r_text,
            marksheet_text=m_text,
            github_url=github_url,
            extra_links=links,
            form_fields=form_fields,
            bus=bus,
            chaos=chaos,
            run_id=run_id,
        )
    )

    async def _stream():
        try:
            async for event in bus.stream():
                if await request.is_disconnected():
                    # Handle client disconnect / Stop
                    entry = RUN_REGISTRY.get(run_id)
                    if entry:
                        entry["abort_event"].set()
                    pipeline_task.cancel()
                    break

                line = event.model_dump_json()
                yield line + "\n"
        finally:
            if run_id in RUN_REGISTRY:
                del RUN_REGISTRY[run_id]

    return StreamingResponse(_stream(), media_type="application/x-ndjson")


@app.post("/api/chat")
async def api_chat(payload: dict) -> dict:
    """Conversational Chatbot Endpoint – converse with the Swarm Supervisor Agent."""
    from app.llm_gate import default_gate
    from app.tasks import chatbot_assistant_prompt

    user_msg = payload.get("message", "").strip()
    run_id = payload.get("run_id", "")

    if not user_msg:
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    profile = None
    ranked = []
    verified = []
    swarm_status = "idle"

    # Try to read active state from in-memory pipeline registry
    if run_id and run_id in RUN_REGISTRY:
        pipeline = RUN_REGISTRY[run_id].get("pipeline")
        if pipeline:
            profile = pipeline.profile
            ranked = pipeline.ranked
            verified = pipeline.verified_items
            swarm_status = "running"
    elif run_id:
        # Try to read from saved run JSON
        run_file = RUNS_DIR / f"{run_id}.json"
        if run_file.exists():
            try:
                run_data = json.loads(run_file.read_text(encoding="utf-8"))
                res_data = run_data.get("result", {})
                from app.models import RankedOpportunity, StudentProfile, VerifiedOpportunity
                if "profile" in res_data:
                    profile = StudentProfile.model_validate(res_data["profile"])
                ranked = [RankedOpportunity.model_validate(r) for r in res_data.get("ranked", [])]
                verified = [VerifiedOpportunity.model_validate(v) for v in res_data.get("all_checked", [])]
                swarm_status = "completed"
            except Exception:
                pass

    prompt = chatbot_assistant_prompt(
        user_query=user_msg,
        profile=profile,
        ranked=ranked,
        verified=verified,
        swarm_status=swarm_status,
    )

    reply = await default_gate.complete(
        messages=[{"role": "user", "content": prompt}],
        tier="fast",
        temperature=0.3,
        max_tokens=1000,
        agent_name="Supervisor",
    )

    return {
        "reply": reply,
        "swarm_status": swarm_status,
        "opportunities_count": len(verified),
        "timestamp": datetime.now(UTC).isoformat(),
    }


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

