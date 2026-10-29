import argparse
import hashlib
import io
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from typing import Callable, Dict, List, Optional, Set, Tuple

import cv2


SUPPORTED_FORMATS = ("mp4", "webp", "svga", "png-sequence", "gif", "apng")
Conversion = Callable[..., None]
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _create_frame_directory() -> str:
    script_directory = os.path.dirname(os.path.abspath(__file__))
    return tempfile.mkdtemp(prefix="convertFromVideo-frames-", dir=script_directory)


def _quantize_png8(png_data: bytes) -> bytes:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("PNG8 量化需要 FFmpeg，请先安装 FFmpeg 并加入 PATH")

    result = subprocess.run(
        [
            ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            "pipe:0",
            "-filter_complex",
            "[0:v]split[a][b];"
            "[a]palettegen=max_colors=256:reserve_transparent=1[p];"
            "[b][p]paletteuse=dither=sierra2_4a",
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "pipe:1",
        ],
        input=png_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"PNG8 量化失败: {error or result.returncode}")
    if not result.stdout.startswith(PNG_SIGNATURE):
        raise RuntimeError("FFmpeg PNG8 量化未生成有效 PNG")

    return result.stdout if len(result.stdout) < len(png_data) else png_data


def _second_compress_png(png_data: bytes) -> Tuple[bytes, str]:
    pngquant_path = shutil.which("pngquant")
    if pngquant_path is not None:
        result = subprocess.run(
            [
                pngquant_path,
                "--quality=65-90",
                "--speed",
                "1",
                "--strip",
                "--force",
                "--output",
                "-",
                "-",
            ],
            input=png_data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode not in (0, 98):
            error = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"pngquant 二次压缩失败: {error or result.returncode}")
        compressed = result.stdout
        if not compressed:
            return png_data, "pngquant（无更小结果）"
        if not compressed.startswith(PNG_SIGNATURE):
            raise RuntimeError("pngquant 二次压缩未生成有效 PNG")
        if len(compressed) < len(png_data):
            return compressed, "pngquant"
        return png_data, "pngquant（无更小结果）"
    else:
        print("pngquant 未找到，将使用 Pillow 进行二次压缩")

    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "二次压缩需要安装 pngquant 或 Pillow；可运行 pip install pillow"
        ) from error

    try:
        with Image.open(io.BytesIO(png_data)) as image:
            image.load()
            original_pixels = image.convert("RGBA")
            output = io.BytesIO()
            image.save(output, format="PNG", optimize=True, compress_level=9)
        compressed = output.getvalue()
        if not compressed.startswith(PNG_SIGNATURE):
            raise RuntimeError("Pillow 二次压缩未生成有效 PNG")
        with Image.open(io.BytesIO(compressed)) as optimized_image:
            if optimized_image.size != original_pixels.size:
                raise RuntimeError("Pillow 二次压缩改变了 PNG 尺寸")
            if optimized_image.convert("RGBA").tobytes() != original_pixels.tobytes():
                raise RuntimeError("Pillow 二次压缩改变了 PNG 像素或透明通道")
    except OSError as error:
        raise RuntimeError(f"Pillow 二次压缩失败: {error}") from error

    if len(compressed) < len(png_data):
        return compressed, "Pillow"
    return png_data, "Pillow（无更小结果）"


def _protobuf_varint(value: int) -> bytes:
    encoded = bytearray()
    while value > 0x7F:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _protobuf_bytes_field(field_number: int, value: bytes) -> bytes:
    return (
        _protobuf_varint((field_number << 3) | 2)
        + _protobuf_varint(len(value))
        + value
    )


def _protobuf_float_field(field_number: int, value: float) -> bytes:
    return _protobuf_varint((field_number << 3) | 5) + struct.pack("<f", value)


def _protobuf_int32_field(field_number: int, value: int) -> bytes:
    return _protobuf_varint(field_number << 3) + _protobuf_varint(value)


