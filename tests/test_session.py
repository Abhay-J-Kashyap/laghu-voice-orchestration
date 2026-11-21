"""The speaking path end to end in-process, with the stub TTS and the real pacer (real time, short texts)."""
import asyncio
import time

from laghu_voice.config import Settings
from laghu_voice.obs.trace import TraceWriter
from laghu_voice.orchestrator.session import Session
from laghu_voice.services.tts_stub import StubTTS


class Recorder:
    def __init__(self, session_ref):
        self.frames = []
        self.events = []
        self.session_ref = session_ref

    async def audio(self, f):
        self.frames.append((time.perf_counter(), f, self.session_ref[0].epoch))

    async def event(self, ev):
        self.events.append((time.perf_counter(), ev))


def make_session(**tts_kw):
    ref = [None]
    rec = Recorder(ref)
    s = Session(StubTTS(**tts_kw), rec.audio, rec.event, Settings(), session_id="test",
                trace_writer=TraceWriter(None, "test"))
    ref[0] = s
    s.start()
    return s, rec


async def wait_for(cond, timeout=5.0):
    t = time.perf_counter()
    while not cond():
        assert time.perf_counter() - t < timeout, "timed out"
        await asyncio.sleep(0.01)


async def test_say_speaks_every_segment_in_order_and_writes_a_trace():
    s, rec = make_session(first_audio_ms=5, rtf=50, ms_per_char=20)
    await s.say("नमस्ते। आप कैसे हैं?")
    await wait_for(lambda: s.trace.records)
    r = s.trace.records[0]
    assert r["outcome"] == "completed"
    assert [seg["text"] for seg in r["segments"]] == ["नमस्ते।", "आप कैसे हैं?"]
    assert all(seg["samples_sent"] > 0 for seg in r["segments"])
    for name in ["text_start", "first_segment_ready", "tts_first_audio", "first_audio_sent", "agent_audio_end_sent"]:
        assert name in r["ms"], name
    sids = [f.segment_id for _, f, _ in rec.frames]
    assert sids == sorted(sids)
    assert [ev["type"] for _, ev in rec.events].count("segment_start") == 2
    await s.close()


async def test_interrupt_stops_audio_and_nothing_stale_is_sent_afterwards():
    s, rec = make_session(first_audio_ms=5, rtf=50, ms_per_char=80)
    await s.say("यह एक लंबा जवाब है जो बीच में रोका जाएगा। " * 4)
    await wait_for(lambda: len(rec.frames) >= 5)
    await s.interrupt("test")
    t_flush = next(t for t, ev in rec.events if ev["type"] == "flush")
    await asyncio.sleep(0.5)
    late = [f for t, f, _ in rec.frames if t > t_flush]
    assert late == [], "audio from the interrupted epoch reached the client after the flush"
    r = s.trace.records[0]
    assert r["outcome"] == "interrupted"
    playing = [seg for seg in r["segments"] if seg["samples_sent"] > 0]
    assert playing and all(seg["model_text"] for seg in playing), "segments that were spoken must record their text"
    assert r["ms"]["flush_sent"] - r["ms"]["interrupt_received"] < 50
    await s.close()


async def test_new_turn_after_interrupt_is_spoken():
    s, rec = make_session(first_audio_ms=5, rtf=50, ms_per_char=80)
    await s.say("पहला जवाब काफ़ी लंबा है ताकि हम इसे रोक सकें।")
    await wait_for(lambda: len(rec.frames) >= 2)
    await s.interrupt("test")
    await s.say("दूसरा।")
    await wait_for(lambda: len(s.trace.records) == 2)
    assert [r["outcome"] for r in s.trace.records] == ["interrupted", "completed"]
    assert {f.epoch for _, f, _ in rec.frames if f.turn_id == "t2"} == {1}
    await s.close()


async def test_pacer_keeps_client_buffer_small():
    s, rec = make_session(first_audio_ms=5, rtf=50, ms_per_char=40)
    await s.say("यह वाक्य लगभग दो सेकंड का ऑडियो बनाएगा, शायद थोड़ा ज़्यादा।")
    await wait_for(lambda: s.trace.records)
    t0 = rec.frames[0][0]
    sent_audio = 0.0
    for t, f, _ in rec.frames:
        assert sent_audio - (t - t0) <= 0.2 + 0.03, "more than the 200 ms lead was buffered at the client"
        sent_audio += f.n_samples / 24000
    await s.close()


def test_heard_estimate_prorates_the_interrupted_segment():
    from laghu_voice.orchestrator.session import SegmentState, heard_estimate
    a = SegmentState(1, "t1", 0, "पहला वाक्य।", samples_sent=48000, samples_played=48000, done=True)
    b = SegmentState(2, "t1", 0, "दूसरा वाक्य लंबा है।", samples_sent=48000, samples_played=24000)
    c = SegmentState(3, "t1", 0, "तीसरा।", samples_sent=0, samples_played=0)
    h = heard_estimate([a, b, c])
    assert h["played_s"] == 3.0
    assert h["text_estimate"].startswith("पहला वाक्य। दूसरा") and h["text_estimate"].endswith("…")
    assert "तीसरा" not in h["text_estimate"]
    assert heard_estimate([c]) == {"text_estimate": "", "played_s": 0.0}
