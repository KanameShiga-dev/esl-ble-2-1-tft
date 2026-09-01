from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from prepare_payload import build_payload  # noqa: E402
from render_layout_samples import (  # noqa: E402
    build_full_qr_sample,
    build_qr,
    build_three_panel_sample,
    qr_matrix_modules,
)


class LayoutSampleTests(unittest.TestCase):
    def assert_exact_bw_frame(self, image) -> None:
        self.assertEqual(image.size, (250, 132))
        self.assertEqual(image.mode, "RGB")
        colors = {color for _, color in image.getcolors(maxcolors=3) or []}
        self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})

    def test_three_panel_sample_is_exact_bw_frame(self) -> None:
        image = build_three_panel_sample("ESL-A0")
        self.assert_exact_bw_frame(image)
        # Separators are deliberately integer-aligned and span the content.
        self.assertEqual(image.getpixel((82, 60)), (0, 0, 0))
        self.assertEqual(image.getpixel((166, 60)), (0, 0, 0))

    def test_full_qr_sample_is_exact_bw_frame(self) -> None:
        image = build_full_qr_sample("ESL-A0-TEST")
        self.assert_exact_bw_frame(image)
        black_pixels = sum(
            image.getpixel((x, y)) == (0, 0, 0)
            for y in range(image.height)
            for x in range(image.width)
        )
        self.assertGreater(black_pixels, 1000)

    def test_qr_has_four_module_quiet_zone_and_expected_size(self) -> None:
        self.assertEqual(qr_matrix_modules(1), 21)
        qr = build_qr("ESL-A0", version=1, box_size=2)
        self.assertEqual(qr.size, (58, 58))
        # Four modules at two pixels/module means eight white pixels around
        # the encoded matrix on each edge.
        for coordinate in range(58):
            self.assertEqual(qr.getpixel((coordinate, 0)), (255, 255, 255))
            self.assertEqual(qr.getpixel((0, coordinate)), (255, 255, 255))

    def test_layout_payload_matches_model_size(self) -> None:
        payload = build_payload(build_three_panel_sample("ESL-A0"))
        self.assertEqual(len(payload), 4125)


if __name__ == "__main__":
    unittest.main()