def _encode_svga_v2(
    width: int,
    height: int,
    fps: int,
    frame_image_names: List[str],
    image_assets: Dict[str, bytes],
) -> bytes:
    layout = b"".join(
        (
            _protobuf_float_field(1, 0),
            _protobuf_float_field(2, 0),
            _protobuf_float_field(3, width),
            _protobuf_float_field(4, height),
        )
    )
    transform = b"".join(
        _protobuf_float_field(number, value)
        for number, value in enumerate((1, 0, 0, 1, 0, 0), start=1)
    )
    visible_frame = b"".join(
        (
            _protobuf_float_field(1, 1),
            _protobuf_bytes_field(2, layout),
            _protobuf_bytes_field(3, transform),
        )
    )
    hidden_frame = b"".join(
        (
            _protobuf_float_field(1, 0),
            _protobuf_bytes_field(2, layout),
            _protobuf_bytes_field(3, transform),
        )
    )

    movie_params = b"".join(
        (
            _protobuf_float_field(1, width),
            _protobuf_float_field(2, height),
            _protobuf_int32_field(3, fps),
            _protobuf_int32_field(4, len(frame_image_names)),
        )
    )
    movie_entity = bytearray()
    movie_entity.extend(_protobuf_bytes_field(1, b"2.0"))
    movie_entity.extend(_protobuf_bytes_field(2, movie_params))

    for image_name, image_data in image_assets.items():
        map_entry = _protobuf_bytes_field(1, image_name.encode("utf-8"))
        map_entry += _protobuf_bytes_field(2, image_data)
        movie_entity.extend(_protobuf_bytes_field(3, map_entry))

    for image_name in dict.fromkeys(frame_image_names):
        sprite = bytearray(_protobuf_bytes_field(1, image_name.encode("utf-8")))
        for frame_image_name in frame_image_names:
            sprite.extend(
                _protobuf_bytes_field(
                    2, visible_frame if frame_image_name == image_name else hidden_frame
                )
            )
        movie_entity.extend(_protobuf_bytes_field(4, bytes(sprite)))

    return zlib.compress(bytes(movie_entity), level=9)


def convert_alpha_mp4_to_svga(
    input_path: str,
    output_path: str,
    alpha_pos: str = "right",
    keep_frames: bool = False,
    png8: bool = True,
    second_compress: bool = False,
) -> None:
    if alpha_pos not in ("left", "right"):
        raise ValueError("alpha_pos 必须是 left 或 right")

    absolute_input = os.path.abspath(input_path)
    absolute_output = os.path.abspath(output_path)
    if absolute_input == absolute_output:
        raise ValueError("输入文件和输出文件不能是同一路径")

    capture = cv2.VideoCapture(input_path)
    if not capture.isOpened():
        raise ValueError(f"无法打开 MP4 文件: {input_path}")

    fps_value = capture.get(cv2.CAP_PROP_FPS)
    fps = max(1, round(fps_value)) if math.isfinite(fps_value) and fps_value > 0 else 30
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    output_directory = os.path.dirname(absolute_output)
    os.makedirs(output_directory, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=".convertFromVideo-", suffix=".tmp", dir=output_directory
    )
    os.close(temp_fd)

    frame_directory: Optional[str] = None
    conversion_succeeded = False
    try:
        width = 0
        height = 0
        frame_count = 0
        frame_image_names: List[str] = []
        encoded_assets: Dict[str, bytes] = {}
        digest_to_name: Dict[str, str] = {}
        second_compress_methods: Set[str] = set()
        if keep_frames:
            frame_directory = _create_frame_directory()
        while True:
            success, frame = capture.read()
            if not success:
                break

            source_width = frame.shape[1]
            split_x = source_width // 2
            if split_x == 0:
                raise ValueError("带通道 MP4 的宽度必须至少为 2 像素")

            left_part = frame[:, :split_x]
            right_part = frame[:, split_x:]
            if alpha_pos == "right":
                rgb_part, alpha_part = left_part, right_part
            else:
                rgb_part, alpha_part = right_part, left_part

            if rgb_part.size == 0 or alpha_part.size == 0:
                raise ValueError("视频帧无法拆分为 RGB 和 Alpha 两部分")

            alpha_channel = cv2.cvtColor(alpha_part, cv2.COLOR_BGR2GRAY)
            rgb_height, rgb_width = rgb_part.shape[:2]
            if frame_count and (rgb_width, rgb_height) != (width, height):
                raise ValueError("视频帧尺寸发生变化，无法生成单尺寸 SVGA")
            if alpha_channel.shape != (rgb_height, rgb_width):
                alpha_channel = cv2.resize(
                    alpha_channel,
                    (rgb_width, rgb_height),
                    interpolation=cv2.INTER_LINEAR,
                )

            bgra_frame = cv2.cvtColor(rgb_part, cv2.COLOR_BGR2BGRA)
            bgra_frame[:, :, 3] = alpha_channel
            encoded, png_data = cv2.imencode(".png", bgra_frame)
            if not encoded:
                raise RuntimeError(f"第 {frame_count} 帧 PNG 编码失败")

            png_bytes = png_data.tobytes()
            if png8:
                png_bytes = _quantize_png8(png_bytes)
            if second_compress:
                png_bytes, method = _second_compress_png(png_bytes)
                second_compress_methods.add(method)
            image_name = f"frame_{frame_count:06d}"
            if frame_directory is not None:
                frame_path = os.path.join(frame_directory, f"{image_name}.png")
                with open(frame_path, "wb") as frame_file:
                    frame_file.write(png_bytes)
            digest = hashlib.sha256(png_bytes).hexdigest()
            encoded_name = digest_to_name.get(digest)
            if encoded_name is None:
                encoded_name = image_name
                digest_to_name[digest] = encoded_name
                encoded_assets[encoded_name] = png_bytes
            frame_image_names.append(encoded_name)
            width, height = rgb_width, rgb_height
            frame_count += 1

        if frame_count == 0:
            raise ValueError(f"MP4 文件中没有可读取的视频帧: {input_path}")

        encoded_movie = _encode_svga_v2(
            width, height, fps, frame_image_names, encoded_assets
        )
        with open(temp_path, "wb") as output_file:
            output_file.write(encoded_movie)

        os.replace(temp_path, absolute_output)
        conversion_succeeded = True
    finally:
        capture.release()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if frame_directory is not None and not conversion_succeeded:
            shutil.rmtree(frame_directory)

    print(
        f"转换完成: {input_path} -> {absolute_output} "
        f"({width}x{height}, {fps} fps, {frame_count}/{expected_frames} 帧)"
    )
    if frame_directory is not None:
        print(f"中间 PNG 序列已保留: {frame_directory}")
    print(f"帧图像格式: {'PNG8 调色板' if png8 else 'RGBA PNG'}")
    print("SVGA 格式: 2.0（zlib 压缩 protobuf）")
    if second_compress:
        print(f"二次压缩: {', '.join(sorted(second_compress_methods))}")


