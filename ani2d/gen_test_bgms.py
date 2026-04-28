#!/usr/bin/env python3
"""Generate simple test AAC BGMs for states: idle/run/jump/attack."""

from __future__ import annotations

import math
import struct
import subprocess
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DURATION_SEC = 1.2
AMPLITUDE = 0.22

STATE_FREQ = {
    "idle": 330.0,
    "run": 440.0,
    "jump": 660.0,
    "attack": 550.0,
}


def _write_sine_wav(path: Path, freq: float) -> None:
    frame_count = int(SAMPLE_RATE * DURATION_SEC)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)

        for i in range(frame_count):
            t = i / SAMPLE_RATE
            # Simple fade-out to avoid click at end.
            fade = max(0.0, 1.0 - (t / DURATION_SEC) * 0.15)
            sample = AMPLITUDE * fade * math.sin(2.0 * math.pi * freq * t)
            pcm = int(max(-1.0, min(1.0, sample)) * 32767)
            wf.writeframesraw(struct.pack("<h", pcm))


def _convert(in_wav: Path, out_audio: Path, fmt: str) -> None:
    cmd = [
        "afconvert",
        "-f",
        fmt,
        str(in_wav),
        str(out_audio),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parent
    out_dir = root / "tmp" / "bgms"
    out_dir.mkdir(parents=True, exist_ok=True)

    for state, freq in STATE_FREQ.items():
        wav_path = out_dir / f"{state}.wav"
        _write_sine_wav(wav_path, freq)

        out_path = out_dir / f"{state}.aac"
        _convert(wav_path, out_path, "adts")

        print(f"[gen_test_bgms] {state}: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
