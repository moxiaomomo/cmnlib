#!/usr/bin/env python3
"""ani2d encoder/decoder/player.

新格式说明 (不兼容旧版本):
1) 每个 stateName 的 inputImgs 单独打包成各自 atlas PNG
2) .a2d 文件按 8 字节对齐组装: header + json + state_png_chunks
3) play 可按 stateName 按需加载并渲染，降低复杂状态机场景下的解码开销
"""

from __future__ import annotations

import argparse
import concurrent.futures
import glob
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageTk, features
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("缺少 Pillow 依赖，请先安装: pip install pillow") from exc


MAGIC = b"ANI2D"
VERSION = 2
ALIGNMENT = 8
HEADER_STRUCT = struct.Struct("<5sBHI")
# header: magic(5) + version(1) + state_count(uint16) + json_size(uint32)
RAW_FORCE_THRESHOLD_BYTES = 50 * 1024 * 1024
RAW_FORCE_THRESHOLD_MB_DEFAULT = 50.0
RAW_PNG_OPTIMIZE_THRESHOLD_BYTES = 100 * 1024


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _align_pad_len(current_len: int, alignment: int = ALIGNMENT) -> int:
    return (-current_len) % alignment


def _state_dir_name(name: str) -> str:
    cleaned = name.replace("/", "_").replace("\\", "_").strip()
    return cleaned or "default"


@dataclass
class Ani2dStateData:
    name: str
    storage: str
    atlas_image: Optional[Image.Image]
    raw_frames: Optional[List[Image.Image]]
    frames: List[Dict[str, Any]]
    bgm_data: Optional[bytes] = None
    bgm_codec: Optional[str] = None
    bgm_file_name: Optional[str] = None


@dataclass
class Ani2dData:
    meta: Dict[str, Any]
    states: Dict[str, Ani2dStateData]


def _load_image(path: Path) -> Image.Image:
    if path.suffix.lower() not in {".png", ".webp"}:
        raise ValueError(f"仅支持 PNG/WEBP: {path}")
    return Image.open(path).convert("RGBA")


def _webp_supported() -> bool:
    try:
        return bool(features.check("webp"))
    except Exception:
        return False


def _optimize_png_fallback(image: Image.Image) -> Image.Image:
    """WebP 不可用时的回退优化：降分辨率+降色深，降低中间帧体积。"""
    w, h = image.size
    if w > 0 and h > 0:
        # 面积缩放约到 64%，尽量保留可用清晰度
        new_w = max(1, int(round(w * 0.8)))
        new_h = max(1, int(round(h * 0.8)))
        image = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    # 转为调色板再转回 RGBA，显著减少颜色空间复杂度
    pal = image.convert("RGBA").quantize(colors=128, method=Image.Quantize.FASTOCTREE)
    return pal.convert("RGBA")


def _trim_transparent_border(image: Image.Image) -> Tuple[Image.Image, Dict[str, int]]:
    bbox = image.getbbox()
    source_w, source_h = image.size
    if bbox is None:
        # 全透明图至少保留 1x1，避免后续编码异常
        trimmed = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
        return trimmed, {
            "sourceW": source_w,
            "sourceH": source_h,
            "offsetX": 0,
            "offsetY": 0,
        }

    left, top, right, bottom = bbox
    trimmed = image.crop(bbox)
    return trimmed, {
        "sourceW": source_w,
        "sourceH": source_h,
        "offsetX": left,
        "offsetY": top,
    }


def _restore_trimmed_frame(frame_image: Image.Image, frame_meta: Dict[str, Any]) -> Image.Image:
    source_w = int(frame_meta.get("sourceW", frame_image.width))
    source_h = int(frame_meta.get("sourceH", frame_image.height))
    offset_x = int(frame_meta.get("offsetX", 0))
    offset_y = int(frame_meta.get("offsetY", 0))

    if (
        source_w == frame_image.width
        and source_h == frame_image.height
        and offset_x == 0
        and offset_y == 0
    ):
        return frame_image

    canvas = Image.new("RGBA", (max(1, source_w), max(1, source_h)), (0, 0, 0, 0))
    canvas.paste(frame_image, (offset_x, offset_y))
    return canvas


def _optimize_png_bytes(png_bytes: bytes, optimize_mode: str) -> Tuple[bytes, Optional[str]]:
    if optimize_mode == "none":
        return png_bytes, None

    pngquant_path = shutil.which("pngquant")
    if not pngquant_path:
        return png_bytes, None

    with tempfile.TemporaryDirectory(prefix="ani2d_pngquant_") as tmp_dir_name:
        tmp_dir = Path(tmp_dir_name)
        input_path = tmp_dir / "input.png"
        output_path = tmp_dir / "output.png"
        input_path.write_bytes(png_bytes)

        try:
            proc = subprocess.run(
                [
                    pngquant_path,
                    "--force",
                    "--skip-if-larger",
                    "--speed",
                    "1",
                    "--quality",
                    "55-95",
                    "--output",
                    str(output_path),
                    str(input_path),
                ],
                capture_output=True,
                check=False,
            )
        except Exception:
            return png_bytes, None

        if proc.returncode not in (0, 98) or not output_path.exists():
            return png_bytes, None

        optimized = output_path.read_bytes()
        if len(optimized) < len(png_bytes):
            return optimized, "pngquant"
        return png_bytes, None


def _next_power_of_two(v: int) -> int:
    if v <= 1:
        return 1
    return 1 << (v - 1).bit_length()


def _shelf_pack_sizes(
    sizes: List[Tuple[int, int]],
    atlas_width: int,
    padding: int,
) -> Optional[Tuple[List[Tuple[int, int]], int]]:
    x = 0
    y = 0
    row_height = 0
    positions: List[Tuple[int, int]] = []

    for w, h in sizes:
        packed_w = w + padding * 2
        packed_h = h + padding * 2

        if packed_w > atlas_width:
            return None

        if x + packed_w > atlas_width:
            y += row_height
            x = 0
            row_height = 0

        positions.append((x + padding, y + padding))
        x += packed_w
        if packed_h > row_height:
            row_height = packed_h

    total_height = y + row_height
    return positions, total_height