def _parse_bg_color(bg_color: str) -> Tuple[int, int, int]:
    color = bg_color.strip().lstrip("#")
    if len(color) == 3:
        color = "".join(channel * 2 for channel in color)
    if len(color) != 6:
        raise ValueError("bg_color 必须是 #RGB 或 #RRGGBB 格式")
    try:
        red, green, blue = (
            int(color[index : index + 2], 16) for index in (0, 2, 4)
        )
    except ValueError as error:
        raise ValueError("bg_color 必须是 #RGB 或 #RRGGBB 格式") from error
    return blue, green, red


def _key_background(frame, background_bgr: Tuple[int, int, int]):
    difference = cv2.absdiff(frame, background_bgr)
    distance = cv2.max(
        cv2.max(difference[:, :, 0], difference[:, :, 1]), difference[:, :, 2]
    )
    alpha = cv2.convertScaleAbs(cv2.subtract(distance, 16), alpha=255 / 32)
    bgra = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA)
    bgra[:, :, 3] = alpha
    return bgra, alpha


def convert_mp4_to_svga(
    input_path: str,
    output_path: str,
    bg_color: str = "#000000",
    target_fps: int = -1,
    keep_frames: bool = False,
    png8: bool = True,
    second_compress: bool = False,
) -> None:
    """Key out a solid background and encode sampled frames in SVGA 2.0.

    PNG8 quantization is enabled by default. Identical images share one
    embedded image asset while remaining in the timeline.
    """
    if target_fps != -1 and target_fps < 1:
        raise ValueError("target_fps 必须大于 0，或为 -1 表示跟随源视频帧率")

    background_bgr = _parse_bg_color(bg_color)
    absolute_input = os.path.abspath(input_path)
    absolute_output = os.path.abspath(output_path)
    if absolute_input == absolute_output:
        raise ValueError("输入文件和输出文件不能是同一路径")

    capture = cv2.VideoCapture(input_path)
    if not capture.isOpened():
        raise ValueError(f"无法打开 MP4 文件: {input_path}")

    source_fps_value = capture.get(cv2.CAP_PROP_FPS)
    source_fps = (
        source_fps_value
        if math.isfinite(source_fps_value) and source_fps_value > 0
        else 30.0
    )
    if target_fps == -1:
        target_fps = max(1, round(source_fps))
    fps = max(1, min(target_fps, round(source_fps)))
    sample_interval = source_fps / fps
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))

    output_directory = os.path.dirname(absolute_output)
    os.makedirs(output_directory, exist_ok=True)
    temp_fd, temp_path = tempfile.mkstemp(
        prefix=".convertFromVideo-", suffix=".tmp", dir=output_directory
    )
    os.close(temp_fd)

    frame_directory: Optional[str] = None
    conversion_succeeded = False
    try:
        frame_index = 0
        next_sample_index = 0.0
        crop_left: Optional[int] = None
        crop_top: Optional[int] = None
        crop_right = 0
        crop_bottom = 0
        sampled_frame_count = 0
        source_size: Optional[Tuple[int, int]] = None

        while True:
            success, frame = capture.read()
            if not success:
                break
            current_size = (frame.shape[1], frame.shape[0])
            if source_size is None:
                source_size = current_size
            elif current_size != source_size:
                raise ValueError("视频帧尺寸发生变化，无法生成单尺寸 SVGA")

            if frame_index + 1e-9 >= next_sample_index:
                _, alpha = _key_background(frame, background_bgr)
                visible = cv2.threshold(alpha, 16, 255, cv2.THRESH_BINARY)[1]
                points = cv2.findNonZero(visible)
                if points is not None:
                    x, y, width, height = cv2.boundingRect(points)
                    crop_left = x if crop_left is None else min(crop_left, x)
                    crop_top = y if crop_top is None else min(crop_top, y)
                    crop_right = max(crop_right, x + width)
                    crop_bottom = max(crop_bottom, y + height)
                sampled_frame_count += 1
                next_sample_index += sample_interval
            frame_index += 1

        if sampled_frame_count == 0:
            raise ValueError(f"MP4 文件中没有可读取的视频帧: {input_path}")
        if crop_left is None or crop_top is None:
            raise ValueError("视频中未检测到背景以外的可见内容")
        if not capture.set(cv2.CAP_PROP_POS_FRAMES, 0):
            raise RuntimeError("无法重新定位视频帧，不能完成两遍转换")

        width = crop_right - crop_left
        height = crop_bottom - crop_top
        if keep_frames:
            frame_directory = _create_frame_directory()
        frame_image_names: List[str] = []
        encoded_assets: Dict[str, bytes] = {}
        digest_to_name: Dict[str, str] = {}
        second_compress_methods: Set[str] = set()
        frame_index = 0
        next_sample_index = 0.0
        while True:
            success, frame = capture.read()
            if not success:
                break
            if (frame.shape[1], frame.shape[0]) != source_size:
                raise ValueError("视频帧尺寸发生变化，无法生成单尺寸 SVGA")

            if frame_index + 1e-9 >= next_sample_index:
                bgra_frame, _ = _key_background(frame, background_bgr)
                cropped_frame = bgra_frame[crop_top:crop_bottom, crop_left:crop_right]
                encoded, png_data = cv2.imencode(
                    ".png",
                    cropped_frame,
                    [cv2.IMWRITE_PNG_COMPRESSION, 9],
                )
                if not encoded:
                    raise RuntimeError(
                        f"第 {len(frame_image_names)} 帧 PNG 编码失败"
                    )

                png_bytes = png_data.tobytes()
                if png8:
                    png_bytes = _quantize_png8(png_bytes)
                if second_compress:
                    png_bytes, method = _second_compress_png(png_bytes)
                    second_compress_methods.add(method)
                if frame_directory is not None:
                    frame_path = os.path.join(
                        frame_directory,
                        # f"frame_{len(frame_image_names):06d}.png",
                        f"{len(frame_image_names):03d}.png",
                    )
                    with open(frame_path, "wb") as frame_file:
                        frame_file.write(png_bytes)
                digest = hashlib.sha256(png_bytes).hexdigest()
                image_name = digest_to_name.get(digest)
                if image_name is None:
                    # image_name = f"frame_{len(encoded_assets):06d}"
                    image_name = f"{len(encoded_assets):03d}"
                    digest_to_name[digest] = image_name
                    encoded_assets[image_name] = png_bytes
                frame_image_names.append(image_name)
                next_sample_index += sample_interval
            frame_index += 1

        if len(frame_image_names) != sampled_frame_count:
            raise RuntimeError("视频帧读取结果不一致，请检查输入文件")

        encoded_movie = _encode_svga_v2(
            width, height, fps, frame_image_names, encoded_assets
        )
        with open(temp_path, "wb") as output_file:
            output_file.write(encoded_movie)

        os.replace(temp_path, absolute_output)
        conversion_succeeded = True
    finally:
        capture.release()
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if frame_directory is not None and not conversion_succeeded:
            shutil.rmtree(frame_directory)

    print(
        f"转换完成: {input_path} -> {absolute_output} "
        f"({width}x{height}, {fps} fps, {len(frame_image_names)} 帧, "
        f"{len(encoded_assets)} 个唯一 PNG/{expected_frames} 源帧, SVGA 2.0)"
    )
    if frame_directory is not None:
        print(f"中间 PNG 序列已保留: {frame_directory}")
    print(f"帧图像格式: {'PNG8 调色板' if png8 else 'RGBA PNG'}")
    if second_compress:
        print(f"二次压缩: {', '.join(sorted(second_compress_methods))}")


