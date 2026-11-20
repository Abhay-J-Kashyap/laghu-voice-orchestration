"""Frames passed between pipeline stages (design doc: Runtime model).

Every frame that belongs to an agent reply carries the session epoch it was made in. When a barge-in
increments the epoch, every stage drops frames from older epochs, wherever they are sitting.
Milestone 1 only needs the speaking-path frames; the listening-path frames arrive in Milestone 2.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

SAMPLE_RATE_OUT = 24_000          # Laghu / Mimi output rate
FRAME_SAMPLES_OUT = 1_920         # one Mimi frame = 80 ms at 24 kHz
AUDIO_HEADER = struct.Struct("<II")  # epoch, segment_id: prefixed to every binary audio frame sent to the client


@dataclass(frozen=True)
class SpeakText:
    """A segment of agent text ready for TTS."""
    text: str
    epoch: int
    segment_id: int
    turn_id: str


@dataclass(frozen=True)
class AudioOut:
    """One frame of agent audio: PCM16 mono at 24 kHz, normally 80 ms."""
    pcm: bytes
    epoch: int
    segment_id: int
    turn_id: str
    sample_offset: int      # first sample of this frame, counted from the start of its segment
    last: bool = False      # last frame of its segment

    @property
    def n_samples(self) -> int:
        return len(self.pcm) // 2


def pack_audio(frame: AudioOut) -> bytes:
    """Wire format of a server-to-client audio message: 8-byte header + PCM16 little-endian."""
    return AUDIO_HEADER.pack(frame.epoch, frame.segment_id) + frame.pcm


def unpack_audio(msg: bytes) -> tuple[int, int, bytes]:
    epoch, segment_id = AUDIO_HEADER.unpack_from(msg)
    return epoch, segment_id, msg[AUDIO_HEADER.size:]