def _build_single_state_atlas(
    state_name: str,
    images: List[Image.Image],
    names: List[str],
    durations_ms: List[int],
    fps: int,
    padding: int = 0,
    max_atlas_width: Optional[int] = None,
    max_atlas_height: Optional[int] = None,
) -> Tuple[Image.Image, Dict[str, Any]]:
    if not images:
        raise ValueError(f"状态 {state_name} 没有输入图片")
    if len(images) != len(durations_ms):
        raise ValueError(f"状态 {state_name} durations 数量与帧数不一致")

    if padding < 0:
        raise ValueError("padding 不能为负数")
    if max_atlas_width is not None and max_atlas_width <= 0:
        raise ValueError("max_atlas_width 必须大于 0")
    if max_atlas_height is not None and max_atlas_height <= 0:
        raise ValueError("max_atlas_height 必须大于 0")

    sizes = [(img.width, img.height) for img in images]
    max_w = max(w + padding * 2 for w, _ in sizes)
    total_area = sum(w * h for w, h in sizes)
    padded_area = total_area + sum((w + h) * 2 * padding + 4 * padding * padding for w, h in sizes)

    min_candidate = max(max_w, int(padded_area ** 0.5))
    max_candidate = max(max_w, sum(w + padding * 2 for w, _ in sizes))
    if max_atlas_width is not None:
        max_candidate = min(max_candidate, max_atlas_width)

    candidate_widths: List[int] = []
    width = _next_power_of_two(min_candidate)
    limit = _next_power_of_two(max_candidate) if max_candidate > 0 else 0
    while width <= limit:
        candidate_widths.append(width)
        width <<= 1

    if max_w <= max_candidate and max_w not in candidate_widths:
        candidate_widths.append(max_w)
    if max_atlas_width is not None and max_atlas_width >= max_w:
        candidate_widths = [w for w in candidate_widths if w <= max_atlas_width]
    candidate_widths = sorted(set(candidate_widths))

    best_width = 0
    best_height = 0
    best_positions: List[Tuple[int, int]] = []
    best_area = 0

    for cw in candidate_widths:
        packed = _shelf_pack_sizes(sizes, cw, padding=padding)
        if packed is None:
            continue
        positions, ch = packed
        if max_atlas_height is not None and ch > max_atlas_height:
            continue
        area = cw * ch
        if not best_positions or area < best_area or (area == best_area and cw < best_width):
            best_width = cw
            best_height = ch
            best_positions = positions
            best_area = area

    if not best_positions:
        raise ValueError(
            f"状态 {state_name} 无法完成图集装箱，请调整 padding 或放宽 maxAtlasWidth/maxAtlasHeight"
        )

    atlas = Image.new("RGBA", (best_width, best_height), (0, 0, 0, 0))
    frames: List[Dict[str, Any]] = []

    for idx, img in enumerate(images):
        x, y = best_positions[idx]
        atlas.paste(img, (x, y))
        frames.append(
            {
                "index": idx,
                "name": names[idx],
                "x": x,
                "y": y,
                "w": img.width,
                "h": img.height,
                "durationMs": int(durations_ms[idx]),
            }
        )

    meta = {
        "name": state_name,
        "fps": int(fps),
        "frameCount": len(frames),
        "atlas": {
            "width": best_width,
            "height": best_height,
            "layout": "shelf-binpack",
            "padding": int(padding),
        },
        "frames": frames,
    }
    return atlas, meta


def _build_single_state_raw(
    workers: int,
    state_name: str,
    images: List[Image.Image],
    names: List[str],
    durations_ms: List[int],
    fps: int,
    raw_frame_format: str = "png",
    raw_webp_quality: int = 80,
    raw_webp_lossless: bool = False,
) -> Tuple[List[bytes], Dict[str, Any]]:
    if not images:
        raise ValueError(f"状态 {state_name} 没有输入图片")
    if len(images) != len(durations_ms):
        raise ValueError(f"状态 {state_name} durations 数量与帧数不一致")

    fmt = raw_frame_format.lower().strip()
    if fmt not in {"png", "webp"}:
        raise ValueError("raw_frame_format 仅支持 png 或 webp")
    
    def _encode_frame(idx: int, images: List[Image.Image]) -> Tuple[int, List[bytes], List[Dict[str, Any]]]:
        cur_frame_bytes: List[bytes] = []
        cur_frames: List[Dict[str, Any]] = []
        for _, img in enumerate(images):
            with io.BytesIO() as frame_io:
                if fmt == "webp":
                    img.save(
                        frame_io,
                        format="WEBP",
                        quality=max(1, min(100, int(raw_webp_quality))),
                        lossless=bool(raw_webp_lossless),
                        method=6,
                    )
                else:
                    img.save(frame_io, format="PNG")
                png_bytes = frame_io.getvalue()
                optimizedBy: Optional[str] = None
                if fmt == "png" and len(png_bytes) > RAW_PNG_OPTIMIZE_THRESHOLD_BYTES:
                    png_bytes, optimizedBy = _optimize_png_bytes(png_bytes, "auto")

                cur_frame_bytes.append(png_bytes)
                src_name = names[idx]
                src_path = Path(src_name)
                frame_name = f"{src_path.stem}.{fmt}" if src_path.suffix else f"{src_name}.{fmt}"

                cur_frames.append(
                    {
                        "index": idx,
                        "name": frame_name,
                        "w": img.width,
                        "h": img.height,
                        "durationMs": int(durations_ms[idx]),
                        "byteSize": len(png_bytes),
                        "format": fmt,
                        "optimizedBy": optimizedBy if fmt == "png" else None,
                    }
                )
        return idx, cur_frame_bytes, cur_frames

    frame_bytes: List[bytes] = []
    frames: List[Dict[str, Any]] = []
    if workers <= 1:
        _, frame_bytes, frames = _encode_frame(0, images)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            each_frame_count = math.ceil(len(images) / workers)
            future_to_idx = {
                executor.submit(_encode_frame, idx, images[idx * each_frame_count:(idx + 1) * each_frame_count]): idx
                for idx in range(workers)
            }
            for future in concurrent.futures.as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    _, cur_frame_bytes, cur_frames = future.result()
                    frame_bytes.extend(cur_frame_bytes)
                    frames.extend(cur_frames)
                    print(f"[encode] state={state_name}, worker={idx}, encoded {len(cur_frames)} frames, totalEncoded={len(frames)} frames")
                except Exception as exc:
                    raise RuntimeError(f"状态 {state_name} 的帧 {idx} 编码失败: {exc}") from exc

    meta = {
        "name": state_name,
        "fps": int(fps),
        "frameCount": len(frames),
        "storage": "raw",
        "frames": frames,
    }
    print(f"[ani2dEncode] state={state_name}, workers={workers}, each_frame_count={each_frame_count}," 
          f" fps={fps}, len(frames)={len(frames)}, totalRawSize={sum(len(b) for b in frame_bytes)} bytes")
    return frame_bytes, meta


def _packed_chunk_size(chunks: List[bytes]) -> int:
    total = 0
    for chunk in chunks:
        total += len(chunk)
        total += _align_pad_len(len(chunk))
    return total


def _parse_state_names(state_names_raw: Optional[str]) -> List[str]:
    if state_names_raw is None:
        return ["default"]

    state_names = [v.strip() for v in state_names_raw.split(",") if v.strip()]
    if not state_names:
        raise ValueError("--stateNames 至少包含一个非空状态名")
    if len(state_names) != len(set(state_names)):
        raise ValueError("--stateNames 中状态名不能重复")
    return state_names


def _expand_pattern_sequence(pattern: str) -> List[str]:
    """
    扩展 %Nd 格式的文件序列模式。
    例如: "folder/img_%03d.png" -> ["folder/img_000.png", "folder/img_001.png", ...]
    查找从 0 开始连续的文件，直到某个编号的文件不存在。
    """
    match = re.search(r'%(\d*)d', pattern)
    if not match:
        # 不是 %d 格式，直接作为单个文件返回
        return [pattern]
    
    width_str = match.group(1)
    glob_pattern = re.sub(r'%\d*d', '*', pattern)
    matched_files = sorted(glob.glob(glob_pattern))

    if not matched_files:
        # 若 glob 没找到，按 0,1,2... 连续探测
        result: List[str] = []
        idx = 0
        while True:
            formatted = pattern % (idx,)
            if not Path(formatted).exists():
                break
            result.append(formatted)
            idx += 1
        if result:
            return result
        raise ValueError(f"未找到匹配 {pattern} 的文件序列")

    def extract_number(filepath: str) -> tuple[int | None, str]:
        basename = Path(filepath).name
        pattern_name = Path(pattern).name
        test_pattern = pattern_name.replace('%' + width_str + 'd', '(\\d+)')
        test_match = re.search(test_pattern, basename)
        if test_match:
            return (int(test_match.group(1)), filepath)
        return (None, filepath)

    numbered = [extract_number(f) for f in matched_files]
    numbered_sort = sorted(numbered, key=lambda x: (x[0] is None, x[0], x[1]))
    return [path for _, path in numbered_sort]


def _split_csv_values(value: str) -> List[str]:
    parts = [v.strip() for v in value.split(",") if v.strip()]
    result: List[str] = []
    for part in parts:
        if '%' in part and 'd' in part:
            try:
                result.extend(_expand_pattern_sequence(part))
            except ValueError:
                result.append(part)
        else:
            result.append(part)
    return result