CONVERTERS: Dict[Tuple[str, str], Conversion] = {
    ("mp4", "svga"): convert_mp4_to_svga,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "媒体格式转换入口；支持纯色背景 MP4 或带 Alpha 通道 MP4 转 SVGA。"
            "默认生成 SVGA 2.0 并量化为 PNG8；保留 RGBA 可使用 --rgba。"
        )
    )
    parser.add_argument("input_format", choices=SUPPORTED_FORMATS, help="输入文件格式")
    parser.add_argument("output_format", choices=SUPPORTED_FORMATS, help="输出文件格式")
    parser.add_argument("input_path", help="输入文件路径")
    parser.add_argument("output_path", help="输出文件路径")
    parser.add_argument(
        "--alpha",
        action="store_true",
        help="输入是左右拼接 RGB/Alpha 的带通道 MP4（默认按背景色抠像）",
    )
    parser.add_argument(
        "--alpha-pos",
        choices=("left", "right"),
        default="right",
        help="带通道 MP4 中 Alpha 遮罩的位置（默认 right；另一半为 RGB）",
    )
    parser.add_argument(
        "--bg-color",
        default="#000000",
        help="标准 MP4 中需要去除的背景色（#RGB 或 #RRGGBB，默认黑色）",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=-1,
        help="标准 MP4 导出帧率上限（默认 -1，跟随源视频帧率）",
    )
    parser.add_argument(
        "--keep-frames",
        action="store_true",
        help="保留抠像、裁剪和降帧后的 PNG 序列（写入脚本目录下的子文件夹）",
    )
    parser.add_argument(
        "--png8",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--rgba",
        action="store_false",
        dest="png8",
        help="不做 PNG8 量化，改用 RGBA PNG（用于排查播放器兼容性）",
    )
    parser.add_argument(
        "--second-compress",
        action="store_true",
        help="使用 pngquant 或 Pillow 二次压缩 PNG 帧（仅在文件变小时替换）",
    )
    args = parser.parse_args(argv)

    converter = CONVERTERS.get((args.input_format, args.output_format))
    if converter is None:
        parser.error(
            f"暂不支持 {args.input_format} -> {args.output_format}；"
            "目前仅支持 mp4 -> svga"
        )

    try:
        if args.alpha:
            convert_alpha_mp4_to_svga(
                args.input_path,
                args.output_path,
                args.alpha_pos,
                args.keep_frames,
                args.png8,
                args.second_compress,
            )
        else:
            convert_mp4_to_svga(
                args.input_path,
                args.output_path,
                args.bg_color,
                args.fps,
                args.keep_frames,
                args.png8,
                args.second_compress,
            )
    except (OSError, ValueError, RuntimeError, cv2.error) as error:
        print(f"转换失败: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
