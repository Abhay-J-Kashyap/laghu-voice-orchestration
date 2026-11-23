"""The web UI's API (FastAPI): make an agent from a description, answer its questions, run setup with live
progress, read the review, approve. The built UI (web/dist) is served from the same server.

    python -m laghu_voice.web                   # http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from .jobs import FINAL, Busy, Jobs, events_from
from .roman import romanize
from .store import NotFound, Store

ROOT = Path(__file__).resolve().parents[2]


class NewAgent(BaseModel):
    name: str = ""
    description: str


class Description(BaseModel):
    description: str


class Answers(BaseModel):
    answers: list[dict]


class RunOptions(BaseModel):
    simulate: bool = True


def create_app(root: Path = ROOT, make_clients=None, dist: Path | None = None) -> FastAPI:
    store = Store(root)
    if make_clients is None:
        def make_clients():
            from ..setup.tool import build_clients
            return build_clients()
    jobs = Jobs(store, make_clients)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        jobs.close()
    app = FastAPI(title="laghu-voice setup", lifespan=lifespan)
    app.state.store, app.state.jobs = store, jobs

    def folder_or_404(agent_id: str) -> Path:
        try:
            return store.folder(agent_id)
        except NotFound:
            raise HTTPException(404, f"no agent {agent_id!r}") from None

    def detail(agent_id: str) -> dict:
        folder_or_404(agent_id)
        desc = store.description_path(agent_id)
        return {**store.summary(agent_id, jobs.job_for(agent_id)),
                "description": desc.read_text(encoding="utf-8") if desc.exists() else "",
                "questions": store.questions(agent_id), "answers": store.read(agent_id, "answers.json"),
                "result": store.read(agent_id, "setup.json")}

    # ------------------------------------------------------------------ agents
    @app.get("/api/health")
    def health():
        return {"ok": True, "queue": jobs.state(), "models": jobs.models()}

    @app.get("/api/examples")
    def examples():
        """The use cases in m5/use_cases, as starting points for a new description."""
        out = []
        for f in sorted(store.use_cases.glob("*.md")) if store.use_cases.is_dir() else []:
            text = f.read_text(encoding="utf-8")
            title = text.strip().split("\n", 1)[0].lstrip("# ").strip() or f.stem
            out.append({"id": f.stem, "title": title, "description": text})
        return out

    @app.get("/api/agents")
    def list_agents():
        return [store.summary(i, jobs.job_for(i)) for i in store.ids()]

    @app.post("/api/agents", status_code=201)
    def new_agent(body: NewAgent):
        try:
            agent_id = store.create(body.name, body.description)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return detail(agent_id)

    @app.get("/api/agents/{agent_id}")
    def get_agent(agent_id: str):
        return detail(agent_id)

    @app.put("/api/agents/{agent_id}/description")
    def put_description(agent_id: str, body: Description):
        folder_or_404(agent_id)
        _not_busy(jobs, agent_id)
        try:
            store.set_description(agent_id, body.description)
        except ValueError as e:
            raise HTTPException(400, str(e)) from None
        return detail(agent_id)

    @app.put("/api/agents/{agent_id}/answers")
    def put_answers(agent_id: str, body: Answers):
        folder_or_404(agent_id)
        _not_busy(jobs, agent_id)
        store.set_answers(agent_id, body.answers)
        return detail(agent_id)

    # ------------------------------------------------------------------ jobs
    @app.post("/api/agents/{agent_id}/questions", status_code=202)
    def ask_questions(agent_id: str):
        folder_or_404(agent_id)
        return _submit(jobs, agent_id, "questions")

    @app.post("/api/agents/{agent_id}/run", status_code=202)
    def run(agent_id: str, body: RunOptions | None = None):
        folder_or_404(agent_id)
        if not store.description_path(agent_id).exists():
            raise HTTPException(400, "this agent has no description")
        return _submit(jobs, agent_id, "setup", simulate=(body or RunOptions()).simulate)

    @app.get("/api/queue")
    def queue_state():
        return jobs.state()

    @app.get("/api/agents/{agent_id}/events")
    async def events(agent_id: str, since: int = 0, follow: bool = True):
        """Server-sent events: the last job's events from line `since`, then new ones as they come, until the job
        ends. follow=false returns what there is and stops."""
        f = folder_or_404(agent_id) / "events.jsonl"

        async def stream():
            n, idle = since, 0.0
            while True:
                got, n2 = events_from(f, n)
                if n2 < n:
                    yield "event: reset\ndata: {}\n\n"
                n = n2
                for i, e in enumerate(got):
                    yield f"id: {n - len(got) + i + 1}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                running = jobs.job_for(agent_id)
                if not follow or (not running and not got):
                    yield "event: end\ndata: {}\n\n"
                    return
                if got:
                    idle = 0.0
                elif (idle := idle + 0.4) >= 15:
                    idle = 0.0
                    yield ": still here\n\n"
                await asyncio.sleep(0.4)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ results
    @app.get("/api/agents/{agent_id}/review")
    def get_review(agent_id: str):
        folder_or_404(agent_id)
        return review_data(store, agent_id)

    @app.post("/api/agents/{agent_id}/approve")
    def approve_agent(agent_id: str):
        folder = folder_or_404(agent_id)
        _not_busy(jobs, agent_id)
        if not (folder / "setup.json").exists():
            raise HTTPException(400, "run setup first")
        from ..setup.tool import approve
        store.agents_dir.mkdir(parents=True, exist_ok=True)
        try:
            dest = approve(folder, store.agents_dir)
        except SystemExit as e:
            raise HTTPException(400, str(e)) from None
        return {**detail(agent_id), "installed": str(dest.relative_to(store.root)),
                "run": f"python -m laghu_voice.server --tts laghu --dialog agent --agent-spec "
                       f"{dest.relative_to(store.root).as_posix()}"}

    # ------------------------------------------------------------------ the built UI
    dist = dist or root / "web" / "dist"
    if dist.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        def ui(path: str):
            if path.startswith("api/"):
                return JSONResponse({"detail": "not found"}, status_code=404)
            f = (dist / path).resolve()
            if path and f.is_file() and dist.resolve() in f.parents:
                return FileResponse(f)
            return FileResponse(dist / "index.html")         # the page's own routes (/build/mba)

    return app


def _submit(jobs: Jobs, agent_id: str, kind: str, **opts) -> dict:
    try:
        return jobs.submit(agent_id, kind, **opts)
    except Busy as e:
        raise HTTPException(409, str(e)) from None


def _not_busy(jobs: Jobs, agent_id: str) -> None:
    if jobs.job_for(agent_id):
        raise HTTPException(409, "a job is running for this agent; wait for it to finish")


# ---------------------------------------------------------------------------------------------- the review
def review_data(store: Store, agent_id: str) -> dict:
    """Everything the review screen shows, with every Hindi text also in Latin letters."""
    draft = store.read(agent_id, "draft.json") or {}
    raw = draft.get("raw") or {}
    en = store.read(agent_id, "en.json") or draft.get("en") or {}
    folder = store.folder(agent_id)
    spec = None
    if (folder / "spec.yaml").exists():
        try:
            from ..dialog.spec import load_spec
            spec = load_spec(folder / "spec.yaml", generated=True)
        except Exception:                          # noqa: BLE001 - a spec with errors still has a review
            spec = None
    if (folder / "spec.yaml").exists():
        raw = _raw_of(folder / "spec.yaml", raw)
    lines = []
    for k, v in (raw.get("lines") or {}).items():
        text = v if isinstance(v, str) else v.get("example", "")
        lines.append({"key": k, "kind": "fixed" if isinstance(v, str) else "llm", "text": text,
                      "roman": romanize(text), "en": en.get(k, ""),
                      "goal": None if isinstance(v, str) else v.get("llm")})
    states = []
    tools = raw.get("tools") or {}
    for name, st in (raw.get("states") or {}).items():
        states.append({"name": name, "say": st.get("say"), "expect": st.get("expect"), "tool": st.get("tool"),
                       "commits": bool(st.get("tool") and (tools.get(st["tool"]) or {}).get("commits")),
                       "on": st.get("on") or {}, "next": st.get("next"), "end": st.get("end"),
                       "outcome": st.get("outcome")})
    slots = [{"name": k, "type": s.get("type"), "describe": s.get("describe", ""),
              "options": list((s.get("options") or {}).keys())} for k, s in (raw.get("slots") or {}).items()]
    calls = []
    for row in store.rows(agent_id, "test_calls.jsonl"):
        diag = row.get("diagnosis")
        if diag is None and spec is not None:
            try:
                from ..setup.simulate import diagnose
                diag = diagnose(spec, row)
            except Exception:                      # noqa: BLE001 - an old record the diagnosis can't read
                diag = None
        v = row.get("verdict") or {}
        p = row.get("persona") or {}
        calls.append({
            "id": p.get("id"), "kind": p.get("kind"), "name": p.get("name"), "round": row.get("round", row.get("run")),
            "expected": p.get("expected"), "outcome": row.get("outcome"), "end": row.get("end"),
            "ok": bool(v.get("success")) and not v.get("safety"), "facts": v.get("facts") or {},
            "persona_facts": p.get("facts") or {}, "safety": v.get("safety") or [], "error": row.get("error"),
            "cause": (diag or {}).get("cause"), "why": [romanize(w) for w in (diag or {}).get("why") or []],
            "seconds": row.get("seconds"),
            "transcript": [{"who": w, "text": t, "roman": romanize(t), "cut": h} for w, t, h in
                           row.get("transcript") or []],
        })
    review = folder / "review.md"
    agent = raw.get("agent") or {}
    return {
        "id": agent_id, "result": store.read(agent_id, "setup.json"),
        "agent": {k: agent.get(k) for k in ("name", "company", "company_en", "persona", "gender") if agent.get(k)},
        "knowledge": raw.get("knowledge") or {}, "slots": slots, "states": states, "lines": lines,
        "answers": store.read(agent_id, "answers.json") or [], "calls": calls,
        "warnings": (store.read(agent_id, "setup.json") or {}).get("warnings") or [],
        "review_md": review.read_text(encoding="utf-8") if review.exists() else "",
    }


def _raw_of(path: Path, raw: dict) -> dict:
    """spec.yaml is what the test calls ran and what approve installs; the draft is older when a repair changed it."""
    import yaml
    try:
        got = yaml.safe_load(path.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) and got.get("states") else raw
    except Exception:                              # noqa: BLE001 - fall back to the draft
        return raw