def _parse_bgms(bgms_raw: Optional[str], state_names: List[str]) -> Dict[str, Path]:
    if bgms_raw is None:
        return {}

    mapping: Dict[str, Path] = {}
    known = set(state_names)
    entries = [v.strip() for v in bgms_raw.split(";") if v.strip()]

    for item in entries:
        if ":" not in item:
            raise ValueError(f"--bgms 配置格式错误: {item}，应为 state:path")
        state_name, raw_path = item.split(":", 1)
        state_name = state_name.strip()
        raw_path = raw_path.strip()

        if not state_name or not raw_path:
            raise ValueError(f"--bgms 配置格式错误: {item}，应为 state:path")
        if state_name not in known:
            raise ValueError(f"--bgms 中存在未知状态: {state_name}")

        p = Path(raw_path).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"bgm 文件不存在: {p}")
        ext = p.suffix.lower()
        if ext not in {".mp3", ".aac"}:
            raise ValueError(f"bgm 仅支持 mp3 或 aac: {p}")
        if state_name in mapping:
            raise ValueError(f"--bgms 中状态重复: {state_name}")
        mapping[state_name] = p
    return mapping


def _parse_state_input_groups(input_imgs: List[str], state_names: List[str]) -> List[List[str]]:
    if not input_imgs:
        raise ValueError("--inputImgs 至少提供一张 PNG")

    if len(state_names) == 1:
        flat: List[str] = []
        for token in input_imgs:
            flat.extend(_split_csv_values(token))
        if not flat:
            raise ValueError("--inputImgs 至少提供一张 PNG")
        return [flat]

    if len(input_imgs) != len(state_names):
        raise ValueError(
            f"多状态模式下 --inputImgs 数量({len(input_imgs)})必须与状态数({len(state_names)})一致"
        )

    grouped: List[List[str]] = []
    for idx, token in enumerate(input_imgs):
        seq = _split_csv_values(token)
        if not seq:
            raise ValueError(f"状态 {state_names[idx]} 的图片序列不能为空")
        grouped.append(seq)
    return grouped


def _normalize_durations(
    frame_count: int,
    fps: int,
    durations_ms: Optional[List[int]],
) -> List[int]:
    if fps <= 0:
        raise ValueError("fps 必须大于 0")

    if durations_ms is None:
        return [max(1, int(round(1000 / fps)))] * frame_count

    if len(durations_ms) != frame_count:
        raise ValueError(f"--durationsMs 数量({len(durations_ms)})与帧数({frame_count})不一致")

    normalized = [int(v) for v in durations_ms]
    if any(v <= 0 for v in normalized):
        raise ValueError("--durationsMs 中每一项必须大于 0")
    return normalized


