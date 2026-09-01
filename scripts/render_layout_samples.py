"""Render local 0xA0 layout samples without communicating with the ESL."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw
from qrcode.constants import ERROR_CORRECT_M

from common import EVIDENCE_DIR, PROJECT_ROOT, iso_now, unique_path, write_json_new
from render_clear_sample import draw_pixel_text, pixel_text_size


WIDTH = 250
HEIGHT = 132
QR_BORDER_MODULES = 4


def _to_bw(image: Image.Image) -> Image.Image:
    """Return an RGB image containing only exact black and white pixels."""

    return image.convert("L").point(
        lambda value: 255 if value >= 128 else 0, mode="1"
    ).convert("RGB")


def _assert_bw(image: Image.Image) -> None:
    if image.size != (WIDTH, HEIGHT):
        raise ValueError(f"Expected {(WIDTH, HEIGHT)}, got {image.size}")
    if image.mode != "RGB":
        raise ValueError(f"Expected RGB output, got {image.mode}")
    colors = {color for _, color in image.getcolors(maxcolors=3) or []}
    if colors != {(0, 0, 0), (255, 255, 255)}:
        raise ValueError(f"Output is not exact black/white: {sorted(colors)}")


def qr_matrix_modules(version: int) -> int:
    """Return the side length of a Model 2 QR matrix for a version."""

    if version < 1 or version > 40:
        raise ValueError("QR version must be between 1 and 40")
    return 17 + 4 * version


def build_qr(
    data: str,
    *,
    version: int,
    box_size: int,
    border: int = QR_BORDER_MODULES,
) -> Image.Image:
    """Build a high-contrast QR raster with a standards-compliant quiet zone."""

    if not data:
        raise ValueError("QR data must not be empty")
    if box_size < 1:
        raise ValueError("QR box_size must be positive")
    if border < QR_BORDER_MODULES:
        raise ValueError("QR border must be at least four modules")

    code = qrcode.QRCode(
        version=version,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    code.add_data(data)
    code.make(fit=False)
    image = code.make_image(fill_color="black", back_color="white").convert("RGB")

    expected_side = (qr_matrix_modules(version) + 2 * border) * box_size
    if image.size != (expected_side, expected_side):
        raise ValueError(
            f"Unexpected QR size {image.size}; expected {(expected_side, expected_side)}"
        )
    qr_colors = {color for _, color in image.getcolors(maxcolors=3) or []}
    if qr_colors != {(0, 0, 0), (255, 255, 255)}:
        raise ValueError(f"QR output is not exact black/white: {sorted(qr_colors)}")
    return image


def _center_pixel_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    scale: int,
    box: tuple[int, int, int, int],
    *,
    y: int | None = None,
) -> None:
    text_width, text_height = pixel_text_size(text, scale)
    x = box[0] + (box[2] - box[0] - text_width) // 2
    text_y = box[1] + (box[3] - box[1] - text_height) // 2 if y is None else y
    draw_pixel_text(draw, text, scale, x, text_y)


def _draw_picture_icon(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]) -> None:
    """Draw a simple one-bit picture/icon that survives the small TFT grid."""

    left, top, right, bottom = box
    draw.rectangle((left, top, right, bottom), outline="black", width=3)
    # Sun.
    sun_x = left + (right - left) // 4
    sun_y = top + (bottom - top) // 4
    draw.ellipse((sun_x - 5, sun_y - 5, sun_x + 5, sun_y + 5), fill="black")
    # Two bold mountain silhouettes.
    mid_x = left + (right - left) // 2
    draw.polygon(
        ((left + 7, bottom - 7), (mid_x - 10, top + 30), (mid_x + 5, bottom - 7)),
        fill="black",
    )
    draw.polygon(
        ((mid_x - 2, bottom - 7), (right - 8, top + 18), (right - 3, bottom - 7)),
        fill="black",
    )
    # A white snow notch keeps the icon legible after the device transform.
    draw.polygon(
        ((mid_x - 10, top + 30), (mid_x - 3, top + 37), (mid_x + 2, top + 31)),
        fill="white",
    )


def build_three_panel_sample(qr_data: str = "ESL-A0") -> Image.Image:
    """Build a vertical text / picture / QR demonstration layout."""

    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    draw = ImageDraw.Draw(image)

    # Keep a small outer margin and two pixel-aligned separators. The logical
    # panel widths are approximately 83/83/84 pixels before the gutters.
    draw.rectangle((2, 2, WIDTH - 3, HEIGHT - 3), outline="black", width=2)
    draw.line((82, 4, 82, HEIGHT - 5), fill="black", width=2)
    draw.line((166, 4, 166, HEIGHT - 5), fill="black", width=2)

    left_box = (5, 5, 80, HEIGHT - 6)
    middle_box = (85, 5, 164, HEIGHT - 6)
    right_box = (169, 5, WIDTH - 5, HEIGHT - 6)

    _center_pixel_text(draw, "BLE", 3, left_box, y=18)
    _center_pixel_text(draw, "OK", 4, left_box, y=49)
    draw.line((16, 86, 69, 86), fill="black", width=2)
    _center_pixel_text(draw, "A0", 2, left_box, y=99)

    _draw_picture_icon(draw, (99, 24, 151, 77))
    # A compact progress/bar motif demonstrates non-photographic graphics.
    draw.rectangle((98, 93, 151, 105), outline="black", width=2)
    draw.rectangle((101, 96, 130, 102), fill="black")
    draw.rectangle((134, 96, 148, 102), fill="black")

    qr_image = build_qr(qr_data, version=1, box_size=2)
    qr_x = right_box[0] + (right_box[2] - right_box[0] - qr_image.width) // 2
    qr_y = 13
    image.paste(qr_image, (qr_x, qr_y))
    _center_pixel_text(draw, "QR", 2, right_box, y=98)

    return _to_bw(image)


def build_full_qr_sample(qr_data: str = "ESL-A0-TEST") -> Image.Image:
    """Build a larger QR-only screen for camera distance testing."""

    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    qr_image = build_qr(qr_data, version=2, box_size=3)
    x = (WIDTH - qr_image.width) // 2
    y = (HEIGHT - qr_image.height) // 2
    image.paste(qr_image, (x, y))
    return _to_bw(image)


def _save_sample(path: Path, image: Image.Image) -> dict[str, object]:
    _assert_bw(image)
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG", optimize=False)
    data = path.read_bytes()
    return {
        "file": str(path),
        "sha256": hashlib.sha256(data).hexdigest().upper(),
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
        "file_size": len(data),
        "colors": [
            {"count": count, "rgb": list(rgb)}
            for count, rgb in sorted(image.getcolors(maxcolors=3) or [])
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "images",
        help="Directory for local PNG samples (existing files are never overwritten).",
    )
    parser.add_argument(
        "--qr-data",
        default="ESL-A0",
        help="Short ASCII payload for the three-panel QR sample.",
    )
    parser.add_argument(
        "--full-qr-data",
        default="ESL-A0-TEST",
        help="Payload for the larger QR-only sample.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    outputs = {
        "three_panel": _save_sample(
            output_dir / "three_panel_text_picture_qr.png",
            build_three_panel_sample(args.qr_data),
        ),
        "full_qr": _save_sample(
            output_dir / "qr_full_sample.png",
            build_full_qr_sample(args.full_qr_data),
        ),
    }
    evidence = {
        "created_at": iso_now(),
        "status": "LOCAL_ONLY_READY_FOR_REVIEW",
        "device_writes": 0,
        "write_allowed": False,
        "model": "0xA0 TFT 2.1 BW",
        "logical_dimensions": [WIDTH, HEIGHT],
        "qr": {
            "three_panel_data": args.qr_data,
            "full_qr_data": args.full_qr_data,
            "error_correction": "M",
            "quiet_zone_modules": QR_BORDER_MODULES,
            "three_panel_version": 1,
            "three_panel_box_size": 2,
            "full_qr_version": 2,
            "full_qr_box_size": 3,
        },
        "outputs": outputs,
        "next_gate": "Explicit user approval is required before any BLE image write.",
    }
    evidence_path = unique_path(EVIDENCE_DIR, "layout_samples", ".json")
    write_json_new(evidence_path, evidence)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(f"Evidence: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
