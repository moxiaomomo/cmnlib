#!/usr/bin/env python3
"""使用 %Nd 简化参数语法生成 out_test4_simplified.a2d"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STATES = ["idle", "run", "jump", "attack"]
OUT_A2D = Path("ani2d/output/out_test4_simplified.a2d")


def encode() -> None:
    """使用 %02d 模式而不是逐列表示"""
    state_names = ",".join(STATES)
    
    # 使用 %02d 模式，而不是逐一列举文件
    input_patterns = [
        f"ani2d/tmp/test4/{state}/{state}_%02d.png"
        for state in STATES
    ]
    
    total_frames = sum([12, 10, 11, 14])
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
    ] + input_patterns

    print("[encode] running with simplified %02d patterns …")
    print(f"  patterns: {input_patterns}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print("[ERROR]", result.stderr)
        sys.exit(1)

    # Copy to simplified filename
    src = Path("ani2d/output/out.a2d")
    OUT_A2D.parent.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.copy2(src, OUT_A2D)
    print(f"[encode] copied → {OUT_A2D}")


if __name__ == "__main__":
    encode()
