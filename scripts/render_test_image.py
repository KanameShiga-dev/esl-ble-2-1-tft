"""Render a high-contrast, orientation-sensitive 250x132 TFT test image."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import EVIDENCE_DIR, PROJECT_ROOT, iso_now, unique_path, write_json_new


WIDTH = 250
HEIGHT = 132


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    windows_fonts = Path("C:/Windows/Fonts")
    names = ["arialbd.ttf", "segoeuib.ttf"] if bold else ["arial.ttf", "segoeui.ttf"]
    for name in names:
        path = windows_fonts / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def centered_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (box[2] - box[0])) // 2


def build_test_image(rendered_at: str) -> Image.Image:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    small = load_font(10, bold=True)
    medium = load_font(13, bold=True)
    large = load_font(42, bold=True)

    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline="black", width=2)

    corner_boxes = {
        "TL": (3, 3, 25, 18),
        "TR": (WIDTH - 26, 3, WIDTH - 4, 18),
        "BL": (3, HEIGHT - 19, 25, HEIGHT - 4),
        "BR": (WIDTH - 26, HEIGHT - 19, WIDTH - 4, HEIGHT - 4),
    }
    for label, box in corner_boxes.items():
        draw.rectangle(box, fill="black")
        text_box = draw.textbbox((0, 0), label, font=small)
        text_width = text_box[2] - text_box[0]
        text_height = text_box[3] - text_box[1]
        x = box[0] + (box[2] - box[0] - text_width) // 2
        y = box[1] + (box[3] - box[1] - text_height) // 2 - text_box[1]
        draw.text((x, y), label, font=small, fill="white")

    draw.polygon(((WIDTH // 2, 3), (WIDTH // 2 - 7, 15), (WIDTH // 2 + 7, 15)), fill="black")
    draw.text((WIDTH // 2 + 10, 4), "UP", font=small, fill="black")

    title = "TEST"
    draw.text((centered_x(draw, title, large), 29), title, font=large, fill="black")

    model_line = "0xA0  250x132  BW"
    draw.text((centered_x(draw, model_line, medium), 78), model_line, font=medium, fill="black")

    timestamp_line = rendered_at.replace("T", " ")[:19]
    draw.text((centered_x(draw, timestamp_line, small), 99), timestamp_line, font=small, fill="black")

    # Eliminate anti-aliasing gray so the asset contains only exact black/white.
    return image.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="1").convert("RGB")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "images" / "test_pattern.png",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    rendered_at = iso_now()
    image = build_test_image(rendered_at)
    image.save(output, format="PNG", optimize=False)
    image_bytes = output.read_bytes()
    colors = image.getcolors(maxcolors=3) or []
    metadata = {
        "created_at": rendered_at,
        "file": str(output),
        "sha256": hashlib.sha256(image_bytes).hexdigest().upper(),
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "file_size": len(image_bytes),
        "colors": [
            {"count": count, "rgb": list(rgb)} for count, rgb in sorted(colors)
        ],
        "device_writes": 0,
        "write_allowed": False,
    }
    evidence_path = unique_path(EVIDENCE_DIR, "test_image", ".json")
    write_json_new(evidence_path, metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f"Evidence: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