def _ani2dEncode(
    input_imgs: List[str],
    base_dir: Path,
    state_names_raw: Optional[str] = None,
    bgms_raw: Optional[str] = None,
    ani_file: Optional[str] = None,
    size_mode: str = "auto",
    atlas_optimize: str = "auto",
    trim_transparent: bool = True,
    fps: int = 10,
    durations_ms: Optional[List[int]] = None,
    padding: int = 0,
    max_atlas_width: Optional[int] = None,
    max_atlas_height: Optional[int] = None,
    raw_force_threshold_mb: float = RAW_FORCE_THRESHOLD_MB_DEFAULT,
    raw_frame_format: str = "png",
    raw_webp_quality: int = 80,
    raw_webp_lossless: bool = False,
    workers: int = 1,
) -> Path:
    if size_mode not in {"auto", "atlas", "raw"}:
        raise ValueError("size_mode 仅支持: auto, atlas, raw")
    if atlas_optimize not in {"auto", "none", "pngquant"}:
        raise ValueError("atlas_optimize 仅支持: auto, none, pngquant")
    if raw_force_threshold_mb <= 0:
        raise ValueError("raw_force_threshold_mb 必须大于 0")
    if raw_frame_format not in {"png", "webp"}:
        raise ValueError("raw_frame_format 仅支持: png, webp")

    raw_force_threshold_bytes = int(raw_force_threshold_mb * 1024 * 1024)
    force_raw_by_format = raw_frame_format == "webp"

    state_names = _parse_state_names(state_names_raw)
    grouped_inputs = _parse_state_input_groups(input_imgs, state_names)
    bgm_mapping = _parse_bgms(bgms_raw, state_names)

    if workers <= 0:
        cpu_count = os.cpu_count() or 1
        workers = max(1, min(len(state_names), cpu_count))

    total_frames = sum(len(g) for g in grouped_inputs)
    flat_durations = _normalize_durations(total_frames, fps=fps, durations_ms=durations_ms)

    unique_id = str(uuid.uuid4())
    tmp_dir = base_dir / "tmp"
    out_dir = base_dir / "output"
    json_path = tmp_dir / f"{unique_id}.json"
    if ani_file is not None and ani_file.strip():
        a2d_path = Path(ani_file).expanduser().resolve()
    else:
        a2d_path = out_dir / "out.a2d"
    ensure_parent(json_path)
    ensure_parent(a2d_path)

    state_jobs: List[Tuple[int, str, List[str], List[int]]] = []
    duration_offset = 0
    for state_idx, (state_name, state_inputs) in enumerate(zip(state_names, grouped_inputs)):
        state_frame_count = len(state_inputs)
        state_durations = flat_durations[duration_offset:duration_offset + state_frame_count]
        duration_offset += state_frame_count
        state_jobs.append((state_idx, state_name, state_inputs, state_durations))
    print(
        f"[ani2dEncode] 开始处理状态帧数据，size_mode={size_mode}, atlas_optimize={atlas_optimize}, "
        f"raw_frame_format={raw_frame_format}, raw_force_threshold={raw_force_threshold_mb} MB, workers={workers} len(state_jobs)={len(state_jobs)}"
    )

    def _build_state_asset(workers:int, job: Tuple[int, str, List[str], List[int]]) -> Tuple[int, Dict[str, Any]]:
        state_idx, state_name, state_inputs, state_durations = job
        print(f"[ani2dEncode] 处理状态, idx:{state_idx} state_name:{state_name} frame_count:{len(state_inputs)}")
        img_paths = [Path(p).expanduser().resolve() for p in state_inputs]
        for p in img_paths:
            if not p.exists():
                raise FileNotFoundError(f"输入图片不存在: {p}")

        source_images = [_load_image(p) for p in img_paths]
        names = [p.name for p in img_paths]

        images: List[Image.Image] = []
        trim_infos: List[Dict[str, int]] = []
        for image, src_path in zip(source_images, img_paths):
            if trim_transparent and src_path.suffix.lower() == ".png":
                trimmed, trim_info = _trim_transparent_border(image)
                images.append(trimmed)
                trim_infos.append(trim_info)
            else:
                images.append(image)
                trim_infos.append(
                    {
                        "sourceW": image.width,
                        "sourceH": image.height,
                        "offsetX": 0,
                        "offsetY": 0,
                    }
                )

        raw_frame_bytes, raw_state_meta = _build_single_state_raw(
            workers=workers,
            state_name=state_name,
            images=images,
            names=names,
            durations_ms=state_durations,
            fps=fps,
            raw_frame_format=raw_frame_format,
            raw_webp_quality=raw_webp_quality,
            raw_webp_lossless=raw_webp_lossless,
        )
        for frame_meta, trim_info in zip(raw_state_meta["frames"], trim_infos):
            frame_meta.update(trim_info)

        raw_total_bytes = sum(len(v) for v in raw_frame_bytes)
        force_raw_by_size = raw_total_bytes > raw_force_threshold_bytes
        if force_raw_by_format and size_mode in {"auto", "atlas"}:
            print(
                f"[ani2dEncode] state {state_name}: rawFrameFormat=webp，直接使用 raw-frames 并跳过 atlas 生成"
            )
        if force_raw_by_size and size_mode in {"auto", "atlas"}:
            print(
                f"[ani2dEncode] state {state_name}: png序列总大小 {raw_total_bytes} bytes > "
                f"{raw_force_threshold_bytes} bytes，强制使用 raw-frames"
            )

        atlas_bytes: Optional[bytes] = None
        atlas_state_meta: Optional[Dict[str, Any]] = None
        atlas_tmp_path: Optional[Path] = None

        need_build_atlas = (size_mode != "raw") and not force_raw_by_format and not force_raw_by_size
        if need_build_atlas:
            atlas_image, atlas_state_meta = _build_single_state_atlas(
                state_name=state_name,
                images=images,
                names=names,
                durations_ms=state_durations,
                fps=fps,
                padding=padding,
                max_atlas_width=max_atlas_width,
                max_atlas_height=max_atlas_height,
            )

            atlas_tmp_name = f"{unique_id}_{state_idx:02d}_{_state_dir_name(state_name)}.png"
            atlas_tmp_path = tmp_dir / atlas_tmp_name
            atlas_image.save(atlas_tmp_path, format="PNG")

            atlas_io = io.BytesIO()
            atlas_image.save(atlas_io, format="PNG")
            atlas_bytes = atlas_io.getvalue()
            atlas_state_meta["atlas"]["byteSize"] = len(atlas_bytes)
            atlas_state_meta["atlas"]["tmpFile"] = str(atlas_tmp_path)
            atlas_state_meta["atlas"]["optimizedBy"] = None
            atlas_state_meta["storage"] = "atlas"

            for frame_meta, trim_info in zip(atlas_state_meta["frames"], trim_infos):
                frame_meta.update(trim_info)

        chosen_storage = size_mode
        if (force_raw_by_format or force_raw_by_size) and size_mode in {"auto", "atlas"}:
            chosen_storage = "raw"
        elif size_mode == "auto" and atlas_bytes is not None:
            atlas_packed = _packed_chunk_size([atlas_bytes])
            raw_packed = _packed_chunk_size(raw_frame_bytes)
            chosen_storage = "raw" if raw_packed < atlas_packed else "atlas"

        if chosen_storage == "raw":
            visual_chunks = raw_frame_bytes
            state_meta = raw_state_meta
            storage_note = "raw-frames"
        else:
            if atlas_bytes is None or atlas_state_meta is None:
                raise ValueError(f"状态 {state_name} 未生成 atlas 数据，无法使用 atlas 存储")
            visual_chunks = [atlas_bytes]
            state_meta = atlas_state_meta
            storage_note = "atlas"

        bgm_path = bgm_mapping.get(state_name)
        bgm_bytes: Optional[bytes] = None
        bgm_meta: Optional[Dict[str, Any]] = None
        if bgm_path is not None:
            bgm_bytes = bgm_path.read_bytes()
            codec = bgm_path.suffix.lower().lstrip(".")
            bgm_meta = {
                "codec": codec,
                "byteSize": len(bgm_bytes),
                "fileName": bgm_path.name,
            }
        state_meta["bgm"] = bgm_meta
        asset = {
            "name": state_name,
            "visualChunks": visual_chunks,
            "storage": state_meta.get("storage", "atlas"),
            "bgmBytes": bgm_bytes,
            "meta": state_meta,
            "atlasTmpPath": str(atlas_tmp_path) if atlas_tmp_path is not None else "raw-inline",
            "storageNote": storage_note,
        }
        return state_idx, asset

    state_assets: List[Optional[Dict[str, Any]]] = [None] * len(state_jobs)
    if workers == 1 or len(state_jobs) <= 1:
        for job in state_jobs:
            idx, asset = _build_state_asset(workers, job)
            state_assets[idx] = asset
    else:
        max_workers = min(workers, len(state_jobs))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 以线程池方式并发处理状态资产构建，适合 I/O 密集型任务（如图像处理和文件读写）
            # 外层已经应用了并发，_build_state_asset内部不再使用多线程，避免过度并发导致性能下降，因此workers设为1
            future_map = {executor.submit(_build_state_asset, 1, job): job[0] for job in state_jobs}
            for future in concurrent.futures.as_completed(future_map):
                idx, asset = future.result()
                state_assets[idx] = asset

    finalized_state_assets: List[Dict[str, Any]] = []
    for asset in state_assets:
        if asset is None:
            raise RuntimeError("状态并发处理异常：存在未完成的状态资产")
        finalized_state_assets.append(asset)

    print(f"[ani2dEncode] 状态帧数据处理完成，开始生成 .a2d 包装文件...")

    package_meta = {
        "type": "a2d",
        "version": VERSION,
        "packing": {
            "alignment": ALIGNMENT,
            "layout": "header+json+state_chunks(visual+optional_bgm)",
        },
        "fps": int(fps),
        "sizeMode": size_mode,
        "trimTransparent": bool(trim_transparent),
        "atlasOptimize": atlas_optimize,
        "stateCount": len(finalized_state_assets),
        "totalFrameCount": total_frames,
        "states": [asset["meta"] for asset in finalized_state_assets],
    }

    json_text = json.dumps(package_meta, ensure_ascii=False, indent=2)
    json_bytes = json_text.encode("utf-8")
    json_path.write_text(json_text, encoding="utf-8")

    header = HEADER_STRUCT.pack(MAGIC, VERSION, len(finalized_state_assets), len(json_bytes))

    with a2d_path.open("wb") as f:
        f.write(header)
        f.write(json_bytes)

        json_pad = _align_pad_len(HEADER_STRUCT.size + len(json_bytes))
        if json_pad:
            f.write(b"\x00" * json_pad)

        for asset in finalized_state_assets:
            for visual_chunk in asset["visualChunks"]:
                f.write(visual_chunk)
                chunk_pad = _align_pad_len(len(visual_chunk))
                if chunk_pad:
                    f.write(b"\x00" * chunk_pad)

            bgm_bytes = asset.get("bgmBytes")
            if bgm_bytes:
                f.write(bgm_bytes)
                bgm_pad = _align_pad_len(len(bgm_bytes))
                if bgm_pad:
                    f.write(b"\x00" * bgm_pad)

    print(f"[ani2dEncode] json : {json_path}")
    for asset in finalized_state_assets:
        print(f"[ani2dEncode] state {asset['storageNote']} ({asset['name']}): {asset['atlasTmpPath']}")
        if asset.get("bgmBytes") is not None:
            print(f"[ani2dEncode] state bgm   ({asset['name']}): {asset['meta']['bgm']['fileName']}")
    print(f"[ani2dEncode] a2d : {a2d_path}")
    return a2d_path


def ani2dEncode(
    input_imgs: List[str],
    base_dir: Path,
    state_names_raw: Optional[str] = None,
    bgms_raw: Optional[str] = None,
    ani_file: Optional[str] = None,
    size_mode: str = "auto",
    atlas_optimize: str = "auto",
    trim_transparent: bool = True,
    fps: int = 10,
    durations_ms: Optional[List[int]] = None,
    padding: int = 0,
    max_atlas_width: Optional[int] = None,
    max_atlas_height: Optional[int] = None,
    raw_force_threshold_mb: float = RAW_FORCE_THRESHOLD_MB_DEFAULT,
    raw_frame_format: str = "png",
    raw_webp_quality: int = 80,
    raw_webp_lossless: bool = False,
    workers: int = 1,
) -> Path:
    return _ani2dEncode(
        input_imgs=input_imgs,
        base_dir=base_dir,
        state_names_raw=state_names_raw,
        bgms_raw=bgms_raw,
        ani_file=ani_file,
        size_mode=size_mode,
        atlas_optimize=atlas_optimize,
        trim_transparent=trim_transparent,
        fps=fps,
        durations_ms=durations_ms,
        padding=padding,
        max_atlas_width=max_atlas_width,
        max_atlas_height=max_atlas_height,
        raw_force_threshold_mb=raw_force_threshold_mb,
        raw_frame_format=raw_frame_format,
        raw_webp_quality=raw_webp_quality,
        raw_webp_lossless=raw_webp_lossless,
        workers=workers,
    )


