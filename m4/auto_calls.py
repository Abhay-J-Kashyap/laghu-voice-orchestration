"""Milestone 4, part B without a person: the five calls of m4/live_scripts.md, made by a program (Amendment 3).

    python m4/auto_calls.py                       # L1 to L5, against the server on ws://127.0.0.1:8765
    python m4/auto_calls.py --calls L2            # one call (not a judged run)

The caller speaks with Laghu's female voice, so the agent (male) hears a different speaker. Its audio goes
through the server's whole listening path exactly as a microphone's would: 16 kHz PCM in 20 ms frames, in real
time, with silence in between. The server can't tell it from a person on a headset.

How the caller behaves, as the scripts ask of a person:
- It answers the question the agent is asking: the agent's state, from its `dialog` events, picks the answer
  (so a question asked again gets the same answer again, as a caller would give it).
- It speaks only after the agent has finished: no audio left to play for 0.6 s (a person's reaction gap).
- It plays the agent's audio at real-time pace and reports playback, like the terminal client.
- The passcode is the one the backend sent (the `show` event), read out as Hindi digits.
- A question it has no answer for gets silence; the agent then re-asks and in the end hangs up. Each call
  counts once, and none is restarted.

Afterwards: `python m4/summarize_live.py --last 5` judges the five calls from their traces, as before.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
from websockets.asyncio.client import connect

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from laghu_voice.dialog import hindi  # noqa: E402
from laghu_voice.frames import unpack_audio  # noqa: E402

_spec = importlib.util.spec_from_file_location("lv_client", ROOT / "clients" / "cli" / "client.py")
client = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(client)

MIC_SR, MIC_FRAME, OUT_SR = client.MIC_SR, client.MIC_FRAME, client.SR
REACTION_S = 0.6             # the caller starts this long after the agent's audio has finished
CALL_LIMIT_S = 300           # a call still running after 5 minutes is stopped and counts as failed

YES = "हाँ जी, बताइए"         # Yes, go ahead
CONFIRM = "हाँ, सब सही है"    # Yes, all correct
OTP = "{otp}"
OTP_STATES = ["ask_otp_phone", "ask_otp_email", "otp_wrong", "otp_resent", "otp_expired_resent"]


def _identity(name: str, dob: str, pan: str) -> dict[str, str]:
    return {"greet": YES, "ask_name": f"मेरा नाम {name} है", "ask_name_again": f"मेरा नाम {name} है",
            "ask_dob": dob, "ask_pan": pan, "confirm_identity": CONFIRM, **{s: OTP for s in OTP_STATES}}


# m4/live_scripts.md, as the agent's state -> what the caller says (Devanagari, the way the STT writes it)
SCRIPTS: dict[str, dict[str, str]] = {
    "L1": {   # Rajesh, approved, agrees: completed
        **_identity("राजेश कुमार", "बारह अप्रैल उन्नीस सौ अठासी", "ए बी सी डी ई एक दो तीन चार एफ़"),
        "ask_amount": "तीन लाख रुपये", "ask_tenure": "तीन साल के लिए", "ask_income": "पचानवे हज़ार",
        "ask_employment": "मैं नौकरी करता हूँ", "ask_consent": "हाँ, मैं सहमत हूँ"},
    "L2": {   # Imran, declined, wants to talk to someone: transferred
        **_identity("इमरान क़ुरैशी", "इक्कीस जुलाई उन्नीस सौ इक्यानवे", "सी डी ई एफ़ जी तीन चार पाँच छह एच"),
        "ask_amount": "दो लाख", "ask_tenure": "दो साल", "ask_income": "साठ हज़ार",
        "ask_employment": "मेरा अपना बिज़नेस है", "declined": "हाँ, किसी से बात करवा दीजिए"},
    "L3": {   # Anita, approved, declines the terms: consent_declined
        **_identity("अनीता देसाई", "अठारह फ़रवरी उन्नीस सौ नब्बे", "एफ़ जी एच आई जे छह सात आठ नौ के"),
        "ask_amount": "एक लाख", "ask_tenure": "दो साल", "ask_income": "अट्ठासी हज़ार", "ask_employment": "नौकरी",
        "ask_consent": "नहीं, मुझे सोचना है"},
    "L4": {   # Priya, asks for too much, smaller offer, agrees: completed (no tenure question)
        **_identity("प्रिया शर्मा", "तीन नवंबर उन्नीस सौ चौरानवे", "बी सी डी ई एफ़ दो तीन चार पाँच जी"),
        "ask_amount": "पंद्रह लाख तीन साल के लिए", "ask_tenure": "तीन साल", "ask_income": "बयालीस हज़ार",
        "ask_employment": "सैलरी मिलती है", "ask_consent": "हाँ, ठीक है"},
    "L5": {   # Kavya, no account, leaves her details: lead_captured
        **_identity("काव्या रेड्डी", "चौदह अगस्त उन्नीस सौ बानवे", "ज़ेड ज़ेड ज़ेड ज़ेड ज़ेड नौ नौ नौ नौ ज़ेड"),
        "offer_lead": "हाँ, भेज दीजिए",
        "ask_email": "के ए वी वाई ए डॉट आर ई डी डी वाई एट एग्ज़ाम्पल डॉट कॉम", "confirm_email": "हाँ, सही है"},
}


class Voice:
    """Laghu with another voice: text -> int16 mono 16 kHz."""

    def __init__(self, laghu_dir: Path, voice: str):
        from laghu_voice.services.base import TTSResult
        from laghu_voice.services.tts_laghu import LaghuTTS

        self._result = TTSResult
        try:
            self.tts = LaghuTTS(laghu_dir, voice=voice)
        except Exception as e:  # noqa: BLE001 - most likely a voice name Laghu doesn't have
            have = sorted(p.stem for p in (Path(laghu_dir) / "model" / "voices").glob("*.npy"))
            raise SystemExit(f"can't load Laghu voice {voice!r} ({e!r}); voices here: {', '.join(have)}") from e

    async def say(self, text: str) -> np.ndarray:
        chunks = []
        async for c in self.tts.stream(text, threading.Event(), self._result()):
            chunks.append(np.asarray(c, np.float32))
        x = np.concatenate(chunks) if chunks else np.zeros(0, np.float32)
        return to_mic(x, self.tts.sample_rate)


def to_mic(x: np.ndarray, sr: int) -> np.ndarray:
    if sr != MIC_SR:
        from math import gcd

        from scipy.signal import resample_poly
        g = gcd(sr, MIC_SR)
        x = resample_poly(x, MIC_SR // g, sr // g)
    return (np.clip(x, -1, 1) * 32767).astype(np.int16)


async def call(url: str, script: dict[str, str], voice, log: list[str], on_line=None) -> dict:
    """One call. `on_line(text)` is told what the caller is about to say (tests use it as the STT)."""
    player = client.Player()
    st = {"state": None, "asked": 0, "answered": 0, "otp": "", "end": None, "session": None, "said": 0,
          "asked_at": 0.0}
    outgoing: asyncio.Queue[np.ndarray] = asyncio.Queue()
    last_audio = [time.perf_counter()]

    async with connect(url, max_size=2**20) as ws:
        async def mic():
            silence = np.zeros(MIC_FRAME, np.int16)
            current, pos, t_next = None, 0, time.perf_counter()
            while True:
                if current is None and not outgoing.empty():
                    current, pos = outgoing.get_nowait(), 0
                if current is not None:
                    frame = current[pos:pos + MIC_FRAME]
                    pos += MIC_FRAME
                    if pos >= len(current):
                        current = None
                    if len(frame) < MIC_FRAME:
                        frame = np.concatenate([frame, silence[:MIC_FRAME - len(frame)]])
                else:
                    frame = silence
                await ws.send(frame.tobytes())
                t_next += MIC_FRAME / MIC_SR
                await asyncio.sleep(max(0.0, t_next - time.perf_counter()))

        async def playback():
            t_last, sent = time.perf_counter(), {}
            while True:
                await asyncio.sleep(0.02)
                now = time.perf_counter()
                player.pull(int((now - t_last) * OUT_SR))
                t_last = now
                with player.lock:
                    busy = bool(player.chunks)
                    played = dict(player.played)
                if busy:
                    last_audio[0] = now
                for sid, n in played.items():
                    if sent.get(sid) != n:
                        sent[sid] = n
                        await ws.send(json.dumps({"type": "playback", "segment_id": sid, "samples": n}))

        async def receive():
            async for msg in ws:
                if isinstance(msg, bytes):
                    epoch, sid, pcm = unpack_audio(msg)
                    player.feed(epoch, sid, pcm)
                    last_audio[0] = time.perf_counter()
                    continue
                ev = json.loads(msg)
                kind = ev.get("type")
                if kind == "flush":
                    player.flush(ev["epoch"])
                elif kind == "user_turn" and not ev.get("backchannel"):
                    log.append(f"   heard: {ev['text'] or '(nothing)'}  [{ev['trace'].get('end_reason')}]")
                elif kind == "dialog" and ev.get("show"):
                    st["otp"] = str(ev["show"].get("demo_otp") or st["otp"])
                elif kind == "dialog":
                    if ev.get("end"):
                        st["end"] = ev["end"]
                    elif ev.get("state"):
                        st["state"] = ev["state"]
                        st["asked"] += 1
                        st["asked_at"] = time.perf_counter()
                    log.append(f"   agent: {ev.get('event') or 'start'} -> {ev.get('state') or ev.get('end')}")
                elif kind == "segment_start":
                    log.append(f"   agent says: {ev['text']}")
                elif kind == "end_call":
                    st["end"], st["session"] = ev["reason"], ev.get("backend_session")
                    return

        async def caller():
            while st["end"] is None:
                await asyncio.sleep(0.05)
                if st["answered"] >= st["asked"] or st["state"] is None:
                    continue
                now = time.perf_counter()
                if now - last_audio[0] < REACTION_S:
                    continue
                if last_audio[0] < st["asked_at"] and now - st["asked_at"] < 3.0:
                    continue                  # the reply's audio may not have started arriving yet
                st["answered"] = st["asked"]
                text = script.get(st["state"])
                if text is None:
                    log.append(f"   (no answer scripted for {st['state']}: silence)")
                    continue
                text = text.replace(OTP, hindi.digits_words(st["otp"]))
                audio = await voice.say(text)
                if on_line is not None:
                    on_line(text)
                log.append(f"caller: {text}")
                st["said"] += 1
                await outgoing.put(audio)

        tasks = [asyncio.create_task(c()) for c in (mic, playback, caller)]
        try:
            await asyncio.wait_for(receive(), CALL_LIMIT_S)
        except asyncio.TimeoutError:
            log.append("   (call stopped after the time limit)")
        finally:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    return st


async def main_async(a) -> None:
    voice = Voice(Path(a.laghu_dir), a.voice)
    print(f"caller voice: Laghu {a.voice}; server {a.url}")
    for k, cid in enumerate(a.calls.split(",")):
        if k:
            await asyncio.sleep(a.gap)
        log: list[str] = []
        t0 = time.perf_counter()
        st = await call(a.url, SCRIPTS[cid], voice, log)
        print(f"\n== {cid}: ended {st['end']} in {time.perf_counter() - t0:.0f} s, "
              f"{st['said']} caller turns, backend session {st['session']}")
        print("\n".join(log))
    print("\nNow: python m4/summarize_live.py --last 5")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="ws://127.0.0.1:8765")
    ap.add_argument("--calls", default="L1,L2,L3,L4,L5")
    ap.add_argument("--voice", default="female", help="the caller's Laghu voice (the agent's is male)")
    ap.add_argument("--laghu-dir", default=str(ROOT / "vendor" / "laghu"))
    ap.add_argument("--gap", type=float, default=3.0, help="seconds between calls")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
