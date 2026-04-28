#!/usr/bin/env python3
"""Generate test A2D with 4 states and per-state BGMs."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> None:
    print("[run]", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main() -> int:
    # 1) Ensure bgm files exist.
    _run([sys.executable, str(ROOT / "gen_test_bgms.py")])

    # 2) Build .a2d with bgms.
    bgms = (
        "idle:ani2d/tmp/bgms/idle.aac;"
        "run:ani2d/tmp/bgms/run.aac;"
        "jump:ani2d/tmp/bgms/jump.aac;"
        "attack:ani2d/tmp/bgms/attack.aac"
    )

    cmd = [
        sys.executable,
        "ani2d/ani2d_tool.py",
        "encode",
        "--stateNames",
        "idle,run,jump,attack",
        "--bgms",
        bgms,
        "--fps",
        "12",
        "--padding",
        "2",
        "--maxAtlasWidth",
        "512",
        "--maxAtlasHeight",
        "512",
        "--inputImgs",
        "ani2d/tmp/test4/idle/idle_%02d.png",
        "ani2d/tmp/test4/run/run_%02d.png",
        "ani2d/tmp/test4/jump/jump_%02d.png",
        "ani2d/tmp/test4/attack/attack_%02d.png",
    ]
    _run(cmd)

    src = ROOT / "output" / "out.a2d"
    dst = ROOT / "output" / "out_test4_bgm.a2d"
    dst.write_bytes(src.read_bytes())
    print(f"[ok] {dst}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
