import cv2
import os
import numpy as np

def apply_watermark(frame, text=None, logo_path=None, font_path=None, font_scale=1.0):
    """在 BGR 图像上居中底部 1/4 位置添加文本/图片水印"""
    h, w = frame.shape[:2]
    overlay = frame.copy()

    has_logo = bool(logo_path)
    has_text = bool(text)

    logo = None
    logo_h = logo_w = 0
    if has_logo:
        logo = cv2.imread(logo_path, cv2.IMREAD_UNCHANGED)
        if logo is None:
            print(f"Warning: 无法加载 wmLogo 图片 {logo_path}，仅输出文本水印")
            has_logo = False
        else:
            # 统一宽度不超过画面宽度的 20%
            max_logo_w = int(w * 0.2)
            if logo.shape[1] > max_logo_w:
                scale_ratio = max_logo_w / logo.shape[1]
                logo = cv2.resize(
                    logo,
                    (max_logo_w, int(logo.shape[0] * scale_ratio)),
                    interpolation=cv2.INTER_AREA,
                )
            logo_h, logo_w = logo.shape[:2]

    # 计算文字位置和大小
    text_size = (0, 0)
    scale = 1.0
    thickness = 2
    use_pil_text = False
    pil_font = None
    pil_text_size = (0, 0)

    if has_text:
        use_pil_text = any(ord(ch) > 127 for ch in text)
        if use_pil_text:
            try:
                from PIL import Image, ImageDraw, ImageFont
            except ImportError:
                use_pil_text = False
                print(
                    "Warning: 未安装 Pillow，将使用 OpenCV 文字渲染，中文可能不正确。请运行：pip install pillow"
                )

        if use_pil_text:
            from PIL import Image, ImageDraw, ImageFont

            pil_img = Image.fromarray(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)

            candidates = []
            if font_path:
                candidates.append(font_path)
            candidates += [
                "C:/Windows/Fonts/simhei.ttf",
                "C:/Windows/Fonts/msyh.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]

            font_size = max(8, int(h * 0.05 * font_scale))
            font_file = None
            for p in candidates:
                if p and os.path.exists(p):
                    try:
                        pil_font = ImageFont.truetype(p, font_size)
                        font_file = p
                        break
                    except Exception:
                        pil_font = None
            if pil_font is None:
                pil_font = ImageFont.load_default()

            def _get_text_size(draw_obj, txt, font_obj):
                if hasattr(draw_obj, "textbbox"):
                    bbox = draw_obj.textbbox((0, 0), txt, font=font_obj)
                    return bbox[2] - bbox[0], bbox[3] - bbox[1]
                elif hasattr(draw_obj, "textsize"):
                    return draw_obj.textsize(txt, font=font_obj)
                else:
                    # 兼容老版本
                    return (len(txt) * 10, 20)

            pil_text_size = _get_text_size(draw, text, pil_font)
            text_size = pil_text_size
        else:
            font = cv2.FONT_HERSHEY_SIMPLEX
            text_size, _ = cv2.getTextSize(text, font, scale, thickness)
            while text_size[0] > int(w * 0.9) and scale > 0.1:
                scale -= 0.05
                text_size, _ = cv2.getTextSize(text, font, scale, thickness)

    # 基准位置：水平居中，纵向 80%
    y_base = int(h * 0.8)

    # 处理 logo (可能带 alpha)，确保 logo+文字宽度整体居中
    total_width = 0
    spacing = 10 if has_logo and has_text else 0
    if has_logo and has_text:
        total_width = (
            logo_w + spacing + (text_size[0] if not use_pil_text else pil_text_size[0])
        )
    elif has_logo:
        total_width = logo_w
    elif has_text:
        total_width = text_size[0] if not use_pil_text else pil_text_size[0]

    x_start = int((w - total_width) / 2) if total_width > 0 else 0

    if has_logo:
        x_logo = x_start
        y_logo = y_base - int(logo_h / 2)

        if logo.ndim == 3 and logo.shape[2] == 4:
            alpha_logo = logo[:, :, 3] / 255.0
            for c in range(3):
                overlay[y_logo : y_logo + logo_h, x_logo : x_logo + logo_w, c] = (
                    logo[:, :, c] * alpha_logo
                    + overlay[y_logo : y_logo + logo_h, x_logo : x_logo + logo_w, c]
                    * (1 - alpha_logo)
                ).astype(np.uint8)
        else:
            overlay[y_logo : y_logo + logo_h, x_logo : x_logo + logo_w] = (
                logo[:, :, :3]
                if logo.ndim == 3
                else cv2.cvtColor(logo, cv2.COLOR_GRAY2BGR)
            )
    else:
        x_logo = None

    # 处理文字
    if has_text:
        if use_pil_text:
            from PIL import Image, ImageDraw, ImageFont

            pil_img = Image.fromarray(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)

            if pil_text_size[0] > int(w * 0.9):
                scale_ratio = int(w * 0.9) / pil_text_size[0]
                font_size = max(8, int(font_size * scale_ratio))
                try:
                    if font_file and os.path.exists(font_file):
                        pil_font = ImageFont.truetype(font_file, font_size)
                    else:
                        pil_font = ImageFont.load_default()
                except Exception:
                    pil_font = ImageFont.load_default()

                pil_text_size = _get_text_size(draw, text, pil_font)

            x_text = x_start if x_start is not None else int((w - pil_text_size[0]) / 2)
            if has_logo:
                x_text = int(x_logo + logo_w + spacing)
            y_text = y_base - int(pil_text_size[1] / 2)

            for dx, dy in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text(
                    (x_text + dx, y_text + dy), text, font=pil_font, fill=(0, 0, 0)
                )
            draw.text((x_text, y_text), text, font=pil_font, fill=(255, 255, 255))

            overlay = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        else:
            x_text = x_start if x_start is not None else int((w - text_size[0]) / 2)
            if has_logo:
                x_text = int(x_logo + logo_w + spacing)
            y_text = y_base
            cv2.putText(
                overlay,
                text,
                (x_text, y_text),
                font,
                scale,
                (0, 0, 0),
                thickness + 2,
                cv2.LINE_AA,
            )
            cv2.putText(
                overlay,
                text,
                (x_text, y_text),
                font,
                scale,
                (255, 255, 255),
                thickness,
                cv2.LINE_AA,
            )

    return overlay


def extract_frames_with_alpha(
    video_path,
    output_dir,
    mix_bg_path=None,
    output_video_path=None,
    wm_text=None,
    wm_logo=None,
    wm_font_scale=1.0,
    jpg_quality=95,
):
    """
    读取左右拼接的视频（左为RGB，右为Alpha遮罩），合并输出为JPG/PNG序列。
    mix_bg_path: 可选参数，指定一个背景图片路径，用于混合输出JPG序列。如果不提供，则输出将包含Alpha通道的PNG序列。
    output_video_path: 可选参数，指定输出合成MP4路径。
    wm_text: 可选参数，指定视频合成后加水印文本（需同时指定 output_video_path）。
    wm_logo: 可选参数，指定水印图像路径; 如果有 wm_text 则放在文字左边，否则居中底部1/4。
    """
    if (wm_text or wm_logo) and not output_video_path:
        print("Error: wm_text/wm_logo 参数需要同时指定 --output_video_path")
        return

    # 1. 检查并创建输出目录
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # 2. 打开视频文件
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: 无法打开视频文件 {video_path}")
        return

    # 获取视频信息
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # 原视频宽度是双倍的，计算单边宽度
    half_width = width // 2

    print(f"视频信息: {width}x{height} @ {fps:.2f}fps, 总帧数: {total_frames}")
    print(f"开始处理，输出目录: {output_dir}")

    frame_idx = 0
    video_writer = None

    while True:
        ret, frame = cap.read()

        if not ret:
            break  # 视频读取结束

        # --- 核心处理逻辑 ---

        # 1. 切割图像
        # 左半部分：原始视频内容 -> 作为 RGB 通道
        # 右半部分：Alpha遮罩 -> 作为 Alpha 通道
        rgb_part = frame[:, :half_width]
        alpha_part = frame[:, half_width:]

        # 2. 处理 Alpha 通道
        # 如果 Alpha 遮罩是彩色的（虽然通常是黑白），转为灰度图
        if len(alpha_part.shape) == 3:
            alpha_channel = cv2.cvtColor(alpha_part, cv2.COLOR_BGR2GRAY)
        else:
            alpha_channel = alpha_part

        # (可选) 如果遮罩是“白底黑字”而你需要“透明背景”，请取消下面注释
        # alpha_channel = 255 - alpha_channel

        # 3. 合并通道 (OpenCV 读图默认是 BGR)
        # 将 BGR 转为 BGRA，并赋予 Alpha 通道
        bgra_image = cv2.cvtColor(rgb_part, cv2.COLOR_BGR2BGRA)
        bgra_image[:, :, 3] = alpha_channel

        # 4. 构造输出文件名
        if mix_bg_path:
            output_filename = f"{frame_idx:06d}.jpg"
        else:
            output_filename = f"{frame_idx:06d}.png"
        output_path = os.path.join(output_dir, output_filename)

        if mix_bg_path:
            # 5a. 加载背景图并调整到视频单帧大小
            if frame_idx == 0:
                bg_image = cv2.imread(mix_bg_path, cv2.IMREAD_COLOR)
                if bg_image is None:
                    print(f"Error: 无法打开背景图片 {mix_bg_path}")
                    cap.release()
                    if video_writer is not None:
                        video_writer.release()
                    return
                bg_image = cv2.resize(
                    bg_image, (half_width, height), interpolation=cv2.INTER_LINEAR
                )

            # 5b. 透明混合（前景是 rgb_part + alpha_channel）
            alpha_norm = alpha_channel.astype(np.float32) / 255.0
            alpha_3c = cv2.merge([alpha_norm, alpha_norm, alpha_norm])

            fg = rgb_part.astype(np.float32)
            bg = bg_image.astype(np.float32)

            blend = cv2.multiply(alpha_3c, fg) + cv2.multiply(1.0 - alpha_3c, bg)
            blend = np.clip(blend, 0, 255).astype(np.uint8)

            # 保存 JPG
            cv2.imwrite(output_path, blend, [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])
            frame_for_video = blend
        else:
            # 保存带 alpha 的 PNG
            cv2.imwrite(output_path, bgra_image)
            frame_for_video = cv2.cvtColor(bgra_image, cv2.COLOR_BGRA2BGR)

        # 6. 如需要输出视频，写入 VideoWriter
        if output_video_path:
            if video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
                video_writer = cv2.VideoWriter(
                    output_video_path, fourcc, fps, (half_width, height), True
                )
                if not video_writer.isOpened():
                    print(f"Error: 无法创建视频写入器 {output_video_path}")
                    cap.release()
                    return

            frame_write = frame_for_video.copy()
            if wm_text or wm_logo:
                frame_write = apply_watermark(
                    frame_write, wm_text, wm_logo, font_scale=wm_font_scale
                )
            video_writer.write(frame_write)

        frame_idx += 1

        # 进度打印
        if frame_idx % 30 == 0:
            print(f"已处理: {frame_idx}/{total_frames} 帧", end="\r")

    cap.release()
    if video_writer is not None:
        video_writer.release()
    print(f"\n处理完成! 共生成 {frame_idx} 张图片。")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从左右拼接 RGB/Alpha 视频中提取帧，支持可选背景混合与视频合成")
    parser.add_argument("input_video", help="输入视频文件路径")
    parser.add_argument("output_folder", help="输出文件夹")
    parser.add_argument("--mix_bg_path", dest="mix_bg_path", default=None,
                        help="可选的背景图片路径（指定后输出 JPG 并做前景透明混合）")
    parser.add_argument("--output_video_path", dest="output_video_path", default=None,
                        help="可选的输出 MP4 路径")
    parser.add_argument("--wm_text", dest="wm_text", default=None,
                        help="可选的视频水印文本（需与 --output_video_path 一起使用）")
    parser.add_argument("--wm_logo", dest="wm_logo", default=None,
                        help="可选的视频水印图标路径（可与 --wmText 一起使用）")
    parser.add_argument("--wm_font_scale", dest="wm_font_scale", type=float, default=1.0,
                        help="可选的水印字体缩放系数，0.5 表示默认高度的一半（仅影响文字水印）")
    parser.add_argument("--jpg_quality", type=int, default=95,
                        help="JPEG 质量 0-100（只在 mix_bg_path 模式下有效）")

    args = parser.parse_args()

    if (args.wm_text or args.wm_logo) and not args.output_video_path:
        parser.error("--wm_text/--wm_logo 需要和 --output_video_path 一起使用")

    extract_frames_with_alpha(
        args.input_video,
        args.output_folder,
        mix_bg_path=args.mix_bg_path,
        output_video_path=args.output_video_path,
        wm_text=args.wm_text,
        wm_logo=args.wm_logo,
        wm_font_scale=args.wm_font_scale,
        jpg_quality=args.jpg_quality
    )
