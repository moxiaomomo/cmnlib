#!/usr/bin/env python3
"""Detect foods in an image and return bounding box list.

Usage examples:
  python detect_foods.py --image ./input/food1.png
  python detect_foods.py --image ./input/food1.png --jsonOut ./output/food1_boxes.json --annotatedOut ./output/food1_annotated.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import cv2
from ultralytics import YOLO

# COCO classes that are clearly food-related.
FOOD_CLASSES = {
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
}


def detect_foods(
    image_path: str,
    model_name: str = "yolov8n.pt",
    conf: float = 0.25,
) -> List[Dict[str, Any]]:
    """Detect foods and return a list of bounding box dictionaries.

    Returned item schema:
      {
        "label": "pizza",
        "confidence": 0.92,
        "x": 120,
        "y": 48,
        "width": 210,
        "height": 160
      }
    """
    model = YOLO(model_name)
    results = model.predict(source=image_path, conf=conf, verbose=False)

    food_boxes: List[Dict[str, Any]] = []
    if not results:
        return food_boxes

    result = results[0]
    names = result.names

    if result.boxes is None:
        return food_boxes

    for box in result.boxes:
        cls_id = int(box.cls.item())
        label = names.get(cls_id, str(cls_id))
        if label not in FOOD_CLASSES:
            continue

        x1, y1, x2, y2 = box.xyxy[0].tolist()
        x = int(round(x1))
        y = int(round(y1))
        w = int(round(x2 - x1))
        h = int(round(y2 - y1))

        food_boxes.append(
            {
                "label": label,
                "confidence": round(float(box.conf.item()), 4),
                "x": x,
                "y": y,
                "width": max(0, w),
                "height": max(0, h),
            }
        )

    # Keep output stable: highest confidence first.
    food_boxes.sort(key=lambda item: item["confidence"], reverse=True)
    return food_boxes


def draw_boxes(image_path: str, foods: List[Dict[str, Any]], out_path: str) -> None:
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(f"Cannot read image: {image_path}")

    for item in foods:
        x = int(item["x"])
        y = int(item["y"])
        w = int(item["width"])
        h = int(item["height"])
        label = str(item["label"])
        confidence = float(item["confidence"])

        cv2.rectangle(image, (x, y), (x + w, y + h), (32, 220, 32), 2)
        text = f"{label} {confidence:.2f}"
        cv2.putText(
            image,
            text,
            (x, max(12, y - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (32, 220, 32),
            1,
            cv2.LINE_AA,
        )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), image)


def main() -> None:
    parser = argparse.ArgumentParser(description="Detect foods and output bounding box list")
    parser.add_argument("--image", default="./input/food1.png", help="Input image path")
    parser.add_argument("--model", default="yolov8n.pt", help="YOLO model name or path")
    parser.add_argument("--conf", type=float, default=0.25, help="Confidence threshold")
    parser.add_argument(
        "--jsonOut",
        default="./output/food1_food_boxes.json",
        help="Output JSON path",
    )
    parser.add_argument(
        "--annotatedOut",
        default="./output/food1_annotated.png",
        help="Output image path with drawn boxes",
    )
    args = parser.parse_args()

    foods = detect_foods(image_path=args.image, model_name=args.model, conf=args.conf)

    output_json = {
        "image": str(args.image),
        "count": len(foods),
        "foods": foods,
    }

    out_json_path = Path(args.jsonOut)
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps(output_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    draw_boxes(args.image, foods, args.annotatedOut)

    print(json.dumps(output_json, ensure_ascii=False, indent=2))
    print(f"\nSaved JSON: {out_json_path}")
    print(f"Saved annotated image: {args.annotatedOut}")


if __name__ == "__main__":
    main()