def _apply_vertical_alpha_fade(
    image: Image.Image,
    top_ratio: float = 0.2,
    bottom_ratio: float = 0.2,
) -> Image.Image:
    """对 RGBA 图像上下区域增加透明度，越靠近边缘透明度越高。"""
    rgba = image.convert("RGBA")
    w, h = rgba.size
    if h <= 1:
        return rgba

    top_h = max(1, int(round(h * top_ratio)))
    bottom_h = max(1, int(round(h * bottom_ratio)))

    px = rgba.load()
    for y in range(h):
        if y < top_h:
            factor = y / float(top_h)
        elif y >= h - bottom_h:
            factor = (h - 1 - y) / float(bottom_h)
        else:
            factor = 1.0

        if factor < 0.0:
            factor = 0.0
        elif factor > 1.0:
            factor = 1.0

        for x in range(w):
            r, g, b, a = px[x, y]
            px[x, y] = (r, g, b, int(a * factor))
    return rgba


def _extract_audio_from_video(video_path: Path, out_dir: Path) -> Optional[Path]:
    """尽可能从视频中提取音频，优先使用 ffmpeg。"""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        print("[convert_from_video] 未找到 ffmpeg，跳过音频保留")
        return None

    out_audio = out_dir / f"{video_path.stem}_audio.aac"
    cmd = [
        ffmpeg_path,
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "aac",
        "-b:a",
        "192k",
        str(out_audio),
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode == 0 and out_audio.exists() and out_audio.stat().st_size > 0:
        print(f"[convert_from_video] 提取音频: {out_audio}")
        return out_audio

    print("[convert_from_video] 音频提取失败，继续仅视频帧转码")
    return None


def convert_from_video(
    video_path: str,
    base_dir: Path,
    ani_file: Optional[str] = None,
    raw_force_threshold_mb: float = RAW_FORCE_THRESHOLD_MB_DEFAULT,
) -> Path:
    """
    将视频转换为 a2d:
    1) 抽帧（每秒最多 20 帧）
    2) 每帧转 RGBA PNG，并对 top20%/bottom20% 做透明渐变
    3) 使用内部 _ani2dEncode 生成 a2d，尽可能保留音频
    """
    try:
        import cv2
    except Exception as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError("convert_from_video 需要依赖: pip install opencv-python") from exc

    src_video = Path(video_path).expanduser().resolve()
    if not src_video.exists():
        raise FileNotFoundError(f"视频文件不存在: {src_video}")

    tmp_root = base_dir / "tmp"
    work_dir = tmp_root / f"video_frames_{uuid.uuid4()}"
    work_dir.mkdir(parents=True, exist_ok=True)

    cap = cv2.VideoCapture(str(src_video))
    if not cap.isOpened():
        raise RuntimeError(f"无法打开视频: {src_video}")

    src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    if src_fps <= 0:
        src_fps = 25.0
    target_fps = min(10.0, src_fps)
    frame_interval = 1.0 / target_fps

    use_webp = _webp_supported()
    if use_webp:
        frame_ext = "webp"
        print("[convert_from_video] 使用 WebP(含 alpha) 作为中间帧格式")
    else:
        frame_ext = "png"
        print("[convert_from_video] Pillow 不支持 WebP，回退为优化PNG帧")

    frame_paths: List[str] = []
    frame_idx = 0
    out_idx = 0
    next_sample_t = 0.0

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok:
                break

            current_t = frame_idx / src_fps
            frame_idx += 1

            if current_t + 1e-9 < next_sample_t:
                continue

            frame_rgba = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGBA)
            frame_img = Image.fromarray(frame_rgba, mode="RGBA")
            frame_img = _apply_vertical_alpha_fade(frame_img, top_ratio=0.2, bottom_ratio=0.2)
            if not use_webp:
                frame_img = _optimize_png_fallback(frame_img)

            out_path = work_dir / f"default_{out_idx:06d}.{frame_ext}"
            if use_webp:
                frame_img.save(out_path, format="WEBP", quality=80, lossless=False, method=6)
            else:
                frame_img.save(out_path, format="PNG", optimize=True, compress_level=9)
            frame_paths.append(str(out_path))

            out_idx += 1
            next_sample_t += frame_interval
    finally:
        cap.release()

    if not frame_paths:
        raise RuntimeError("视频抽帧失败，未生成任何帧")

    audio_file = _extract_audio_from_video(src_video, work_dir)
    bgms_raw = f"default:{audio_file}" if audio_file is not None else None

    encode_fps = max(1, int(round(target_fps)))
    out_a2d = _ani2dEncode(
        input_imgs=frame_paths,
        base_dir=base_dir,
        state_names_raw="default",
        bgms_raw=bgms_raw,
        ani_file=ani_file,
        size_mode="auto",
        atlas_optimize="auto",
        trim_transparent=True,
        fps=encode_fps,
        durations_ms=None,
        padding=0,
        max_atlas_width=None,
        max_atlas_height=None,
        raw_force_threshold_mb=raw_force_threshold_mb,
        raw_frame_format="webp" if use_webp else "png",
        raw_webp_quality=80,
        raw_webp_lossless=False,
    )

    print(f"[convert_from_video] video: {src_video}")
    print(f"[convert_from_video] sampled frames: {len(frame_paths)}, fps: {target_fps:.2f}")
    print(f"[convert_from_video] a2d: {out_a2d}")
    return out_a2d


def _read_ani2d(ani_file: Path) -> Ani2dData:
    if not ani_file.exists():
        raise FileNotFoundError(f".a2d 文件不存在: {ani_file}")

    raw = ani_file.read_bytes()
    if len(raw) < HEADER_STRUCT.size:
        raise ValueError("非法 .a2d: 头部长度不足")

    magic, version, state_count, json_size = HEADER_STRUCT.unpack_from(raw, 0)
    if magic != MAGIC:
        raise ValueError("非法 .a2d: MAGIC 不匹配")
    if version != VERSION:
        raise ValueError(f"不支持的版本: {version}，当前仅支持 {VERSION}")

    offset = HEADER_STRUCT.size
    json_end = offset + json_size
    if json_end > len(raw):
        raise ValueError("非法 .a2d: JSON 长度不完整")

    json_bytes = raw[offset:json_end]
    meta = json.loads(json_bytes.decode("utf-8"))

    states_meta = meta.get("states", [])
    if len(states_meta) != int(state_count):
        raise ValueError("非法 .a2d: header 与 json 的 stateCount 不一致")

    offset = json_end
    offset += _align_pad_len(offset)

    states: Dict[str, Ani2dStateData] = {}
    for st in states_meta:
        st_name = str(st.get("name", "default"))
        storage = str(st.get("storage", "atlas"))
        frames = st.get("frames", [])

        atlas_img: Optional[Image.Image] = None
        raw_frame_images: Optional[List[Image.Image]] = None

        if storage == "raw":
            raw_frame_images = []
            for frame in frames:
                frame_size = int(frame.get("byteSize", 0))
                if frame_size <= 0:
                    raise ValueError(f"非法 .a2d: 状态 {st_name} 的 raw frame byteSize 无效")
                end = offset + frame_size
                if end > len(raw):
                    raise ValueError(f"非法 .a2d: 状态 {st_name} 的 raw frame 数据不完整")
                frame_bytes = raw[offset:end]
                try:
                    raw_frame_images.append(Image.open(io.BytesIO(frame_bytes)).convert("RGBA"))
                except Exception as exc:
                    fmt = str(frame.get("format", "unknown"))
                    raise ValueError(
                        f"非法 .a2d: 状态 {st_name} 的 raw frame 解码失败(index={len(raw_frame_images)}, format={fmt})"
                    ) from exc
                offset = end
                offset += _align_pad_len(frame_size)
        else:
            atlas_meta = st.get("atlas", {})
            byte_size = int(atlas_meta.get("byteSize", 0))
            if byte_size <= 0:
                raise ValueError(f"非法 .a2d: 状态 {st_name} 的 atlas byteSize 无效")

            end = offset + byte_size
            if end > len(raw):
                raise ValueError(f"非法 .a2d: 状态 {st_name} 的 atlas 数据不完整")

            atlas_bytes = raw[offset:end]
            atlas_img = Image.open(io.BytesIO(atlas_bytes)).convert("RGBA")
            offset = end
            offset += _align_pad_len(byte_size)

        bgm_bytes: Optional[bytes] = None
        bgm_codec: Optional[str] = None
        bgm_file_name: Optional[str] = None
        bgm_meta = st.get("bgm")
        if isinstance(bgm_meta, dict):
            bgm_size = int(bgm_meta.get("byteSize", 0))
            if bgm_size > 0:
                bgm_end = offset + bgm_size
                if bgm_end > len(raw):
                    raise ValueError(f"非法 .a2d: 状态 {st_name} 的 bgm 数据不完整")
                bgm_bytes = raw[offset:bgm_end]
                bgm_codec = str(bgm_meta.get("codec", "")).strip() or None
                bgm_file_name = str(bgm_meta.get("fileName", "")).strip() or None
                offset = bgm_end
                offset += _align_pad_len(bgm_size)

        states[st_name] = Ani2dStateData(
            name=st_name,
            storage=storage,
            atlas_image=atlas_img,
            raw_frames=raw_frame_images,
            frames=frames,
            bgm_data=bgm_bytes,
            bgm_codec=bgm_codec,
            bgm_file_name=bgm_file_name,
        )

    return Ani2dData(meta=meta, states=states)


