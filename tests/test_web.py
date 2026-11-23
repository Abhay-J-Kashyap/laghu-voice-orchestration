"""The web UI's API, with stand-in LLMs: make an agent, answer its questions, run setup, follow the progress,
read the review, approve. No Groq tokens."""
from __future__ import annotations

import asyncio
import json
import time

import pytest
from fastapi.testclient import TestClient

from laghu_voice.web.app import create_app
from laghu_voice.web.roman import romanize
from test_setup import FakeSetupLLM

DESC = "City Library calls people who asked about membership. Monthly 200, yearly 2000."


def wait_idle(client, agent_id, timeout=20.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if client.get(f"/api/agents/{agent_id}").json()["job"] is None:
            return
        time.sleep(0.05)
    raise AssertionError("the job never finished")


def sse(text: str) -> list[dict]:
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ") and line[6:] != "{}"]


@pytest.fixture
def client(tmp_path):
    llm = FakeSetupLLM()
    app = create_app(tmp_path, make_clients=lambda: (llm, None, llm), dist=tmp_path / "no-ui")
    with TestClient(app) as c:
        c.root = tmp_path
        yield c


def test_an_agent_goes_from_description_to_approval(client):
    r = client.post("/api/agents", json={"name": "City Library", "description": DESC})
    assert r.status_code == 201
    a = r.json()
    assert a["id"] == "city-library" and a["status"] == "new" and a["description"].startswith("City Library")

    assert client.post("/api/agents/city-library/questions").status_code == 202
    wait_idle(client, "city-library")
    a = client.get("/api/agents/city-library").json()
    assert a["status"] == "questions" and a["questions"] == ["How much is the yearly plan?"]

    r = client.put("/api/agents/city-library/answers",
                   json={"answers": [{"q": "How much is the yearly plan?", "a": "2000 rupees"}, {"q": " ", "a": "x"}]})
    assert r.json()["status"] == "answered" and r.json()["answers"] == [{"q": "How much is the yearly plan?",
                                                                       "a": "2000 rupees"}]

    assert client.post("/api/agents/city-library/run", json={"simulate": False}).status_code == 202
    wait_idle(client, "city-library")
    a = client.get("/api/agents/city-library").json()
    assert a["status"] == "passed" and a["result"]["ok"], a

    events = sse(client.get("/api/agents/city-library/events?follow=false").text)
    types = [e["type"] for e in events]
    assert types[0] == "job" and "finished" in types and types[-1] == "job"
    assert [e["stage"] for e in events if e["type"] == "stage"] == ["questions", "drafting", "checking", "writing"]
    assert all("tokens" in e for e in events if e["type"] != "job" or e["status"] != "queued")

    rv = client.get("/api/agents/city-library/review").json()
    assert rv["lines"] and all(ln["roman"] and ln["en"] for ln in rv["lines"])
    assert any(s["name"] == "booked" and s["outcome"] == "success" for s in rv["states"])
    assert rv["answers"][0]["a"] == "2000 rupees" and rv["calls"] == [] and "## The flow" in rv["review_md"]

    r = client.post("/api/agents/city-library/approve")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert (client.root / "agents" / "city_library.yaml").exists()
    assert "--agent-spec agents/city_library.yaml" in r.json()["run"]


def test_the_list_includes_runs_made_from_the_command_line(client):
    (client.root / "m5" / "use_cases").mkdir(parents=True)
    (client.root / "m5" / "use_cases" / "mba.md").write_text("# MBA counselling: outbound calls\n...", "utf-8")
    f = client.root / "m5" / "out" / "setup" / "mba"
    f.mkdir(parents=True)
    (f / "setup.json").write_text(json.dumps({"ok": True, "test_calls": 8, "passed": 8}), "utf-8")
    (f / "answers.json").write_text("[]", "utf-8")
    assert client.get("/api/examples").json() == [{"id": "mba", "title": "MBA counselling: outbound calls",
                                                   "description": "# MBA counselling: outbound calls\n..."}]
    got = {a["id"]: a for a in client.get("/api/agents").json()}
    assert got["mba"]["status"] == "passed" and got["mba"]["name"] == "MBA counselling: outbound calls"
    (f / "setup.json").write_text(json.dumps({"ok": False, "stopped": "DailyLimit: tokens per day"}), "utf-8")
    assert client.get("/api/agents/mba").json()["status"] == "paused"
    assert client.get("/api/agents/mba").json()["description"].startswith("# MBA")


def test_bad_requests_are_refused(client):
    assert client.get("/api/agents/nope").status_code == 404
    assert client.get("/api/agents/..%2F..%2Fetc").status_code == 404
    assert client.post("/api/agents", json={"name": "x", "description": "  "}).status_code == 400
    client.post("/api/agents", json={"name": "Gym", "description": DESC})
    assert client.post("/api/agents", json={"name": "Gym", "description": DESC}).json()["id"] == "gym-2"
    assert client.post("/api/agents/gym/approve").status_code == 400          # nothing run yet


class SlowLLM(FakeSetupLLM):
    async def complete(self, messages, **kw):
        await asyncio.sleep(0.6)
        return await super().complete(messages, **kw)


def test_one_job_at_a_time_and_no_two_for_one_agent(tmp_path):
    llm = SlowLLM()
    app = create_app(tmp_path, make_clients=lambda: (llm, None, llm), dist=tmp_path / "no-ui")
    with TestClient(app) as c:
        for n in ("a", "b"):
            c.post("/api/agents", json={"name": n, "description": DESC})
        assert c.post("/api/agents/a/questions").json()["position"] == 0
        assert c.post("/api/agents/a/questions").status_code == 409            # already has one
        assert c.post("/api/agents/b/questions").json()["position"] == 1       # waits its turn
        time.sleep(0.2)
        q = c.get("/api/queue").json()
        assert q["running"]["agent"] == "a" and [j["agent"] for j in q["waiting"]] == ["b"]
        assert c.get("/api/agents/b").json()["status"] == "queued"
        assert c.put("/api/agents/a/answers", json={"answers": []}).status_code == 409
        wait_idle(c, "a")
        wait_idle(c, "b")
        assert c.get("/api/agents/b").json()["questions"]


def test_a_failed_job_says_why_and_the_next_one_still_runs(tmp_path):
    calls = []

    def make():
        calls.append(1)
        llm = FakeSetupLLM()
        return llm, None, llm
    app = create_app(tmp_path, make_clients=make, dist=tmp_path / "no-ui")
    with TestClient(app) as c:
        c.post("/api/agents", json={"name": "a", "description": DESC})
        (tmp_path / "m5" / "out" / "setup" / "a" / "description.md").unlink()
        c.post("/api/agents/a/questions")
        wait_idle(c, "a")
        events = sse(c.get("/api/agents/a/events?follow=false").text)
        assert any(e["type"] == "stopped" and "FileNotFoundError" in e["error"] for e in events)
        c.post("/api/agents", json={"name": "b", "description": DESC})
        c.post("/api/agents/b/questions")
        wait_idle(c, "b")
        assert c.get("/api/agents/b").json()["questions"] and len(calls) == 1      # clients made once


def test_the_built_page_is_served_with_its_own_routes(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>ui</html>", "utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", "utf-8")
    with TestClient(create_app(tmp_path, make_clients=lambda: (None, None, None), dist=dist)) as c:
        assert c.get("/").text == "<html>ui</html>" and c.get("/build/mba").text == "<html>ui</html>"
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert c.get("/api/nothing").status_code == 404
        assert c.get("/api/health").json()["ok"]


def test_hindi_in_latin_letters():
    assert romanize("मेरा नाम अभय है") == "mera naam abhay hai"
    assert romanize("धन्यवाद, समझना") == "dhanyavaad, samajhna"
    assert romanize("हाँ परसों शाम को") == "haan parson shaam ko"
    assert romanize("ज़रूर") == "zaroor" and romanize("OK 15") == "OK 15" and romanize("") == ""


def test_progress_streams_live_until_the_job_ends(tmp_path):
    llm = SlowLLM()
    app = create_app(tmp_path, make_clients=lambda: (llm, None, llm), dist=tmp_path / "no-ui")
    with TestClient(app) as c:
        c.post("/api/agents", json={"name": "a", "description": DESC})
        c.post("/api/agents/a/questions")
        with c.stream("GET", "/api/agents/a/events") as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            text = "".join(r.iter_text())
        got = sse(text)
        assert [e["type"] for e in got][-3:] == ["questions", "finished", "job"] and text.rstrip().endswith("{}")
        assert "id: 1" in text and "event: end" in text
        tail = sse(c.get("/api/agents/a/events?follow=false&since=3").text)    # a reconnect gets only the rest
        assert len(tail) == len(got) - 3
