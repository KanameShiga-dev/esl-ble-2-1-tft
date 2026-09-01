from __future__ import annotations

import sys
import unittest
from pathlib import Path

from PIL import Image


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from prepare_payload import build_payload  # noqa: E402
from render_clear_sample import build_clear_sample, build_pixel_sample  # noqa: E402
from render_test_image import build_test_image  # noqa: E402


class PayloadTests(unittest.TestCase):
    def test_clear_sample_is_bw_and_correct_size(self) -> None:
        image = build_clear_sample(top_safe_margin=10)
        self.assertEqual(image.size, (250, 132))
        self.assertEqual(image.mode, "RGB")
        colors = {color for _, color in image.getcolors(maxcolors=3) or []}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})
        black_pixels = sum(
            image.getpixel((x, y)) == (0, 0, 0)
            for y in range(image.height)
            for x in range(image.width)
        )
        self.assertGreater(black_pixels, 1500)

    def test_pixel_sample_is_bw_and_correct_size(self) -> None:
        image = build_pixel_sample(top_safe_margin=10, title_scale=4)
        self.assertEqual(image.size, (250, 132))
        self.assertEqual(image.mode, "RGB")
        colors = {color for _, color in image.getcolors(maxcolors=3) or []}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})

    def test_test_image_is_exact_bw_and_correct_size(self) -> None:
        image = build_test_image("2026-08-26T19:00:00+09:00")
        self.assertEqual(image.size, (250, 132))
        self.assertEqual(image.mode, "RGB")
        colors = {color for _, color in image.getcolors(maxcolors=3) or []}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})

    def test_white_payload_is_expected_length_and_all_ones(self) -> None:
        payload = build_payload(Image.new("RGB", (250, 132), "white"))
        self.assertEqual(len(payload), 4125)
        self.assertEqual(set(payload), {0xFF})

    def test_black_payload_is_expected_length_and_all_zeroes(self) -> None:
        payload = build_payload(Image.new("RGB", (250, 132), "black"))
        self.assertEqual(len(payload), 4125)
        self.assertEqual(set(payload), {0x00})


if __name__ == "__main__":
    unittest.main()
