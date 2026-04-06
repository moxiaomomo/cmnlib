import cv2
import os
import numpy as np
import asyncio
import base64
from playwright.async_api import async_playwright

# 在puppeteer中加载SVGA的HTML模板，包含必要的JS逻辑来解析SVGA文件并捕获帧
SVGA_HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>SVGA Renderer</title>
    <script src="https://cdn.jsdelivr.net/npm/svgaplayerweb@2.3.1/build/svga.min.js"></script>
</head>
<body style="margin:0; background:transparent;">
    <canvas id="canvas"></canvas>
    <script>
    window.loadSvga = async (base64Data) => {
        const canvas = document.getElementById('canvas');
        try {
            const parser = new SVGA.Parser(canvas);
            const player = new SVGA.Player(canvas);
            
            const binaryString = atob(base64Data);
            const len = binaryString.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) {
                bytes[i] = binaryString.charCodeAt(i);
            }
            
            const blob = new Blob([bytes.buffer], { type: 'application/octet-stream' });
            const blobUrl = URL.createObjectURL(blob);
            
            await new Promise((resolve, reject) => {
                parser.load(blobUrl, (videoItem) => {
                    player.setVideoItem(videoItem);
                    canvas.width = videoItem.videoSize.width;
                    canvas.height = videoItem.videoSize.height;
                    window.videoItem = videoItem;
                    window.player = player;
                    resolve();
                }, (error) => {
                    console.error('SVGA Parse Error:', error);
                    reject(error);
                });
            });
            
            return { success: true, frames: window.videoItem.frames, width: canvas.width, height: canvas.height };
        } catch (e) {
            console.error(e);
            return { success: false, error: e.message };
        }
    };

    window.captureFrame = (frameIndex, type) => {
        window.player.stepToFrame(frameIndex);
        const canvas = document.getElementById('canvas');
        if (type === 'jpg') {
            return canvas.toDataURL('image/jpeg', 0.92);
        }
        return canvas.toDataURL('image/png');
    };
    </script>
