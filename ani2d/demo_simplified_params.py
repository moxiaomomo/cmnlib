#!/usr/bin/env python3
"""
演示 --inputImgs 简化参数语法

支持以下形式：
1. 单个文件: img.png
2. 多个文件逗号分隔: img1.png,img2.png,img3.png
3. 模式序列 %Nd: folder/img_%03d.png (自动展开为 img_000.png, img_001.png, ...)
4. 混合: 某些文件+模式: img_static.png,folder/seq_%02d.png
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def demo_single_state_with_pattern() -> None:
    """演示单状态下使用 %02d 模式"""
    print("\n" + "="*60)
    print("Demo 1: 单状态，使用 %02d 模式")
    print("="*60)
    
    cmd = [
        sys.executable, "ani2d/ani2d_tool.py", "encode",
        "--fps", "10",
        "--padding", "2",
        "--inputImgs", "ani2d/tmp/test4/idle/idle_%02d.png",
    ]
    print("Command:")
    print(f"  python ani2d_tool.py encode --fps 10 --padding 2 \\")
    print(f"    --inputImgs 'ani2d/tmp/test4/idle/idle_%02d.png'")
    print()
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")
        return
    print("✓ 成功")


def demo_multi_state_with_pattern() -> None:
    """演示多状态下使用 %02d 模式"""
    print("\n" + "="*60)
    print("Demo 2: 多状态，每个状态使用 %02d 模式")
    print("="*60)
    
    states = ["idle", "run"]
    cmd = [
        sys.executable, "ani2d/ani2d_tool.py", "encode",
        "--stateNames", ",".join(states),
        "--fps", "10",
        "--padding", "2",
        "--inputImgs",
        *[f"ani2d/tmp/test4/{s}/{s}_%02d.png" for s in states],
    ]
    print("Command:")
    print(f"  python ani2d_tool.py encode \\")
    print(f"    --stateNames idle,run \\")
    print(f"    --fps 10 --padding 2 \\")
    print(f"    --inputImgs 'ani2d/tmp/test4/idle/idle_%02d.png' \\")
    print(f"               'ani2d/tmp/test4/run/run_%02d.png'")
    print()
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")
        return
    print("✓ 成功")


def demo_mixed_files_and_pattern() -> None:
    """演示混合使用单个文件和模式"""
    print("\n" + "="*60)
    print("Demo 3: 混合单个文件和 %02d 模式序列")
    print("="*60)
    
    cmd = [
        sys.executable, "ani2d/ani2d_tool.py", "encode",
        "--fps", "10",
        "--padding", "2",
        "--inputImgs",
        "ani2d/tmp/test4/idle/idle_00.png,ani2d/tmp/test4/idle/idle_%02d.png",
    ]
    print("Command:")
    print(f"  python ani2d_tool.py encode --fps 10 --padding 2 \\")
    print(f"    --inputImgs 'ani2d/tmp/test4/idle/idle_00.png,ani2d/tmp/test4/idle/idle_%02d.png'")
    print()
    print("  (先添加 idle_00.png，然后自动展开 idle_00.png~idle_11.png)")
    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[ERROR] {result.stderr}")
        return
    print("✓ 成功")


if __name__ == "__main__":
    import os
    os.chdir("/Users/moguang/Projects/cmnlib")
    
    demo_single_state_with_pattern()
    demo_multi_state_with_pattern()
    demo_mixed_files_and_pattern()
    
    print("\n" + "="*60)
    print("所有演示完成！")
    print("="*60)
