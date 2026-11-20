"""The pacer keeps at most `lead_ms` of audio ahead of the listener, on a simulated clock."""
import asyncio

from laghu_voice.frames import FRAME_SAMPLES_OUT, AudioOut
from laghu_voice.orchestrator.pacing import AudioPacer


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.t += s
        await asyncio.sleep(0)


def frame(epoch=0, i=0):
    return AudioOut(b"\0\0" * FRAME_SAMPLES_OUT, epoch, 1, "t1", i * FRAME_SAMPLES_OUT)


async def run_pacer(n_frames, lead_ms=200, epoch_fn=lambda: 0):
    clock = FakeClock()
    sent = []

    async def send(f):
        sent.append((clock(), f))

    p = AudioPacer(send, epoch_fn, lead_ms=lead_ms, clock=clock, sleep=clock.sleep, maxsize=0)
    for i in range(n_frames):
        p.q.put_nowait(frame(i=i))
    p.q.put_nowait(None)
    await p.run()
    return clock, sent


async def test_never_more_than_lead_ahead():
    clock, sent = await run_pacer(20, lead_ms=200)
    t0 = sent[0][0]
    for k, (t, _) in enumerate(sent):
        audio_before = k * 0.08                     # seconds of audio already sent before this frame
        assert audio_before - (t - t0) <= 0.2 + 1e-9
    # 20 frames = 1.6 s of audio; the last frame leaves when 0.2 s remain buffered, minus its own 0.08 s
    assert abs((sent[-1][0] - t0) - (1.6 - 0.08 - 0.2)) < 1e-6


async def test_first_frames_go_out_immediately():
    clock, sent = await run_pacer(3, lead_ms=200)
    assert [t for t, _ in sent] == [sent[0][0]] * 3   # 240 ms total, first 3 frames fit in the 200 ms lead


async def test_stale_epoch_frames_are_dropped():
    clock, sent = await run_pacer(5, epoch_fn=lambda: 1)   # frames are epoch 0, session moved on
    assert sent == []


async def test_flush_resets_buffer_and_queue():
    clock = FakeClock()
    p = AudioPacer(lambda f: None, lambda: 0, clock=clock, sleep=clock.sleep, maxsize=0)
    p.buffer_end = clock() + 5.0
    for i in range(4):
        p.q.put_nowait(frame(i=i))
    assert p.flush() == 4
    assert p.q.empty() and p.buffered_s() == 0.0
