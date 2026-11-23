"""Agents on disk, for the web UI. The setup tool's output folders are the source of truth, so the command line
and the UI always show the same thing:

    m5/out/setup/<id>/description.md    the use case (made in the UI); runs from the command line read
                                        m5/use_cases/<id>.md instead
    m5/out/setup/<id>/questions.json    the questions the setup model asked, before they are answered
    m5/out/setup/<id>/answers.json      the owner's answers (what run_setup reads)
    m5/out/setup/<id>/events.jsonl      the progress of the last job, one event per line
    ... and everything run_setup writes (draft.json, spec.yaml, test_calls.jsonl, review.md, setup.json).
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")


class NotFound(KeyError):
    pass


class Store:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.setup_dir = self.root / "m5" / "out" / "setup"
        self.use_cases = self.root / "m5" / "use_cases"
        self.agents_dir = self.root / "agents"

    # ------------------------------------------------------------------ where things are
    def folder(self, agent_id: str) -> Path:
        if not ID_RE.match(agent_id or ""):
            raise NotFound(agent_id)
        f = self.setup_dir / agent_id
        if not f.is_dir():
            raise NotFound(agent_id)
        return f

    def description_path(self, agent_id: str) -> Path:
        own = self.folder(agent_id) / "description.md"
        if own.exists():
            return own
        cli = self.use_cases / f"{agent_id}.md"
        return cli if cli.exists() else own

    def ids(self) -> list[str]:
        if not self.setup_dir.is_dir():
            return []
        return sorted(p.name for p in self.setup_dir.iterdir() if p.is_dir() and ID_RE.match(p.name))

    # ------------------------------------------------------------------ making one
    def slug(self, name: str) -> str:
        base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40] or "agent"
        if not base[0].isalnum():
            base = "a" + base
        taken = set(self.ids())
        out, n = base, 2
        while out in taken:
            out, n = f"{base}-{n}", n + 1
        return out

    def create(self, name: str, description: str) -> str:
        if not description.strip():
            raise ValueError("the description is empty")
        agent_id = self.slug(name or description.split("\n", 1)[0])
        f = self.setup_dir / agent_id
        f.mkdir(parents=True)
        (f / "description.md").write_text(description.strip() + "\n", encoding="utf-8")
        self._write(f / "web.json", {"name": name.strip() or agent_id,
                                     "created": datetime.now().isoformat(timespec="seconds")})
        return agent_id

    def set_description(self, agent_id: str, description: str) -> None:
        if not description.strip():
            raise ValueError("the description is empty")
        (self.folder(agent_id) / "description.md").write_text(description.strip() + "\n", encoding="utf-8")

    def set_answers(self, agent_id: str, answers: list[dict]) -> None:
        clean = [{"q": str(a.get("q", "")).strip(), "a": str(a.get("a", "")).strip()} for a in answers
                 if str(a.get("q", "")).strip()]
        self._write(self.folder(agent_id) / "answers.json", clean)

    def set_questions(self, agent_id: str, questions: list[str]) -> None:
        self._write(self.folder(agent_id) / "questions.json", [str(q) for q in questions])

    # ------------------------------------------------------------------ reading
    def read(self, agent_id: str, name: str, default=None):
        f = self.folder(agent_id) / name
        if not f.exists():
            return default
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def rows(self, agent_id: str, name: str) -> list[dict]:
        f = self.folder(agent_id) / name
        if not f.exists():
            return []
        out = []
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    pass                  # a line half-written while the run goes on
        return out

    def summary(self, agent_id: str, job: dict | None = None) -> dict:
        f = self.folder(agent_id)
        meta = self.read(agent_id, "web.json", {}) or {}
        res = self.read(agent_id, "setup.json")
        draft = self.read(agent_id, "draft.json") or {}
        agent = (draft.get("raw") or {}).get("agent") or {}
        desc = self.description_path(agent_id)
        title = meta.get("name") or agent.get("company_en") or agent.get("company") or agent_id
        if desc.exists() and not meta.get("name"):
            first = desc.read_text(encoding="utf-8").strip().split("\n", 1)[0].lstrip("# ").strip()
            title = first or title
        times = [p.stat().st_mtime for p in f.iterdir() if p.is_file()]
        return {
            "id": agent_id, "name": title, "company": agent.get("company_en") or agent.get("company") or "",
            "status": self.status(agent_id, job), "job": job,
            "updated": datetime.fromtimestamp(max(times)).astimezone().isoformat(timespec="seconds") if times else None,
            "test_calls": res.get("test_calls") if res else None, "passed": res.get("passed") if res else None,
            "approved": (res or {}).get("approved"),
        }

    def status(self, agent_id: str, job: dict | None = None) -> str:
        """new -> questions -> answered -> (running) -> passed | needs_work | paused | stopped -> approved."""
        if job:
            return {"questions": "asking", "setup": "running"}.get(job["kind"], "running") \
                if job["state"] == "running" else "queued"
        res = self.read(agent_id, "setup.json")
        if res:
            if res.get("approved"):
                return "approved"
            if res.get("stopped"):
                return "paused" if "DailyLimit" in res["stopped"] else "stopped"
            all_passed = not res.get("test_calls") or res.get("passed") == res.get("test_calls")
            return "passed" if res.get("ok") and all_passed else "needs_work"
        if (self.folder(agent_id) / "answers.json").exists():
            return "answered"
        if (self.folder(agent_id) / "questions.json").exists():
            return "questions"
        return "new"

    def questions(self, agent_id: str) -> list[str]:
        qs = self.read(agent_id, "questions.json")
        if qs is not None:
            return qs
        return [a["q"] for a in self.read(agent_id, "answers.json", []) or []]

    @staticmethod
    def _write(path: Path, value) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)