def ani2dDecode(
    ani_file: str,
    base_dir: Path,
    export_frames: bool = False,
) -> Dict[str, Any]:
    ani_path = Path(ani_file).expanduser().resolve()
    data = _read_ani2d(ani_path)

    unique_id = str(uuid.uuid4())
    tmp_dir = base_dir / "tmp"
    ensure_parent(tmp_dir / "placeholder")

    json_out = tmp_dir / f"decoded_{unique_id}.json"
    json_out.write_text(json.dumps(data.meta, ensure_ascii=False, indent=2), encoding="utf-8")

    state_atlas_paths: Dict[str, str] = {}
    state_bgm_paths: Dict[str, str] = {}
    for state_name, st_data in data.states.items():
        if st_data.storage == "atlas" and st_data.atlas_image is not None:
            atlas_out = tmp_dir / f"decoded_{unique_id}_{_state_dir_name(state_name)}.png"
            st_data.atlas_image.save(atlas_out, format="PNG")
            state_atlas_paths[state_name] = str(atlas_out)

        if st_data.bgm_data is not None:
            ext = st_data.bgm_codec or "mp3"
            bgm_out = tmp_dir / f"decoded_{unique_id}_{_state_dir_name(state_name)}.{ext}"
            bgm_out.write_bytes(st_data.bgm_data)
            state_bgm_paths[state_name] = str(bgm_out)

    result: Dict[str, Any] = {
        "json": str(json_out),
        "stateCount": len(data.states),
        "totalFrameCount": data.meta.get("totalFrameCount", 0),
        "stateAtlases": state_atlas_paths,
        "stateBgms": state_bgm_paths,
    }

    if export_frames:
        frames_dir = tmp_dir / f"decoded_frames_{unique_id}"
        frames_dir.mkdir(parents=True, exist_ok=True)
        exported = _export_frames(data, frames_dir)
        result["framesDir"] = str(frames_dir)
        result["frames"] = exported

    print(f"[ani2dDecode] json : {result['json']}")
    for st, p in state_atlas_paths.items():
        print(f"[ani2dDecode] state atlas ({st}): {p}")
    for st, p in state_bgm_paths.items():
        print(f"[ani2dDecode] state bgm   ({st}): {p}")
    if export_frames:
        print(f"[ani2dDecode] frames: {result['framesDir']}")

    return result


def _export_frames(data: Ani2dData, frames_dir: Path) -> List[str]:
    out_files: List[str] = []

    for state_name, st_data in data.states.items():
        state_dir = frames_dir / _state_dir_name(state_name)
        state_dir.mkdir(parents=True, exist_ok=True)

        if st_data.storage == "raw":
            raw_frames = st_data.raw_frames or []
            for idx, frame_img in enumerate(raw_frames):
                frame_meta = st_data.frames[idx] if idx < len(st_data.frames) else {}
                name = frame_meta.get("name") or f"frame_{idx:04d}.png"
                out_path = state_dir / name
                if out_path.exists():
                    out_path = state_dir / f"{idx:04d}_{name}"
                restored = _restore_trimmed_frame(frame_img, frame_meta)
                restored.save(out_path, format="PNG")
                out_files.append(str(out_path))
            continue

        for frame in st_data.frames:
            if st_data.atlas_image is None:
                continue
            x = int(frame["x"])
            y = int(frame["y"])
            w = int(frame["w"])
            h = int(frame["h"])
            idx = int(frame.get("index", len(out_files)))
            name = frame.get("name") or f"frame_{idx:04d}.png"

            crop = st_data.atlas_image.crop((x, y, x + w, y + h))
            restored = _restore_trimmed_frame(crop, frame)
            out_path = state_dir / name
            if out_path.exists():
                out_path = state_dir / f"{idx:04d}_{name}"
            restored.save(out_path, format="PNG")
            out_files.append(str(out_path))

    return out_files


def _resolve_play_state(data: Ani2dData, state_name: Optional[str]) -> Ani2dStateData:
    if not data.states:
        raise ValueError(".a2d 中没有状态数据")

    if state_name is None:
        first_state = next(iter(data.states.keys()))
        return data.states[first_state]

    if state_name not in data.states:
        available = ", ".join(data.states.keys())
        raise ValueError(f"状态不存在: {state_name}，可选: {available}")
    return data.states[state_name]


