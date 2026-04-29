import cv2
import numpy as np
from itertools import product
from PIL import Image


def parse_regions(regions_text):
    if not regions_text:
        return None

    regions = []
    for item in regions_text.split(';'):
        item = item.strip()
        if not item:
            continue

        parts = [p.strip() for p in item.split(',')]
        if len(parts) != 4:
            raise ValueError(f"Invalid region '{item}'. Expected format: x,y,w,h")

        x, y, w, h = map(int, parts)
        if w <= 0 or h <= 0:
            raise ValueError(f"Invalid region '{item}'. Width and height must be positive.")

        regions.append((x, y, w, h))

    return regions if regions else None


def apply_regions_to_mask(mask, regions):
    if not regions:
        return mask

    masked = np.zeros_like(mask)
    height, width = mask.shape[:2]

    for x, y, w, h in regions:
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(width, x + w)
        y1 = min(height, y + h)

        if x0 < x1 and y0 < y1:
            masked[y0:y1, x0:x1] = mask[y0:y1, x0:x1]

    return masked


def inpaint_with_feather(frame, mask, inpaint_radius=7, feather_radius=21):
    inpainted = cv2.inpaint(frame, mask, inpaint_radius, cv2.INPAINT_TELEA)
    # Gaussian-blur the binary mask to get a soft alpha channel
    soft = cv2.GaussianBlur(mask.astype(np.float32), (feather_radius, feather_radius), 0)
    soft = np.clip(soft / soft.max(), 0, 1)[:, :, np.newaxis]  # normalise to [0,1]
    result = frame.astype(np.float32) * (1.0 - soft) + inpainted.astype(np.float32) * soft
    return result.astype(np.uint8)


def remove_watermark(image_path, output_path, regions=None):
    image = cv2.imread(image_path)
    if image is None:
        raise ValueError(f"Cannot read image: {image_path}")

    hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

    lower_bound = np.array([0, 0, 150])
    upper_bound = np.array([180, 80, 255])
    mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
    mask = apply_regions_to_mask(mask, regions)
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.dilate(mask, kernel, iterations=2)

    result = inpaint_with_feather(image, mask)
    cv2.imwrite(output_path, result)


def remove_watermark_from_video(input_video_path, output_video_path, regions=None):
    cap = cv2.VideoCapture(input_video_path)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    out = cv2.VideoWriter(output_video_path, fourcc, fps, (width, height))

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        hsv_image = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)

        # Define watermark color range and build a mask
        lower_bound = np.array([0, 0, 46])
        upper_bound = np.array([180, 150, 255])
        mask = cv2.inRange(hsv_image, lower_bound, upper_bound)
        mask = apply_regions_to_mask(mask, regions)
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=2)

        result = inpaint_with_feather(frame, mask)
        result = Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB))
        for pos in product(range(width), range(height)):
            if pos[1] < 100 or pos[1] > height - 100:
                pass
            # for x, y, w, h in regions:
            #     if x <= pos[0] < x + w and y <= pos[1] < y + h:
            #         if sum(result.getpixel(pos)[:3]) > 500:
            #             result.putpixel(pos, (255,255,255))
        
        out.write(cv2.cvtColor(np.array(result), cv2.COLOR_RGB2BGR))

    cap.release()
    out.release()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='Remove watermark from images or videos.')
    parser.add_argument('input_path', type=str, help='Path to the input image or video')
    parser.add_argument('output_path', type=str, help='Path to save the output image or video')
    parser.add_argument(
        '--regions',
        type=str,
        default='',
        help='Optional watermark regions, format: x,y,w,h;x,y,w,h'
    )

    args = parser.parse_args()

    try:
        regions = parse_regions(args.regions)
    except ValueError as exc:
        print(f"Invalid --regions: {exc}")
        raise SystemExit(2)

    if args.input_path.lower().endswith(('.png', '.jpg', '.jpeg')):
        remove_watermark(args.input_path, args.output_path, regions=regions)
    elif args.input_path.lower().endswith(('.mp4', '.avi', '.mov')):
        remove_watermark_from_video(args.input_path, args.output_path, regions=regions)
    else:
        print("Unsupported file format. Please provide an image or video file.")
