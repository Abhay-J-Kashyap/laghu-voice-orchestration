"""A small in-memory stand-in for the onboarding backend's tool API, for tests that must run without it.

It keeps the parts of the real service's contract the agent depends on: the response envelope, the outcome
names, the state machine (out-of-order calls are refused with 409), identity attempts (2), passcode attempts
(3), idempotency replays, and an audit view. The credit policy is a toy. The real service is what Milestone
4's evaluation runs against (m4/run_dialog_eval.py).
"""
from __future__ import annotations

import json
import uuid

import httpx

CUSTOMERS = {
    "ABCDE1234F": {"name": "rajesh kumar", "dob": "1988-04-12", "phone": "0001", "income": 95_000, "score": 760},
    "CDEFG3456H": {"name": "imran qureshi", "dob": "1991-07-21", "phone": "0003", "income": 60_000, "score": 590},
    "EFGHI5678J": {"name": "vikram anand", "dob": "1979-09-15", "phone": "0005", "income": 150_000, "score": 800,
                   "sanctioned": True},
}
OTP = "482913"
TERMINAL = {"completed", "escalated", "blocked", "lead_captured"}


class FakeBackend:
    def __init__(self):
        self.sessions: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/healthz":
            return httpx.Response(200, json={"status": "ok"})
        if request.method == "GET" and path.startswith("/v1/sessions/"):
            s = self.sessions[path.rsplit("/", 1)[1]]
            return httpx.Response(200, json={"session_id": s["id"], "state": s["state"],
                                             "tool_calls": [{"tool_name": t} for t in s["tools"]],
                                             "consents": [{"granted": g} for g in s["consents"]],
                                             "eligibility": s.get("eligibility"), "escalation": s.get("escalation")})
        body = json.loads(request.content or b"{}")
        if path == "/v1/sessions":
            sid = uuid.uuid4().hex
            self.sessions[sid] = {"id": sid, "state": "started", "tools": [], "consents": [], "attempts": 0,
                                  "otp_tries": 0, "replays": {}}
            return httpx.Response(200, json={"session_id": sid, "state": "started", "agent_message": "hi"})
        tool = path.rsplit("/", 1)[1]
        s = self.sessions[body["session_id"]]
        self.calls.append((tool, body))
        key = body.get("idempotency_key")
        if key and (tool, key) in s["replays"]:
            return httpx.Response(200, json=s["replays"][(tool, key)])
        status, out = getattr(self, tool)(s, body)
        out.setdefault("data", {})
        out["session_state"] = s["state"]
        out.setdefault("agent_message", "...")
        if status == 200:
            s["tools"].append(tool)
            if key:
                s["replays"][(tool, key)] = out
        return httpx.Response(status, json=out)

    @staticmethod
    def _need(s, *states):
        if s["state"] in TERMINAL:
            return 409, {"outcome": "rejected", "data": {"code": "session_closed"}}
        if states and s["state"] not in states:
            return 409, {"outcome": "rejected", "data": {"code": "invalid_transition"}}
        return None

    def verify_identity(self, s, b):
        if (e := self._need(s, "started")):
            return e
        c = CUSTOMERS.get(b["pan"].replace(" ", "").upper())
        if c is None:
            s["state"] = "prospect"
            return 200, {"outcome": "not_registered", "data": {"registered": False}}
        if c.get("sanctioned"):
            return 200, {"outcome": "blocked", "data": {"retries_remaining": 0}}
        name_ok = set(b["full_name"].lower().split()) & set(c["name"].split())
        if b["date_of_birth"] == c["dob"] and name_ok:
            s["state"] = "identity_matched"
            s["customer"] = c
            return 200, {"outcome": "otp_sent", "data": {"phone_last4": c["phone"], "demo_otp": OTP}}
        s["attempts"] += 1
        if s["attempts"] >= 2:
            return 200, {"outcome": "blocked", "data": {"retries_remaining": 0}}
        return 200, {"outcome": "retry", "data": {"retries_remaining": 2 - s["attempts"]}}

    def verify_otp(self, s, b):
        if (e := self._need(s, "identity_matched")):
            return e
        if b["code"] == OTP:
            s["state"] = "identity_verified"
            return 200, {"outcome": "ok", "data": {"verified": True}}
        s["otp_tries"] += 1
        if s["otp_tries"] >= 3:
            return 200, {"outcome": "blocked", "data": {"reason": "attempts_exhausted"}}
        return 200, {"outcome": "retry", "data": {"attempts_remaining": 3 - s["otp_tries"]}}

    def resend_otp(self, s, b):
        if (e := self._need(s, "identity_matched")):
            return e
        return 200, {"outcome": "otp_sent", "data": {"phone_last4": s["customer"]["phone"], "demo_otp": OTP}}

    def check_eligibility(self, s, b):
        if (e := self._need(s, "identity_verified")):
            return e
        c = s["customer"]
        s["state"] = "eligibility_assessed"
        if c["score"] < 650:
            d = {"decision": "declined", "approved_amount": 0, "interest_rate": 0.0, "monthly_instalment": 0}
            s["eligibility"] = d
            return 200, {"outcome": "declined", "data": d}
        amount = min(b["requested_amount"], c["income"] * 4)
        d = {"decision": "approved", "approved_amount": amount, "interest_rate": 12.5,
             "monthly_instalment": round(amount / b["tenure_months"] * 1.07)}
        s["eligibility"] = d
        return 200, {"outcome": "ok", "data": d}

    def record_consent(self, s, b):
        if (e := self._need(s, "eligibility_assessed")):
            return e
        s["consents"].append(b["granted"])
        if b["granted"]:
            s["state"] = "completed"
            return 200, {"outcome": "ok", "data": {"granted": True}}
        return 200, {"outcome": "declined", "data": {"granted": False}}

    def escalate(self, s, b):
        if (e := self._need(s)):
            return e
        s["state"] = "escalated"
        queue = {"customer_disputes_decision": "underwriting", "identity_verification_failed": "kyc_review"}.get(
            b["reason_code"], "general_support")
        s["escalation"] = {"queue": queue, "ticket_ref": "ESC-1"}
        return 200, {"outcome": "ok", "data": {"ticket_ref": "ESC-1", "queue": queue}}

    def capture_lead(self, s, b):
        if (e := self._need(s, "prospect")):
            return e
        s["state"] = "lead_captured"
        return 200, {"outcome": "ok", "data": {"lead_reference": "LEAD-1", "link_emailed": True}}
