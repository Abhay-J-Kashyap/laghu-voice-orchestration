"""Milestone 2's stand-in for the dialog: say back what the caller said, so the whole loop can be heard.

Milestone 4 replaces this with the agent spec and state machine. The agent never says नमस्ते (Laghu
mispronounces it, Milestone 0 Amendment 4).
"""
from __future__ import annotations

from ..orchestrator.listener import UserTurn

NOT_HEARD = "माफ़ कीजिए, मैं आपकी बात सुन नहीं पाया। क्या आप दोहरा सकते हैं?"


def echo_reply(turn: UserTurn) -> str:
    return f"मैंने सुना: {turn.text}" if turn.text.strip() else NOT_HEARD
