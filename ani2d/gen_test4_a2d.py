#!/usr/bin/env python3
"""生成4种状态 (idle/run/jump/attack) 各10+帧测试PNG，然后编码成 out_test4.a2d"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

STATES: dict[str, dict] = {
    "idle":   {"color": (80,  160, 220), "frames": 12},
    "run":    {"color": (80,  200,  80), "frames": 10},
    "jump":   {"color": (240, 180,  40), "frames": 11},
    "attack": {"color": (220,  60,  60), "frames": 14},
}
W, H = 80, 80
BASE = Path("ani2d/tmp/test4")
OUT_A2D = Path("ani2d/output/out_test4.a2d")


def gen_frames() -> None:
    for state_name, cfg in STATES.items():
        d = BASE / state_name
        d.mkdir(parents=True, exist_ok=True)
        r, g, b = cfg["color"]
        n = cfg["frames"]
        for i in range(n):
            alpha = int(120 + 135 * (i / max(n - 1, 1)))
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            margin = 4 + i * 2
            draw.ellipse(
                [margin, margin, W - margin, H - margin],
                fill=(r, g, b, alpha),
            )
            text = f"{i + 1:02d}"
            draw.text((W // 2 - 8, H // 2 - 8), text, fill=(255, 255, 255, 255))
            path = d / f"{state_name}_{i:02d}.png"
            img.save(path)
        print(f"[gen] {state_name}: {n} frames → {d}")


def encode() -> None:
    state_names = ",".join(STATES.keys())
    input_groups: list[str] = []
    for state_name, cfg in STATES.items():
        d = BASE / state_name
        files = sorted(d.glob(f"{state_name}_??.png"))
        input_groups.append(",".join(str(f) for f in files))

    total_frames = sum(cfg["frames"] for cfg in STATES.values())
    # --durationsMs expects space-separated integers (one per frame)
    durations_args = ["80"] * total_frames

    cmd = [
        sys.executable, "ani2d/ani2d_tool.py", "encode",
        "--stateNames", state_names,
        "--fps", "12",
        "--durationsMs", *durations_args,
        "--padding", "2",
        "--maxAtlasWidth", "512",
        "--maxAtlasHeight", "512",
        "--inputImgs",
    ] + input_groups

    print("\n[encode] running …")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR]", result.stderr)
        sys.exit(1)

    # ani2d_tool always writes to ani2d/output/out.a2d; rename to test4
    src = Path("ani2d/output/out.a2d")
    OUT_A2D.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, OUT_A2D)
    print(f"[encode] copied → {OUT_A2D}")


if __name__ == "__main__":
    gen_frames()
    encode()
