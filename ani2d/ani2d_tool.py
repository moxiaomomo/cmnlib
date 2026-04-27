#!/usr/bin/env python3
"""ani2d encoder/decoder/player.

新格式说明 (不兼容旧版本):
1) 每个 stateName 的 inputImgs 单独打包成各自 atlas PNG
2) .a2d 文件按 8 字节对齐组装: header + json + state_png_chunks
3) play 可按 stateName 按需加载并渲染，降低复杂状态机场景下的解码开销
"""

from __future__ import annotations

import argparse
import glob
import io
import json
import re
import shutil
import struct
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageTk
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise SystemExit("缺少 Pillow 依赖，请先安装: pip install pillow") from exc


MAGIC = b"ANI2D"
VERSION = 2
ALIGNMENT = 8
HEADER_STRUCT = struct.Struct("<5sBHI")
# header: magic(5) + version(1) + state_count(uint16) + json_size(uint32)


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
    atlas_image: Image.Image
    frames: List[Dict[str, Any]]
    bgm_data: Optional[bytes] = None
    bgm_codec: Optional[str] = None
    bgm_file_name: Optional[str] = None


@dataclass
class Ani2dData:
    meta: Dict[str, Any]
    states: Dict[str, Ani2dStateData]


def _load_png(path: Path) -> Image.Image:
    if path.suffix.lower() != ".png":
        raise ValueError(f"仅支持 PNG: {path}")
    return Image.open(path).convert("RGBA")


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


def ani2dEncode(
    input_imgs: List[str],
    base_dir: Path,
    state_names_raw: Optional[str] = None,
    bgms_raw: Optional[str] = None,
    fps: int = 10,
    durations_ms: Optional[List[int]] = None,
    padding: int = 0,
    max_atlas_width: Optional[int] = None,
    max_atlas_height: Optional[int] = None,
) -> Path:
    state_names = _parse_state_names(state_names_raw)
    grouped_inputs = _parse_state_input_groups(input_imgs, state_names)
    bgm_mapping = _parse_bgms(bgms_raw, state_names)

    total_frames = sum(len(g) for g in grouped_inputs)
    flat_durations = _normalize_durations(total_frames, fps=fps, durations_ms=durations_ms)

    unique_id = str(uuid.uuid4())
    tmp_dir = base_dir / "tmp"
    out_dir = base_dir / "output"
    json_path = tmp_dir / f"{unique_id}.json"
    a2d_path = out_dir / "out.a2d"
    ensure_parent(json_path)
    ensure_parent(a2d_path)

    duration_offset = 0
    state_assets: List[Dict[str, Any]] = []

    for state_idx, (state_name, state_inputs) in enumerate(zip(state_names, grouped_inputs)):
        img_paths = [Path(p).expanduser().resolve() for p in state_inputs]
        for p in img_paths:
            if not p.exists():
                raise FileNotFoundError(f"输入图片不存在: {p}")

        images = [_load_png(p) for p in img_paths]
        names = [p.name for p in img_paths]

        state_frame_count = len(images)
        state_durations = flat_durations[duration_offset:duration_offset + state_frame_count]
        duration_offset += state_frame_count

        atlas_image, state_meta = _build_single_state_atlas(
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

        state_meta["atlas"]["byteSize"] = len(atlas_bytes)
        state_meta["atlas"]["tmpFile"] = str(atlas_tmp_path)

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

        state_assets.append(
            {
                "name": state_name,
                "atlasImage": atlas_image,
                "atlasBytes": atlas_bytes,
                "bgmBytes": bgm_bytes,
                "meta": state_meta,
                "atlasTmpPath": str(atlas_tmp_path),
            }
        )

    package_meta = {
        "type": "a2d",
        "version": VERSION,
        "packing": {
            "alignment": ALIGNMENT,
            "layout": "header+json+state_chunks(atlas+optional_bgm)",
        },
        "fps": int(fps),
        "stateCount": len(state_assets),
        "totalFrameCount": total_frames,
        "states": [asset["meta"] for asset in state_assets],
    }

    json_text = json.dumps(package_meta, ensure_ascii=False, indent=2)
    json_bytes = json_text.encode("utf-8")
    json_path.write_text(json_text, encoding="utf-8")

    header = HEADER_STRUCT.pack(MAGIC, VERSION, len(state_assets), len(json_bytes))

    with a2d_path.open("wb") as f:
        f.write(header)
        f.write(json_bytes)

        json_pad = _align_pad_len(HEADER_STRUCT.size + len(json_bytes))
        if json_pad:
            f.write(b"\x00" * json_pad)

        for asset in state_assets:
            atlas_bytes = asset["atlasBytes"]
            f.write(atlas_bytes)
            chunk_pad = _align_pad_len(len(atlas_bytes))
            if chunk_pad:
                f.write(b"\x00" * chunk_pad)

            bgm_bytes = asset.get("bgmBytes")
            if bgm_bytes:
                f.write(bgm_bytes)
                bgm_pad = _align_pad_len(len(bgm_bytes))
                if bgm_pad:
                    f.write(b"\x00" * bgm_pad)

    print(f"[ani2dEncode] json : {json_path}")
    for asset in state_assets:
        print(f"[ani2dEncode] state atlas ({asset['name']}): {asset['atlasTmpPath']}")
        if asset.get("bgmBytes") is not None:
            print(f"[ani2dEncode] state bgm   ({asset['name']}): {asset['meta']['bgm']['fileName']}")
    print(f"[ani2dEncode] a2d : {a2d_path}")
    return a2d_path


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

        frames = st.get("frames", [])
        states[st_name] = Ani2dStateData(
            name=st_name,
            atlas_image=atlas_img,
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

        for frame in st_data.frames:
            x = int(frame["x"])
            y = int(frame["y"])
            w = int(frame["w"])
            h = int(frame["h"])
            idx = int(frame.get("index", len(out_files)))
            name = frame.get("name") or f"frame_{idx:04d}.png"

            crop = st_data.atlas_image.crop((x, y, x + w, y + h))
            out_path = state_dir / name
            if out_path.exists():
                out_path = state_dir / f"{idx:04d}_{name}"
            crop.save(out_path, format="PNG")
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

    for frame in st_data.frames:
        x = int(frame["x"])
        y = int(frame["y"])
        w = int(frame["w"])
        h = int(frame["h"])

        cropped = st_data.atlas_image.crop((x, y, x + w, y + h))
        rgba_frames.append(cropped)
        rgb_frames.append(cropped.convert("RGB"))

        if w > max_w:
            max_w = w
        if h > max_h:
            max_h = h

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

    if args.command == "encode":
        ani2dEncode(
            args.inputImgs,
            base_dir,
            state_names_raw=args.stateNames,
            bgms_raw=args.bgms,
            fps=args.fps,
            durations_ms=args.durationsMs,
            padding=args.padding,
            max_atlas_width=args.maxAtlasWidth,
            max_atlas_height=args.maxAtlasHeight,
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
