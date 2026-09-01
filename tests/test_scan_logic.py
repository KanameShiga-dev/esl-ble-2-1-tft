from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from scan_ble import classify_advertisement  # noqa: E402


UNRELATED_ADDRESS = ":".join(["AA", "BB", "CC", "DD", "EE", "FF"])
TEST_ADDRESS = ":".join(["FF", "FF", "01", "02", "03", "04"])


class ScanClassificationTests(unittest.TestCase):
    def advertisement(
        self,
        *,
        name: str | None = None,
        services: list[str] | None = None,
        manufacturer: dict[int, bytes] | None = None,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            local_name=name,
            rssi=-42,
            service_uuids=services or [],
            manufacturer_data=manufacturer or {},
            service_data={},
        )

    def test_unrelated_device_is_not_retained(self) -> None:
        result = classify_advertisement(
            UNRELATED_ADDRESS,
            "Headphones",
            self.advertisement(name="Headphones"),
            None,
        )
        self.assertIsNone(result)

    def test_model_a0_payload_is_identified(self) -> None:
        result = classify_advertisement(
            TEST_ADDRESS,
            "NEMR01020304",
            self.advertisement(
                name="NEMR01020304",
                services=["0000fef0-0000-1000-8000-00805f9b34fb"],
                manufacturer={0x5053: bytes([0xA0, 0x29, 0x00, 0x01, 0x02])},
            ),
            "01020304",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["candidate_model_id"], "0xA0")
        self.assertEqual(result["candidate_model"], "TFT 2.1 BW")
        self.assertEqual(result["scan_confidence"], 1.0)

    def test_suffix_match_can_retain_unnamed_candidate(self) -> None:
        result = classify_advertisement(
            TEST_ADDRESS,
            None,
            self.advertisement(),
            "01020304",
        )
        self.assertIsNotNone(result)
        assert result is not None
        self.assertIn("front_label_hex_suffix_match", result["evidence"])


if __name__ == "__main__":
    unittest.main()
