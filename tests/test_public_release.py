from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from check_public_release import (  # noqa: E402
    find_embedded_image_metadata,
    find_private_markers,
    path_is_forbidden,
    private_ipv4_values,
)


class PublicPathTests(unittest.TestCase):
    def test_machine_local_artifacts_are_forbidden(self) -> None:
        forbidden = [
            ".venv/Scripts/python.exe",
            "logs/ble_scan.json",
            "evidence/device_profile.json",
            "images/generated.payload.bin",
            "reports/assets/device_example.jpg",
            "reports/assets/qr_decode_result.jpg",
            "reports/display_results_report.html",
            ".env.local",
            "private/device.key",
        ]
        for path in forbidden:
            with self.subTest(path=path):
                self.assertTrue(path_is_forbidden(path))

    def test_public_sources_are_allowed(self) -> None:
        allowed = [
            "SEND_IMAGE.cmd",
            "logs/.gitkeep",
            "scripts/send_image.py",
            "config/protocol_model_a0.json",
            "examples/device_profile.example.json",
            "reports/assets/sample_clear_v3.png",
            "reports/esl_ble_2_1_tft_development_specification.html",
        ]
        for path in allowed:
            with self.subTest(path=path):
                self.assertFalse(path_is_forbidden(path))


class PublicContentTests(unittest.TestCase):
    def test_embedded_jpeg_metadata_is_detected(self) -> None:
        samples = {
            b"jpeg-prefix Exif\x00\x00 payload": "embedded EXIF metadata",
            b"jpeg-prefix http://ns.adobe.com/xap/1.0/ payload": "embedded XMP metadata",
            b"jpeg-prefix ICC_PROFILE\x00 payload": "embedded ICC profile",
        }
        for data, expected in samples.items():
            with self.subTest(expected=expected):
                self.assertIn(expected, find_embedded_image_metadata(data))

    def test_metadata_free_jpeg_is_allowed(self) -> None:
        self.assertEqual(find_embedded_image_metadata(b"JFIF image data"), [])

    def test_private_identifiers_are_detected(self) -> None:
        samples = {
            r"C:" + r"\Users\example\project": "machine-specific absolute path",
            "AA:BB:" + "CC:DD:EE:FF": "MAC-like address",
            "person" + "@example.test": "email address",
            "192.168." + "10.25": "private IPv4 address",
            "api_" + 'key = "real-looking-value"': "possible embedded credential",
        }
        for text, expected in samples.items():
            with self.subTest(text=text):
                self.assertIn(expected, find_private_markers(text))

    def test_placeholders_and_protocol_values_are_allowed(self) -> None:
        text = (
            "<EXACT_ADDRESS> <LOCAL_PATH> FEF0 "
            "0000fef0-0000-1000-8000-00805f9b34fb"
        )
        self.assertEqual(find_private_markers(text), [])

    def test_loopback_is_not_treated_as_private_device_address(self) -> None:
        self.assertEqual(private_ipv4_values("127.0.0.1"), [])


if __name__ == "__main__":
    unittest.main()