def playAni2d(
    ani_file: str,
    fps: Optional[int] = None,
    debug_save_frames: bool = False,
    base_dir: Optional[Path] = None,
    render_mode: str = "qt_transparent",
    play_once: bool = False,
    state_name: Optional[str] = None,
) -> None:
    if fps is not None and fps <= 0:
        raise ValueError("fps 必须大于 0")

    data = _read_ani2d(Path(ani_file).expanduser().resolve())
    st_data = _resolve_play_state(data, state_name)

    if not st_data.frames:
        raise ValueError(f"状态 {st_data.name} 没有可播放帧")
    if render_mode not in {"canvas", "label", "opencv", "qt_transparent"}:
        raise ValueError("render_mode 仅支持: canvas, label, opencv, qt_transparent")

    rgba_frames: List[Image.Image] = []
    rgb_frames: List[Image.Image] = []
    frame_delays_ms: List[int] = []

    fallback_fps = int(data.meta.get("fps", 10))
    if fallback_fps <= 0:
        fallback_fps = 10
    default_delay = max(1, int(round(1000 / fallback_fps)))

    max_w = 1
    max_h = 1

    if st_data.storage == "raw":
        raw_frames = st_data.raw_frames or []
        for idx, raw_frame in enumerate(raw_frames):
            frame_meta = st_data.frames[idx] if idx < len(st_data.frames) else {}
            restored = _restore_trimmed_frame(raw_frame, frame_meta)
            rgba_frames.append(restored)
            rgb_frames.append(restored.convert("RGB"))
            w, h = restored.size

            if w > max_w:
                max_w = w
            if h > max_h:
                max_h = h

            if fps is not None:
                frame_delays_ms.append(max(1, int(round(1000 / fps))))
            else:
                frame_delays_ms.append(int(frame_meta.get("durationMs", default_delay)))
    else:
        if st_data.atlas_image is None:
            raise ValueError(f"状态 {st_data.name} 缺少 atlas 数据")
        for frame in st_data.frames:
            x = int(frame["x"])
            y = int(frame["y"])
            w = int(frame["w"])
            h = int(frame["h"])

            cropped = st_data.atlas_image.crop((x, y, x + w, y + h))
            restored = _restore_trimmed_frame(cropped, frame)
            rgba_frames.append(restored)
            rgb_frames.append(restored.convert("RGB"))

            if restored.width > max_w:
                max_w = restored.width
            if restored.height > max_h:
                max_h = restored.height

            if fps is not None:
                frame_delays_ms.append(max(1, int(round(1000 / fps))))
            else:
                frame_delays_ms.append(int(frame.get("durationMs", default_delay)))

    print(f"[playAni2d] render mode: {render_mode}")
    print(f"[playAni2d] state: {st_data.name}")
    print(f"[playAni2d] frame count: {len(st_data.frames)}")

    bgm_process: Optional[subprocess.Popen[Any]] = None
    bgm_temp_file: Optional[Path] = None

    if st_data.bgm_data is not None:
        codec = (st_data.bgm_codec or "mp3").lower()
        suffix = ".aac" if codec == "aac" else ".mp3"
        tmp_root = (base_dir or Path(__file__).resolve().parent) / "tmp"
        tmp_root.mkdir(parents=True, exist_ok=True)
        bgm_temp_file = tmp_root / f"play_bgm_{st_data.name}_{uuid.uuid4()}{suffix}"
        bgm_temp_file.write_bytes(st_data.bgm_data)

        if sys.platform == "darwin" and shutil.which("afplay"):
            bgm_process = subprocess.Popen(["afplay", str(bgm_temp_file)])
            print(f"[playAni2d] bgm: {st_data.bgm_file_name or bgm_temp_file.name}")
        elif shutil.which("ffplay"):
            bgm_process = subprocess.Popen([
                "ffplay",
                "-nodisp",
                "-autoexit",
                "-loglevel",
                "quiet",
                str(bgm_temp_file),
            ])
            print(f"[playAni2d] bgm: {st_data.bgm_file_name or bgm_temp_file.name}")
        else:
            print("[playAni2d] bgm 存在，但未找到 afplay/ffplay，跳过音频播放")

    def _cleanup_bgm() -> None:
        if bgm_process is not None and bgm_process.poll() is None:
            bgm_process.terminate()
        if bgm_temp_file is not None and bgm_temp_file.exists():
            bgm_temp_file.unlink(missing_ok=True)

    if debug_save_frames:
        output_root = (base_dir or Path(__file__).resolve().parent) / "tmp"
        debug_dir = output_root / f"debug_play_frames_{uuid.uuid4()}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_source = rgba_frames if render_mode == "qt_transparent" else rgb_frames
        for i, img in enumerate(debug_source):
            img.save(debug_dir / f"frame_{i:04d}.png", format="PNG")
        print(f"[playAni2d] debug frames: {debug_dir}")

    if render_mode == "opencv":
        try:
            import cv2
            import numpy as np
        except Exception as exc:  # pragma: no cover - runtime dependency check
            raise RuntimeError("opencv 模式需要依赖: pip install opencv-python numpy") from exc

        window_name = f"A2D Player (OpenCV) - {st_data.name}"
        print("[playAni2d] OpenCV: 按 q 或 Esc 退出")

        try:
            cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
            idx = 0
            while True:
                frame_bgr = cv2.cvtColor(np.array(rgb_frames[idx]), cv2.COLOR_RGB2BGR)
                cv2.imshow(window_name, frame_bgr)

                if play_once and idx == len(rgb_frames) - 1:
                    while True:
                        key_hold = cv2.waitKey(30) & 0xFF
                        if key_hold in (27, ord("q")):
                            return

                key = cv2.waitKey(max(1, frame_delays_ms[idx])) & 0xFF
                if key in (27, ord("q")):
                    return

                idx = (idx + 1) % len(rgb_frames)
        finally:
            cv2.destroyAllWindows()
            _cleanup_bgm()
        return

    if render_mode == "qt_transparent":
        try:
            from PySide6.QtCore import QTimer, Qt
            from PySide6.QtGui import QGuiApplication, QImage, QKeyEvent, QPixmap
            from PySide6.QtWidgets import QApplication, QLabel, QWidget
        except Exception as exc:  # pragma: no cover - runtime dependency check
            raise RuntimeError("qt_transparent 模式需要依赖: pip install PySide6") from exc

        app = QApplication.instance() or QApplication(sys.argv[:1])

        class TransparentPlayer(QWidget):
            def __init__(self) -> None:
                super().__init__()
                self._idx = 0
                self._label = QLabel(self)
                self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._last_pixmap: Optional[QPixmap] = None

                self.setWindowTitle(f"A2D Player (Qt Transparent) - {st_data.name}")
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
                self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                )
                self.resize(max_w, max_h)
                self._label.resize(max_w, max_h)

            def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
                if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Q):
                    self.close()
                    return
                super().keyPressEvent(event)

            def closeEvent(self, event: Any) -> None:  # noqa: N802
                QGuiApplication.quit()
                super().closeEvent(event)

            def _show_frame(self, idx: int) -> None:
                frame = rgba_frames[idx]
                w, h = frame.size
                raw = frame.tobytes("raw", "RGBA")
                qimg = QImage(raw, w, h, w * 4, QImage.Format.Format_RGBA8888)
                pix = QPixmap.fromImage(qimg.copy())
                self._last_pixmap = pix

                self._label.setPixmap(pix)
                self._label.resize(w, h)
                self._label.move((self.width() - w) // 2, (self.height() - h) // 2)

            def tick(self) -> None:
                i = self._idx
                self._show_frame(i)

                if play_once and i == len(rgba_frames) - 1:
                    return

                self._idx = (i + 1) % len(rgba_frames)
                QTimer.singleShot(max(1, frame_delays_ms[i]), self.tick)

        player = TransparentPlayer()
        print("[playAni2d] Qt Transparent: 按 q 或 Esc 退出")
        player.show()
        player.tick()
        app.exec()
        _cleanup_bgm()
        return

    try:
        import tkinter as tk
    except Exception as exc:  # pragma: no cover - runtime dependency check
        raise RuntimeError("当前 Python 环境不可用 tkinter，无法播放") from exc

    root = tk.Tk()
    root.title(f"A2D Player - {st_data.name}")
    root.configure(bg="#111")

    canvas_w = max_w + 32
    canvas_h = max_h + 32
    root.geometry(f"{canvas_w}x{canvas_h}")

    canvas: Any = None
    label: Any = None
    if render_mode == "canvas":
        canvas = tk.Canvas(
            root,
            width=canvas_w,
            height=canvas_h,
            bg="#111",
            highlightthickness=0,
            bd=0,
        )
        canvas.pack(fill="both", expand=True)
    else:
        frame = tk.Frame(root, bg="#111")
        frame.pack(fill="both", expand=True)
        label = tk.Label(frame, bg="#111", bd=0, highlightthickness=0)
        label.place(relx=0.5, rely=0.5, anchor="center")

    frame_idx = {"value": 0}
    render_state: Dict[str, Any] = {"photo": None, "item": None}

    def tick() -> None:
        i = frame_idx["value"]

        photo = ImageTk.PhotoImage(rgb_frames[i], master=root)
        render_state["photo"] = photo

        if render_mode == "canvas":
            if render_state["item"] is None:
                render_state["item"] = canvas.create_image(
                    canvas_w // 2,
                    canvas_h // 2,
                    image=photo,
                    anchor="center",
                )
            else:
                canvas.itemconfig(render_state["item"], image=photo)
        else:
            label.configure(image=photo)
            label.image = photo

        if play_once and i == len(rgb_frames) - 1:
            return

        frame_idx["value"] = (i + 1) % len(rgb_frames)
        root.after(max(1, frame_delays_ms[i]), tick)

    root.after(0, tick)
    try:
        root.mainloop()
    finally:
        _cleanup_bgm()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ANI2D 编解码与播放工具")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_cvrtvd = subparsers.add_parser("cvrtvd", help="从视频抽帧并转换为 .a2d")
    p_cvrtvd.add_argument(
        "--videoPath",
        required=True,
        help="输入视频路径",
    )
    p_cvrtvd.add_argument(
        "--aniFile",
        default=None,
        help="可选: 输出 .a2d 文件路径；未传时默认 output/out.a2d",
    )
    p_cvrtvd.add_argument(
        "--rawForceThresholdMB",
        type=float,
        default=RAW_FORCE_THRESHOLD_MB_DEFAULT,
        help="当状态 PNG 序列总大小超过该阈值(MB)时强制使用 raw 存储，默认 50",
    )

    p_encode = subparsers.add_parser("encode", help="将 PNG 序列编码为 out.a2d")
    p_encode.add_argument(
        "--inputImgs",
        nargs="+",
        required=True,
        help=(
            "输入 PNG 序列。单状态: 直接传多张图; 多状态: 每个参数对应一个状态并用逗号分隔"
        ),
    )
    p_encode.add_argument(
        "--stateNames",
        default=None,
        help=(
            "状态名列表(逗号分隔)，例如 idle,run。"
            "多状态时 --inputImgs 数量需与状态数量一致，且每项是该状态的逗号分隔序列"
        ),
    )
    p_encode.add_argument(
        "--bgms",
        default=None,
        help=(
            "可选: 按状态配置 bgm，格式 state1:path1;state2:path2。"
            "仅支持 mp3/aac"
        ),
    )
    p_encode.add_argument(
        "--aniFile",
        default=None,
        help="可选: encode 输出 .a2d 文件路径；未传时默认 output/out.a2d",
    )
    p_encode.add_argument(
        "--sizeMode",
        choices=["auto", "atlas", "raw"],
        default="auto",
        help="状态图像存储模式: auto(按状态自动择优)/atlas/raw，默认 auto",
    )
    p_encode.add_argument(
        "--atlasOptimize",
        choices=["auto", "none", "pngquant"],
        default="auto",
        help="atlas PNG 优化方式: auto(有 pngquant 则尝试)/none/pngquant，默认 auto",
    )
    p_encode.add_argument(
        "--noTrimTransparent",
        action="store_true",
        help="关闭透明边界裁剪；默认开启裁剪并在播放/导出时还原原尺寸",
    )
    p_encode.add_argument("--fps", type=int, default=10, help="默认帧率，默认 10")
    p_encode.add_argument(
        "--padding",
        type=int,
        default=0,
        help="可选: 每帧四周留白像素，用于抗采样串色，默认 0",
    )
    p_encode.add_argument(
        "--maxAtlasWidth",
        type=int,
        default=None,
        help="可选: 单个 state atlas 最大宽度限制(像素)",
    )
    p_encode.add_argument(
        "--maxAtlasHeight",
        type=int,
        default=None,
        help="可选: 单个 state atlas 最大高度限制(像素)",
    )
    p_encode.add_argument(
        "--durationsMs",
        nargs="+",
        type=int,
        help="逐帧时长(毫秒)，数量需与总帧数一致(多状态时按状态顺序展开)",
    )
    p_encode.add_argument(
        "--rawForceThresholdMB",
        type=float,
        default=RAW_FORCE_THRESHOLD_MB_DEFAULT,
        help="当状态 PNG 序列总大小超过该阈值(MB)时强制使用 raw 存储，默认 50",
    )
    p_encode.add_argument(
        "--rawFrameFormat",
        choices=["png", "webp"],
        default="png",
        help="raw 存储时单帧编码格式，默认 png",
    )
    p_encode.add_argument(
        "--rawWebpQuality",
        type=int,
        default=80,
        help="rawFrameFormat=webp 时的质量(1-100)，默认 80",
    )
    p_encode.add_argument(
        "--rawWebpLossless",
        action="store_true",
        help="rawFrameFormat=webp 时启用无损压缩",
    )
    p_encode.add_argument(
        "--workers",
        type=int,
        default=4,
        help="状态处理并发线程数；<=0 时自动取 min(state数, CPU核数)，默认 4",
    )

    p_decode = subparsers.add_parser("decode", help="从 .a2d 解码图集与配置")
    p_decode.add_argument(
        "--aniFile",
        default="ani2d/output/out.a2d",
        help="输入 .a2d 文件路径",
    )
    p_decode.add_argument(
        "--exportFrames",
        action="store_true",
        help="是否将原始帧导出为独立 PNG",
    )

    p_play = subparsers.add_parser("play", help="播放 .a2d 动画")
    p_play.add_argument(
        "--aniFile",
        default="ani2d/output/out.a2d",
        help="输入 .a2d 文件路径",
    )
    p_play.add_argument(
        "--fps",
        type=int,
        default=None,
        help="可选: 覆盖文件中的逐帧时长，强制按统一帧率播放",
    )
    p_play.add_argument(
        "--debugSaveFrames",
        action="store_true",
        help="调试开关: 将播放前的实际帧导出到 ani2d/tmp 目录",
    )
    p_play.add_argument(
        "--renderMode",
        choices=["canvas", "label", "opencv", "qt_transparent"],
        default="qt_transparent",
        help="渲染模式: canvas、label、opencv 或 qt_transparent，默认 qt_transparent",
    )
    p_play.add_argument(
        "--playOnce",
        action="store_true",
        help="播放一轮后停留在最后一帧(不循环)",
    )
    p_play.add_argument(
        "--stateName",
        default=None,
        help="可选: 指定播放的状态名。若不传则播放首个状态",
    )

    return parser


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    base_dir = Path(__file__).resolve().parent

    if args.command == "cvrtvd":
        convert_from_video(
            video_path=args.videoPath,
            base_dir=base_dir,
            ani_file=args.aniFile,
            raw_force_threshold_mb=args.rawForceThresholdMB,
        )
        return 0

    if args.command == "encode":
        ani2dEncode(
            args.inputImgs,
            base_dir,
            state_names_raw=args.stateNames,
            bgms_raw=args.bgms,
            ani_file=args.aniFile,
            size_mode=args.sizeMode,
            atlas_optimize=args.atlasOptimize,
            trim_transparent=not args.noTrimTransparent,
            fps=args.fps,
            durations_ms=args.durationsMs,
            padding=args.padding,
            max_atlas_width=args.maxAtlasWidth,
            max_atlas_height=args.maxAtlasHeight,
            raw_force_threshold_mb=args.rawForceThresholdMB,
            raw_frame_format=args.rawFrameFormat,
            raw_webp_quality=args.rawWebpQuality,
            raw_webp_lossless=args.rawWebpLossless,
            workers=args.workers,
        )
        return 0

    if args.command == "decode":
        ani2dDecode(args.aniFile, base_dir, export_frames=args.exportFrames)
        return 0

    if args.command == "play":
        playAni2d(
            args.aniFile,
            fps=args.fps,
            debug_save_frames=args.debugSaveFrames,
            base_dir=base_dir,
            render_mode=args.renderMode,
            play_once=args.playOnce,
            state_name=args.stateName,
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
