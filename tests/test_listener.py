"""The listening path's state machine, with a loudness VAD, a stub STT and a scripted turn model."""
import asyncio

import numpy as np

from laghu_voice.audio.vad import EnergyVAD
from laghu_voice.orchestrator.listener import WIN, Listener, ListenConfig
from laghu_voice.services.stt_indic import STTBase

SR = 16000


class CountingSTT(STTBase):
    """Returns 'w1', 'w2', ... per call, so the order of segments is visible in the transcript."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def transcribe(self, audio):
        self.calls.append(len(audio) / SR)
        return f"w{len(self.calls)}"


class ScriptedTurn:
    def __init__(self, probs):
        self.probs = list(probs)
        self.asked = 0

    def probability(self, audio):
        self.asked += 1
        return self.probs[min(self.asked - 1, len(self.probs) - 1)]


def speech(ms):
    t = np.arange(int(SR * ms / 1000)) / SR
    return (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def silence(ms):
    return np.zeros(int(SR * ms / 1000), np.float32)


async def run(listener, *parts, settle=0.3):
    x = np.concatenate(parts)
    for i in range(0, len(x), WIN):
        listener.feed_float(x[i:i + WIN])
        await asyncio.sleep(0.001)         # let decodes and turn-model answers land, roughly in order
    await asyncio.sleep(settle)


def make(turn_model, stt=None, **cfg):
    turns, events = [], []

    async def on_turn(t):
        turns.append(t)

    async def on_event(ev):
        events.append(ev)
    stt = stt or CountingSTT()
    return Listener(EnergyVAD(), stt, turn_model, on_turn, on_event, "test", ListenConfig(**cfg)), turns, events, stt


async def test_one_utterance_ends_on_the_turn_model():
    lis, turns, events, stt = make(ScriptedTurn([0.9]))
    await run(lis, silence(300), speech(1000), silence(800))
    assert len(turns) == 1
    t = turns[0]
    assert t.end_reason == "turn_model" and t.text == "w1"
    rec = t.trace.to_record()
    assert rec["kind"] == "user" and len(rec["segments"]) == 1
    assert rec["turn_checks"][0]["prob"] == 0.9
    lat = rec["latency_ms"]
    assert lat["speech_end_to_transcript"] >= 0 and lat["speech_end_to_turn_end"] >= 0
    # the decode started 96 ms into the silence and includes the pre-roll and a 96 ms tail
    assert 1.0 < stt.calls[0] < 1.0 + 0.32 + 0.1 + 0.05
    assert [e["speech"] for e in events if e["type"] == "vad"][:2] == [True, False]
    await lis.close()


async def test_short_pause_throws_the_speculative_decode_away():
    lis, turns, _, stt = make(ScriptedTurn([0.9]))
    await run(lis, speech(600), silence(150), speech(600), silence(800))
    assert len(turns) == 1
    rec = turns[0].trace.to_record()
    assert rec["wasted_decodes"] == 1
    assert len(rec["segments"]) == 1                 # one segment covering both bursts
    assert rec["segments"][0]["end_s"] > 1.3
    await lis.close()


async def test_long_pause_keeps_both_segments_in_order():
    lis, turns, _, stt = make(ScriptedTurn([0.1, 0.9]))
    await run(lis, speech(600), silence(450), speech(600), silence(800))
    assert len(turns) == 1
    t = turns[0]
    assert t.text == "w1 w2" and t.end_reason == "turn_model"
    rec = t.trace.to_record()
    assert [c["prob"] for c in rec["turn_checks"] if not c["stale"]][:2] == [0.1, 0.9]
    assert rec["wasted_decodes"] == 0
    await lis.close()


async def test_without_a_turn_model_the_silence_timeout_ends_the_turn():
    lis, turns, _, _ = make(None)
    await run(lis, speech(500), silence(1000))
    assert len(turns) == 1 and turns[0].end_reason == "silence_only"
    sil = (turns[0].trace.marks["turn_end"] - turns[0].trace.marks["speech_end"]) / 1e6
    assert sil > 0
    await lis.close()


async def test_silence_cap_when_the_turn_model_never_agrees():
    lis, turns, _, _ = make(ScriptedTurn([0.1]))
    await run(lis, speech(500), silence(2000))
    assert len(turns) == 1 and turns[0].end_reason == "silence_cap"
    assert len(turns[0].trace.fields["turn_checks"]) >= 2
    await lis.close()


async def test_clicks_and_muted_audio_start_no_turn():
    lis, turns, _, stt = make(ScriptedTurn([0.9]))
    await run(lis, silence(192), speech(64), silence(800))   # 64 ms = two whole windows
    lis.set_muted(True)
    await run(lis, speech(800), silence(800))
    assert turns == [] and stt.calls == []
    lis.set_muted(False)
    await run(lis, speech(800), silence(800))
    assert len(turns) == 1
    await lis.close()


async def test_two_turns_in_a_row():
    lis, turns, _, _ = make(ScriptedTurn([0.9]))
    await run(lis, speech(500), silence(700), speech(500), silence(700))
    assert [t.turn_id for t in turns] == ["u1", "u2"]
    assert all(t.text for t in turns)
    await lis.close()


async def test_long_speech_without_pauses_is_cut():
    lis, turns, _, stt = make(ScriptedTurn([0.9]), max_segment_s=3.0)
    await run(lis, speech(7000), silence(800), settle=0.5)
    assert len(turns) == 1
    rec = turns[0].trace.to_record()
    assert len(rec["segments"]) >= 3 and rec.get("long_cuts")
    starts = [s["start_s"] for s in rec["segments"]]
    assert starts == sorted(starts)
    assert turns[0].text.split() == [f"w{i}" for i in range(1, len(rec["segments"]) + 1)]
    await lis.close()
