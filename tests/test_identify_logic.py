from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from identify_device import (  # noqa: E402
    apply_gatt_evidence,
    apply_power_cycle_evidence,
    apply_protocol_assessment,
)
from verify_power_cycle import assess_power_cycle  # noqa: E402


TEST_ADDRESS = ":".join(["FF", "FF", "01", "02", "03", "04"])
OTHER_ADDRESS = ":".join(["FF", "FF", "AA", "BB", "CC", "DD"])


class GattEvidenceTests(unittest.TestCase):
    def base_profile(self) -> dict:
        return {
            "address": TEST_ADDRESS,
            "status": "PASS",
            "reason": None,
            "evidence": [],
            "hard_gates": {"gatt_profile_verified": False},
            "write_allowed": False,
        }

    def write_gatt(self, directory: Path, *, address: str) -> Path:
        payload = {
            "address": address,
            "connected": True,
            "writes": 0,
            "notifications_started": 0,
            "service_count": 1,
            "characteristic_count": 2,
            "services": [
                {
                    "uuid": "0000fef0-0000-1000-8000-00805f9b34fb",
                    "characteristics": [
                        {"uuid": "0000fef1-0000-1000-8000-00805f9b34fb"},
                        {"uuid": "0000fef2-0000-1000-8000-00805f9b34fb"},
                    ],
                }
            ],
        }
        path = directory / "gatt.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_matching_safe_gatt_capture_sets_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path = self.write_gatt(
                Path(directory_name), address=TEST_ADDRESS
            )
            profile = self.base_profile()
            apply_gatt_evidence(profile, path)
        self.assertTrue(profile["hard_gates"]["gatt_profile_verified"])
        self.assertIn("gatt_fef0_fef1_fef2_match", profile["evidence"])
        self.assertFalse(profile["write_allowed"])

    def test_address_mismatch_blocks_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            path = self.write_gatt(
                Path(directory_name), address=OTHER_ADDRESS
            )
            profile = self.base_profile()
            apply_gatt_evidence(profile, path)
        self.assertEqual(profile["status"], "BLOCKED")
        self.assertFalse(profile["write_allowed"])


class PowerCycleAndProtocolTests(unittest.TestCase):
    def profile(self) -> dict:
        return {
            "address": TEST_ADDRESS,
            "candidate_model_id": "0xA0",
            "manufacturer_data": {"0x5053": "A01E810140"},
            "evidence": [],
            "hard_gates": {
                "power_cycle_verified": False,
                "image_dimensions_verified": False,
                "non_dfu_write_path_verified": False,
            },
            "write_allowed": False,
        }

    def candidate(self) -> dict:
        return {
            "address": TEST_ADDRESS,
            "candidate_model_id": "0xA0",
            "manufacturer_data": {"0x5053": "A01E810140"},
        }

    def test_power_cycle_requires_absence_then_exact_reappearance(self) -> None:
        result = assess_power_cycle(
            self.profile(),
            {"candidate_count": 0, "candidates": []},
            {"candidate_count": 1, "candidates": [self.candidate()]},
        )
        self.assertEqual(result["status"], "PASS")
        self.assertFalse(result["write_allowed"])

    def test_evidence_application_never_enables_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            power_path = directory / "power.json"
            power_path.write_text(
                json.dumps(
                    {
                        "status": "PASS",
                        "target_address": TEST_ADDRESS,
                        "off_scan_target_absent": True,
                        "on_scan_single_exact_match": True,
                        "writes": 0,
                    }
                ),
                encoding="utf-8",
            )
            protocol_path = directory / "protocol.json"
            protocol_path.write_text(
                json.dumps(
                    {
                        "model_id": "0xA0",
                        "image_dimensions_verified": True,
                        "logical_dimensions": {"width": 250, "height": 132},
                        "display_update_path": {
                            "non_dfu_write_path_verified": True
                        },
                    }
                ),
                encoding="utf-8",
            )
            profile = self.profile()
            apply_power_cycle_evidence(profile, power_path)
            apply_protocol_assessment(profile, protocol_path)
        self.assertTrue(profile["hard_gates"]["power_cycle_verified"])
        self.assertTrue(profile["hard_gates"]["image_dimensions_verified"])
        self.assertTrue(profile["hard_gates"]["non_dfu_write_path_verified"])
        self.assertFalse(profile["write_allowed"])


if __name__ == "__main__":
    unittest.main()
