"""Render a high-legibility sample for the 0xA0 2.1-inch TFT ESL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from common import EVIDENCE_DIR, PROJECT_ROOT, iso_now, unique_path, write_json_new


WIDTH = 250
HEIGHT = 132


PIXEL_FONT: dict[str, tuple[str, ...]] = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "5": ("11111", "10000", "10000", "11110", "00001", "00001", "11110"),
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "P": ("11110", "10001", "10001", "11110", "10000", "10000", "10000"),
    "Q": ("01110", "10001", "10001", "10001", "10101", "10010", "01101"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "X": ("10001", "10001", "01010", "00100", "01010", "10001", "10001"),
    "x": ("00000", "00000", "10001", "01010", "00100", "01010", "10001"),
    "/": ("00001", "00010", "00100", "01000", "10000", "00000", "00000"),
    "|": ("00100", "00100", "00100", "00100", "00100", "00100", "00100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arialbd.ttf", "segoeuib.ttf"):
        path = Path("C:/Windows/Fonts") / name
        if path.exists():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_size: int,
    min_size: int,
    max_width: int,
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for size in range(max_size, min_size - 1, -1):
        font = load_font(size)
        box = draw.textbbox((0, 0), text, font=font)
        if box[2] - box[0] <= max_width:
            return font
    return load_font(min_size)


def centered_x(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    box = draw.textbbox((0, 0), text, font=font)
    return (WIDTH - (box[2] - box[0])) // 2


def draw_corner_marker(
    draw: ImageDraw.ImageDraw,
    label: str,
    box: tuple[int, int, int, int],
) -> None:
    font = load_font(14)
    draw.rectangle(box, fill="black")
    text_box = draw.textbbox((0, 0), label, font=font)
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    x = box[0] + (box[2] - box[0] - text_width) // 2
    y = box[1] + (box[3] - box[1] - text_height) // 2 - text_box[1]
    draw.text((x, y), label, font=font, fill="white")


def pixel_text_size(text: str, scale: int, spacing: int | None = None) -> tuple[int, int]:
    gap = scale if spacing is None else spacing
    return (sum(5 * scale for _ in text) + max(0, len(text) - 1) * gap, 7 * scale)


def draw_pixel_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    scale: int,
    x: int,
    y: int,
    fill: str = "black",
    spacing: int | None = None,
) -> None:
    gap = scale if spacing is None else spacing
    cursor_x = x
    for character in text:
        pattern = PIXEL_FONT.get(character, PIXEL_FONT[" "])
        for row, pattern_row in enumerate(pattern):
            for column, value in enumerate(pattern_row):
                if value == "1":
                    draw.rectangle(
                        (
                            cursor_x + column * scale,
                            y + row * scale,
                            cursor_x + (column + 1) * scale - 1,
                            y + (row + 1) * scale - 1,
                        ),
                        fill=fill,
                    )
        cursor_x += 5 * scale + gap


def build_pixel_sample(top_safe_margin: int = 10, title_scale: int = 4) -> Image.Image:
    if not 0 <= top_safe_margin <= 20:
        raise ValueError("top_safe_margin must be between 0 and 20 pixels")
    if title_scale not in (4, 6):
        raise ValueError("title_scale must be 4 or 6")
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline="black", width=3)

    marker_boxes = {
        "TL": (4, top_safe_margin, 32, top_safe_margin + 21),
        "TR": (WIDTH - 33, top_safe_margin, WIDTH - 5, top_safe_margin + 21),
        "BL": (4, HEIGHT - 26, 32, HEIGHT - 5),
        "BR": (WIDTH - 33, HEIGHT - 26, WIDTH - 5, HEIGHT - 5),
    }
    for label, box in marker_boxes.items():
        draw.rectangle(box, fill="black")
        text_width, text_height = pixel_text_size(label, 2)
        draw_pixel_text(
            draw,
            label,
            2,
            box[0] + (box[2] - box[0] - text_width) // 2,
            box[1] + (box[3] - box[1] - text_height) // 2,
            fill="white",
        )

    arrow_y = top_safe_margin + 2
    draw.polygon(
        ((WIDTH // 2, arrow_y), (WIDTH // 2 - 8, arrow_y + 14), (WIDTH // 2 + 8, arrow_y + 14)),
        fill="black",
    )
    up_width, _ = pixel_text_size("UP", 2)
    draw_pixel_text(draw, "UP", 2, WIDTH // 2 + 13, arrow_y, fill="black")

    title = "BLE OK"
    title_width, _ = pixel_text_size(title, title_scale)
    draw_pixel_text(draw, title, title_scale, (WIDTH - title_width) // 2, 41)

    draw.line((43, 82, WIDTH - 44, 82), fill="black", width=2)
    subtitle = "A0 250x132"
    subtitle_scale = 3
    subtitle_width, _ = pixel_text_size(subtitle, subtitle_scale)
    draw_pixel_text(draw, subtitle, subtitle_scale, (WIDTH - subtitle_width) // 2, 84)

    return image.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="1").convert("RGB")


def build_clear_sample(top_safe_margin: int = 10) -> Image.Image:
    if not 0 <= top_safe_margin <= 20:
        raise ValueError("top_safe_margin must be between 0 and 20 pixels")
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, WIDTH - 1, HEIGHT - 1), outline="black", width=3)

    top_marker_bottom = top_safe_margin + 21
    draw_corner_marker(draw, "TL", (4, top_safe_margin, 32, top_marker_bottom))
    draw_corner_marker(
        draw,
        "TR",
        (WIDTH - 33, top_safe_margin, WIDTH - 5, top_marker_bottom),
    )
    draw_corner_marker(draw, "BL", (4, HEIGHT - 26, 32, HEIGHT - 5))
    draw_corner_marker(draw, "BR", (WIDTH - 33, HEIGHT - 26, WIDTH - 5, HEIGHT - 5))

    draw.polygon(
        (
            (WIDTH // 2, top_safe_margin),
            (WIDTH // 2 - 8, top_safe_margin + 14),
            (WIDTH // 2 + 8, top_safe_margin + 14),
        ),
        fill="black",
    )
    up_font = load_font(14)
    draw.text((WIDTH // 2 + 13, top_safe_margin + 1), "UP", font=up_font, fill="black")

    title = "BLE OK"
    title_font = fit_font(draw, title, max_size=48, min_size=34, max_width=184)
    title_box = draw.textbbox((0, 0), title, font=title_font)
    title_y = max(37, top_marker_bottom + 6) - title_box[1]
    draw.text((centered_x(draw, title, title_font), title_y), title, font=title_font, fill="black")

    draw.line((54, 79, WIDTH - 55, 79), fill="black", width=2)
    subtitle = "0xA0  |  250x132  |  BW"
    subtitle_font = fit_font(draw, subtitle, max_size=21, min_size=14, max_width=188)
    subtitle_box = draw.textbbox((0, 0), subtitle, font=subtitle_font)
    subtitle_y = 88 - subtitle_box[1]
    draw.text(
        (centered_x(draw, subtitle, subtitle_font), subtitle_y),
        subtitle,
        font=subtitle_font,
        fill="black",
    )

    # The transport is one-bit. Threshold after drawing so no gray pixels are
    # sent and thin anti-aliased edges cannot consume the small text budget.
    return image.convert("L").point(lambda value: 255 if value >= 128 else 0, mode="1").convert("RGB")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "images" / "clear_sample_adjusted.png",
    )
    parser.add_argument(
        "--style",
        choices=("font", "pixel"),
        default="pixel",
        help="Use regular bold fonts or integer-aligned bitmap glyphs.",
    )
    parser.add_argument(
        "--top-safe-margin",
        type=int,
        default=10,
        help="Interior top margin in source pixels for the top markers (0-20).",
    )
    parser.add_argument(
        "--title-scale",
        type=int,
        choices=(4, 6),
        default=4,
        help="Integer pixel scale for BLE OK (4 is finer, 6 is larger).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    created_at = iso_now()
    image = (
        build_pixel_sample(args.top_safe_margin, args.title_scale)
        if args.style == "pixel"
        else build_clear_sample(args.top_safe_margin)
    )
    image.save(output, format="PNG", optimize=False)
    image_bytes = output.read_bytes()
    colors = image.getcolors(maxcolors=3) or []
    metadata = {
        "created_at": created_at,
        "file": str(output),
        "sha256": hashlib.sha256(image_bytes).hexdigest().upper(),
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "file_size": len(image_bytes),
        "colors": [
            {"count": count, "rgb": list(rgb)} for count, rgb in sorted(colors)
        ],
        "design": {
            "title": "BLE OK",
            "subtitle": "A0 250x132" if args.style == "pixel" else "0xA0 | 250x132 | BW",
            "style": args.style,
            "title_scale": args.title_scale if args.style == "pixel" else None,
            "small_text_removed": True,
            "orientation_markers": True,
            "top_safe_margin": args.top_safe_margin,
        },
        "device_writes": 0,
        "write_allowed": False,
    }
    evidence_path = unique_path(EVIDENCE_DIR, "clear_sample", ".json")
    write_json_new(evidence_path, metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    print(f"Evidence: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
