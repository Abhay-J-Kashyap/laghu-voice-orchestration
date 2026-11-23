"""Setup jobs for the web UI, one at a time: Groq's free tier allows one model 8,000 tokens a minute, so two runs at
once would only slow each other down and hit the limits sooner. A second request waits in the queue.

Jobs run on one worker thread with its own event loop; the LLM clients are made there once and kept, so their
token counts (and the per-minute pacing) carry over from job to job. Every event goes to the agent's
events.jsonl as it happens; the web page reads that file, so a reload or a server restart loses nothing.
"""
from __future__ import annotations

import asyncio
import json
import queue
import threading
import time
from pathlib import Path

from .roman import romanize
from .store import Store

FINAL = ("finished", "stopped")


class Busy(RuntimeError):
    pass


class Jobs:
    def __init__(self, store: Store, make_clients):
        """make_clients() -> (setup_llm, agent_llm, caller_llm), called on the worker thread at the first job."""
        self.store = store
        self.make_clients = make_clients
        self.clients = None
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()          # the queue's state
        self.file_lock = threading.Lock()     # events.jsonl: the request thread and the worker both write
        self.current: dict | None = None
        self.waiting: list[dict] = []
        self.thread = threading.Thread(target=self._worker, name="setup-jobs", daemon=True)
        self.thread.start()

    # ------------------------------------------------------------------ asking
    def submit(self, agent_id: str, kind: str, **opts) -> dict:
        self.store.folder(agent_id)                  # NotFound for an unknown agent
        with self.lock:
            if self.job_for(agent_id):
                raise Busy(f"{agent_id} already has a job running or waiting")
            job = {"agent": agent_id, "kind": kind, "opts": opts, "state": "queued",
                   "queued_at": time.time(), "position": len(self.waiting) + (1 if self.current else 0)}
            self.waiting.append(job)
        self._log(agent_id, {"type": "job", "status": "queued", "job": kind, "position": job["position"]},
                  fresh=True)
        self.q.put(job)
        return self.public(job)

    def job_for(self, agent_id: str) -> dict | None:
        if self.current and self.current["agent"] == agent_id:
            return self.public(self.current)
        for j in self.waiting:
            if j["agent"] == agent_id:
                return self.public(j)
        return None

    def state(self) -> dict:
        with self.lock:
            return {"running": self.public(self.current) if self.current else None,
                    "waiting": [self.public(j) for j in self.waiting], "tokens": self.tokens()}

    @staticmethod
    def public(job: dict) -> dict:
        return {k: job[k] for k in ("agent", "kind", "state", "position") if k in job}

    def tokens(self) -> dict:
        if not self.clients:
            return {}
        setup, agent, caller = self.clients
        out = {"setup": getattr(setup, "used_total", 0), "agent": getattr(agent, "used_total", 0)}
        if caller is not setup:
            out["caller"] = getattr(caller, "used_total", 0)
        return out

    def models(self) -> dict:
        if not self.clients:
            return {}
        names = ("setup", "agent", "caller")
        return {n: getattr(getattr(c, "llm", c), "model", "") for n, c in zip(names, self.clients)}

    # ------------------------------------------------------------------ the worker
    def _worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        while True:
            job = self.q.get()
            if job is None:
                break
            with self.lock:
                self.waiting = [j for j in self.waiting if j is not job]
                job["state"] = "running"
                job["position"] = 0
                self.current = job
                for i, j in enumerate(self.waiting):
                    j["position"] = i + 1
            try:
                loop.run_until_complete(self._run(job))
            except Exception as e:                    # noqa: BLE001 - one job's failure never stops the worker
                self._log(job["agent"], {"type": "stopped", "error": f"{type(e).__name__}: {str(e)[:300]}",
                                         "daily_limit": type(e).__name__ == "DailyLimit"})
            finally:
                self._log(job["agent"], {"type": "job", "status": "done", "job": job["kind"]})
                with self.lock:
                    self.current = None
        loop.close()

    async def _run(self, job: dict) -> None:
        agent_id = job["agent"]
        self._log(agent_id, {"type": "job", "status": "started", "job": job["kind"]})
        if self.clients is None:
            self.clients = self.make_clients()
        setup, agent, caller = self.clients
        if job["kind"] == "questions":
            from ..setup.tool import Drafter
            desc = self.store.description_path(agent_id).read_text(encoding="utf-8")
            qs = await Drafter(setup, desc, []).questions()
            self.store.set_questions(agent_id, qs)
            self._log(agent_id, {"type": "questions", "questions": qs})
            self._log(agent_id, {"type": "finished", "result": {"questions": len(qs)}})
            return
        if job["kind"] == "setup":
            from ..setup.tool import run_setup
            folder = self.store.folder(agent_id)
            answers = folder / "answers.json"
            if not answers.exists():
                self.store.set_answers(agent_id, [])

            def on_event(e: dict) -> None:
                if e.get("why"):                 # reasons quote the caller's Hindi: in Latin letters for the page
                    e = {**e, "why": [romanize(w) for w in e["why"]]}
                self._log(agent_id, e)
            await run_setup(self.store.description_path(agent_id), folder, setup, agent, answers_path=answers,
                            simulate=job["opts"].get("simulate", True), caller_llm=caller,
                            events=on_event, ask=_no_terminal)
            return
        raise ValueError(f"unknown job {job['kind']!r}")

    def _log(self, agent_id: str, event: dict, fresh: bool = False) -> None:
        """Append one event; fresh starts the file again (a new job). Every event carries the token counts."""
        event = {"at": round(time.time(), 2), **event}
        tok = self.tokens()
        if tok:
            event["tokens"] = tok
        try:
            f = self.store.folder(agent_id) / "events.jsonl"
        except KeyError:
            return
        with self.file_lock:
            with f.open("w" if fresh else "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")

    def close(self) -> None:
        self.q.put(None)


def _no_terminal(prompt: str) -> str:
    raise RuntimeError("the web UI answers questions before a run; there is no terminal to ask in")


def events_from(path: Path, start: int) -> tuple[list[dict], int]:
    """Events from line `start` on, and the next line number. A half-written last line waits for the next read."""
    if not path.exists():
        return [], 0
    lines = path.read_text(encoding="utf-8").split("\n")
    done = lines[:-1]                     # the last piece has no newline yet (or is empty)
    if start > len(done):
        start = 0                         # the file started again (a new job): from the top
    out = []
    for line in done[start:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append({"type": "log", "text": "(an unreadable event)"})
    return out, len(done)