</body>
</html>
"""

def apply_watermark(frame, text=None, logo_path=None, font_path=None, font_scale=1.0):
    """在 BGR 图像上居中底部约 1/4 位置添加文本/图片水印"""
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

def convert_video(
    input_path,
    output_dir,
    output_video_path=None,
    mix_bg_path=None,
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
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        print(f"Error: 无法打开视频文件 {input_path}")
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
    bg_image_orig = None
    bg_w_output = half_width
    bg_h_output = height

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
            # 5a. 加载背景图（第一帧时），使用其尺寸作为输出标准
            if frame_idx == 0:
                bg_image_orig = cv2.imread(mix_bg_path, cv2.IMREAD_COLOR)
                if bg_image_orig is None:
                    print(f"Error: 无法打开背景图片 {mix_bg_path}")
                    cap.release()
                    if video_writer is not None:
                        video_writer.release()
                    return
                bg_h_output, bg_w_output = bg_image_orig.shape[:2]

            # 计算前景尺寸：宽度按背景宽度，等比例缩放高度
            fg_h, fg_w = rgb_part.shape[:2]
            target_w = bg_w_output
            target_h = max(1, int(fg_h * target_w / fg_w))

            resized_rgb = cv2.resize(rgb_part, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            resized_alpha = cv2.resize(alpha_channel, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

            # 5b. 创建输出画布（复制背景图）
            output_frame = bg_image_orig.copy()

            # 计算垂直居中位置
            offset_x = (bg_w_output - target_w) // 2
            offset_y = (bg_h_output - target_h) // 2

            fg_x_start = max(0, offset_x)
            fg_y_start = max(0, offset_y)
            fg_x_end = min(bg_w_output, offset_x + target_w)
            fg_y_end = min(bg_h_output, offset_y + target_h)

            src_x_start = max(0, -offset_x)
            src_y_start = max(0, -offset_y)
            src_x_end = src_x_start + (fg_x_end - fg_x_start)
            src_y_end = src_y_start + (fg_y_end - fg_y_start)

            alpha_patch = resized_alpha[src_y_start:src_y_end, src_x_start:src_x_end].astype(np.float32) / 255.0
            alpha_3c = cv2.merge([alpha_patch, alpha_patch, alpha_patch])

            fg_patch = resized_rgb[src_y_start:src_y_end, src_x_start:src_x_end].astype(np.float32)
            bg_patch = output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end].astype(np.float32)

            blend_patch = cv2.multiply(alpha_3c, fg_patch) + cv2.multiply(1.0 - alpha_3c, bg_patch)
            blend_patch = np.clip(blend_patch, 0, 255).astype(np.uint8)

            output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end] = blend_patch

            # 不输出视频时，则输出 JPG序列
            if not output_video_path:
                cv2.imwrite(output_path, output_frame, [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])
            frame_for_video = output_frame
        else:
            # 不输出视频时，则输出带 alpha 的 PNG序列
            if not output_video_path:
                cv2.imwrite(output_path, bgra_image)
            frame_for_video = cv2.cvtColor(bgra_image, cv2.COLOR_BGRA2BGR)

        # 6. 如需要输出视频，写入 VideoWriter（第一帧时初始化）
        if output_video_path:
            output_video_full_path = os.path.join(output_dir, output_video_path)
            if video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                os.makedirs(os.path.dirname(output_video_full_path), exist_ok=True)
                video_writer = cv2.VideoWriter(
                    output_video_full_path, fourcc, fps, (bg_w_output, bg_h_output), True
                )
                if not video_writer.isOpened():
                    print(f"Error: 无法创建视频写入器 {output_video_full_path}")
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

async def convert_svga(
    svga_file_path,
    output_dir,
    output_video_path=None,
    mix_bg_path=None,
    wm_text=None,
    wm_logo=None,
    wm_font_scale=1.0,
    jpg_quality=95,
):
    """
    读取 SVGA 文件，提取帧，支持可选背景混合、水印、输出 MP4。
    mix_bg_path: 可选参数，指定背景图片路径，用于混合输出 JPG。
    output_video_path: 可选参数，指定输出合成 MP4 路径。
    wm_text: 可选参数，指定视频水印文本。
    wm_logo: 可选参数，指定水印图像路径。
    """
    if (wm_text or wm_logo) and not output_video_path:
        print("Error: wm_text/wm_logo 参数需要同时指定 --output_video_path")
        return

    # 路径处理
    absolute_svga_path = os.path.abspath(svga_file_path)
    absolute_output_dir = os.path.abspath(output_dir)
    
    if not os.path.exists(absolute_output_dir):
        os.makedirs(absolute_output_dir)

    # 读取文件并转 Base64
    with open(absolute_svga_path, 'rb') as f:
        svga_base64 = base64.b64encode(f.read()).decode('utf-8')

    print("Launching browser...")

    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # 设置页面内容
        await page.set_content(SVGA_HTML_CONTENT)

        print('Loading SVGA file...')
        # 执行 JS 加载 SVGA
        meta = await page.evaluate(f"window.loadSvga('{svga_base64}')")

        if not meta.get('success'):
            print(f"Failed to load SVGA: {meta.get('error')}")
            await browser.close()
            return

        total_frames = meta['frames']
        width = meta['width']
        height = meta['height']
        print(f"SVGA Info: {width}x{height}, Total Frames: {total_frames}")

        # 初始化背景图
        bg_image_orig = None
        bg_w_output = width
        bg_h_output = height
        
        if mix_bg_path:
            bg_image_orig = cv2.imread(mix_bg_path, cv2.IMREAD_COLOR)
            if bg_image_orig is None:
                print(f"Error: 无法打开背景图片 {mix_bg_path}")
                await browser.close()
                return
            bg_h_output, bg_w_output = bg_image_orig.shape[:2]

        video_writer = None
        if output_video_path:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            output_video_full_path = os.path.join(output_dir, output_video_path)
            os.makedirs(os.path.dirname(output_video_full_path), exist_ok=True)
            video_writer = cv2.VideoWriter(output_video_full_path, fourcc, 30, (bg_w_output, bg_h_output), True)  # 假设 30fps
            if not video_writer.isOpened():
                print(f"Error: 无法创建视频写入器 {output_video_full_path}")
                await browser.close()
                return

        # 遍历帧并保存
        for i in range(total_frames):
            # 执行 JS 捕获帧
            data_url = await page.evaluate("window.captureFrame({}, 'png')".format(i))
            
            # 解析 Base64 数据
            header, encoded = data_url.split(",", 1)
            image_data = base64.b64decode(encoded)
            
            # 解码为 numpy 数组
            nparr = np.frombuffer(image_data, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)

            # 处理背景混合
            if mix_bg_path and bg_image_orig is not None:
                fg_h, fg_w = frame.shape[:2]
                target_w = bg_w_output
                target_h = max(1, int(fg_h * target_w / fg_w))

                frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_LINEAR)

                offset_x = (bg_w_output - target_w) // 2
                offset_y = (bg_h_output - target_h) // 2

                output_frame = bg_image_orig.copy()

                fg_x_start = max(0, offset_x)
                fg_y_start = max(0, offset_y)
                fg_x_end = min(bg_w_output, offset_x + target_w)
                fg_y_end = min(bg_h_output, offset_y + target_h)

                src_x_start = max(0, -offset_x)
                src_y_start = max(0, -offset_y)
                src_x_end = src_x_start + (fg_x_end - fg_x_start)
                src_y_end = src_y_start + (fg_y_end - fg_y_start)

                if frame.shape[2] == 4:
                    alpha_patch = frame[src_y_start:src_y_end, src_x_start:src_x_end, 3].astype(np.float32) / 255.0
                    alpha_3c = cv2.merge([alpha_patch, alpha_patch, alpha_patch])

                    fg_patch = frame[src_y_start:src_y_end, src_x_start:src_x_end, :3].astype(np.float32)
                    bg_patch = output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end].astype(np.float32)

                    blend_patch = cv2.multiply(alpha_3c, fg_patch) + cv2.multiply(1.0 - alpha_3c, bg_patch)
                    blend_patch = np.clip(blend_patch, 0, 255).astype(np.uint8)

                    output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end] = blend_patch
                else:
                    output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end] = frame[src_y_start:src_y_end, src_x_start:src_x_end]

                frame = output_frame

            # 构造输出文件名
            output_img_type = 'jpg' if mix_bg_path else 'png'
            file_name = f"{i:06d}.{output_img_type}"
            file_path = os.path.join(absolute_output_dir, file_name)
            
            # 处理视频/图片序列输出
            if output_video_path:
                frame_for_video = frame if mix_bg_path else cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                frame_write = frame_for_video.copy()
                if wm_text or wm_logo:
                    frame_write = apply_watermark(frame_write, wm_text, wm_logo, font_scale=wm_font_scale)
                video_writer.write(frame_write)
            else:
                # 不输出视频，则保存图片
                try:
                    if mix_bg_path:
                        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality]
                        result, encoded_img = cv2.imencode(f'.{output_img_type}', frame, encode_param)
                    else:
                        result, encoded_img = cv2.imencode(f'.{output_img_type}', frame)
                    if result:
                        with open(file_path, 'wb') as f:
                            f.write(encoded_img.tobytes())
                except Exception as e:
                    print(f"Save error for frame {i}: {e}")                

            if i % 10 == 0:
                print(f"Processing frame {i}/{total_frames}")

        if video_writer is not None:
            video_writer.release()

        print(f"\n处理完成! 共处理 {total_frames} 帧图像。")
        await browser.close()
def convert_gif(
    gif_file_path,
    output_dir,
    output_video_path=None,
    mix_bg_path=None,
    wm_text=None,
    wm_logo=None,
    wm_font_scale=1.0,
    jpg_quality=95,
):
    """
    读取 GIF 动图，提取帧，支持可选背景混合、水印、输出 MP4。
    mix_bg_path: 可选参数，指定背景图片路径，用于混合输出 JPG。
    output_video_path: 可选参数，指定输出合成 MP4 路径。
    wm_text: 可选参数，指定视频水印文本。
    wm_logo: 可选参数，指定水印图像路径。
    """
    if (wm_text or wm_logo) and not output_video_path:
        print("Error: wm_text/wm_logo 参数需要同时指定 --output_video_path")
        return

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    gif_width = None
    gif_height = None
    fps = 30
    frames = []

    try:
        from PIL import Image, ImageSequence
        gif = Image.open(gif_file_path)
        gif_width, gif_height = gif.size
        duration = gif.info.get('duration', 100)
        if duration and duration > 0:
            fps = max(1, round(1000.0 / duration))

        for frame in ImageSequence.Iterator(gif):
            frame_rgba = frame.convert('RGBA')
            frames.append(np.array(frame_rgba))
    except ImportError:
        cap = cv2.VideoCapture(gif_file_path)
        if not cap.isOpened():
            print(f"Error: 无法打开 GIF 文件 {gif_file_path}")
            return

        gif_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        gif_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            frames.append(cv2.cvtColor(frame, cv2.COLOR_BGR2RGBA))
        cap.release()

    if gif_width is None or gif_height is None:
        print(f"Error: 无法读取 GIF 大小信息 {gif_file_path}")
        return

    bg_image_orig = None
    bg_w_output = gif_width
    bg_h_output = gif_height
    
    if mix_bg_path:
        bg_image_orig = cv2.imread(mix_bg_path, cv2.IMREAD_COLOR)
        if bg_image_orig is None:
            print(f"Error: 无法打开背景图片 {mix_bg_path}")
            return
        bg_h_output, bg_w_output = bg_image_orig.shape[:2]

    video_writer = None
    if output_video_path:
        output_video_full_path = os.path.join(output_dir, output_video_path)
        os.makedirs(os.path.dirname(output_video_full_path), exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        video_writer = cv2.VideoWriter(output_video_full_path, fourcc, fps, (bg_w_output, bg_h_output), True)
        if not video_writer.isOpened():
            print(f"Error: 无法创建视频写入器 {output_video_full_path}")
            return

    for i, frame_np in enumerate(frames):
        frame_bgra = cv2.cvtColor(frame_np, cv2.COLOR_RGBA2BGRA)

        if mix_bg_path and bg_image_orig is not None:
            fg_h, fg_w = frame_bgra.shape[:2]
            target_w = min(bg_w_output, fg_w * 2)
            target_h = max(1, int(fg_h * target_w / fg_w))

            frame_bgra = cv2.resize(frame_bgra, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
            
            offset_x = (bg_w_output - target_w) // 2
            offset_y = (bg_h_output - target_h) // 2
            
            output_frame = bg_image_orig.copy()
            
            fg_x_start = max(0, offset_x)
            fg_y_start = max(0, offset_y)
            fg_x_end = min(bg_w_output, offset_x + target_w)
            fg_y_end = min(bg_h_output, offset_y + target_h)
            
            src_x_start = max(0, -offset_x)
            src_y_start = max(0, -offset_y)
            src_x_end = src_x_start + (fg_x_end - fg_x_start)
            src_y_end = src_y_start + (fg_y_end - fg_y_start)
            
            alpha_patch = frame_bgra[src_y_start:src_y_end, src_x_start:src_x_end, 3].astype(np.float32) / 255.0
            alpha_3c = cv2.merge([alpha_patch, alpha_patch, alpha_patch])
            
            fg_patch = frame_bgra[src_y_start:src_y_end, src_x_start:src_x_end, :3].astype(np.float32)
            bg_patch = output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end].astype(np.float32)
            
            blend_patch = cv2.multiply(alpha_3c, fg_patch) + cv2.multiply(1.0 - alpha_3c, bg_patch)
            blend_patch = np.clip(blend_patch, 0, 255).astype(np.uint8)
            
            output_frame[fg_y_start:fg_y_end, fg_x_start:fg_x_end] = blend_patch
        else:
            output_frame = frame_bgra

        output_img_type = 'jpg' if mix_bg_path else 'png'
        file_name = f"{i:06d}.{output_img_type}"
        file_path = os.path.join(output_dir, file_name)

        if output_video_path:
            # 输出视频；转换为 BGR 用于视频写入
            if mix_bg_path:
                frame_for_video = output_frame  # 已经是 BGR（背景图）
            else:
                frame_for_video = cv2.cvtColor(output_frame, cv2.COLOR_BGRA2BGR)
            frame_write = frame_for_video.copy()
            if wm_text or wm_logo:
                frame_write = apply_watermark(frame_write, wm_text, wm_logo, font_scale=wm_font_scale)
            video_writer.write(frame_write)
        else:
            # 不输出视频，则保存图片
            try:
                if mix_bg_path:
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), jpg_quality]
                    result, encoded_img = cv2.imencode(f'.{output_img_type}', output_frame, encode_param)
                else:
                    result, encoded_img = cv2.imencode(f'.{output_img_type}', output_frame)
                if result:
                    with open(file_path, 'wb') as f:
                        f.write(encoded_img.tobytes())
            except Exception as e:
                print(f"Save error for frame {i}: {e}")           

        if i % 10 == 0:
            print(f"Processing frame {i}/{len(frames)}")

    print(f"\n处理完成! 共处理 {len(frames)} 帧图像。")
    if video_writer is not None:
        video_writer.release()

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从带通道mp4、VAP视频、SVGA、GIF等动画文件中提取帧，支持加水印、支持背景图混合，合成标准mp4视频")
    parser.add_argument("input_type", help="输入媒体文件类型", choices=["mp4","vap","svga","gif"])
    parser.add_argument("input_path", help="输入媒体文件路径")
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

    switch = {
        "mp4": convert_video,
        "vap": convert_video,
        "svga": convert_svga,
        "gif": convert_gif
    }
    
    match args.input_type:
        case "mp4" | "vap":
            convert_video(
                args.input_path,
                args.output_folder,
                output_video_path=args.output_video_path,
                mix_bg_path=args.mix_bg_path,
                wm_text=args.wm_text,
                wm_logo=args.wm_logo,
                wm_font_scale=args.wm_font_scale,
                jpg_quality=args.jpg_quality
            )
        case "svga":
            asyncio.run(convert_svga(
                args.input_path,
                args.output_folder,
                output_video_path=args.output_video_path,
                mix_bg_path=args.mix_bg_path,
                wm_text=args.wm_text,
                wm_logo=args.wm_logo,
                wm_font_scale=args.wm_font_scale,
                jpg_quality=args.jpg_quality
            ))
        case "gif":
            convert_gif(
                args.input_path,
                args.output_folder,
                output_video_path=args.output_video_path,
                mix_bg_path=args.mix_bg_path,
                wm_text=args.wm_text,
                wm_logo=args.wm_logo,
                wm_font_scale=args.wm_font_scale,
                jpg_quality=args.jpg_quality
            )


"""__summary__
# gif转mp4，加水印、背景图等功能示例：
python convert2video.py gif 5.gif gif2mp4 --mix_bg_path=bg.jpg --output_video_path=gif2mp4.mp4 --wm_text="元子星科技 出品" --wm_logo=logo.png --wm_font_scale=0.5

# svga转mp4，加水印、背景图等功能示例：
python convert2video.py svga 3.svga svga2mp4 --mix_bg_path=bg.jpg --output_video_path=svga2mp4.mp4 --wm_text="元子星科技 出品" --wm_logo=logo.png --wm_font_scale=0.5

# 带通道mp4转标准mp4，加水印、背景图等功能示例：
python convert2video.py mp4 1.mp4 video2mp4 --mix_bg_path=bg.jpg --output_video_path=video2mp4.mp4 --wm_text="元子星科技 出品" --wm_logo=logo.png --wm_font_scale=0.5
"""
