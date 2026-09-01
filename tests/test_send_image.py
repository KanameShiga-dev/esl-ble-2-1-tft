from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from prepare_payload import build_payload  # noqa: E402
from send_image import (  # noqa: E402
    SimpleSendError,
    make_local_plan,
    normalize_image,
    profile_is_ready,
    select_verified_profile,
)


def ready_profile(address: str) -> dict[str, object]:
    return {
        "candidate_model_id": "0xA0",
        "address": address,
        "hard_gates": {
            "unique_candidate": True,
            "power_cycle_verified": True,
            "model_id_verified": True,
            "gatt_profile_verified": True,
            "image_dimensions_verified": True,
            "non_dfu_write_path_verified": True,
        },
    }


class NormalizeImageTests(unittest.TestCase):
    def test_gray_image_is_converted_to_exact_bw_payload(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "gray.png"
            image = Image.new("L", (250, 132), 192)
            image.paste(32, (0, 0, 125, 132))
            image.save(path)

            normalized, metadata = normalize_image(path)

            self.assertEqual(normalized.size, (250, 132))
            self.assertEqual(normalized.mode, "RGB")
            colors = {color for _, color in normalized.getcolors(maxcolors=3) or []}
            self.assertEqual(colors, {(0, 0, 0), (255, 255, 255)})
            self.assertEqual(len(build_payload(normalized)), 4125)
            self.assertEqual(
                metadata["black_pixels"] + metadata["white_pixels"],
                250 * 132,
            )

    def test_wrong_size_has_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "wrong.png"
            Image.new("RGB", (249, 132), "white").save(path)

            with self.assertRaisesRegex(SimpleSendError, "必要: 250x132"):
                normalize_image(path)


class ProfileSelectionTests(unittest.TestCase):
    def write_profile(
        self,
        directory: Path,
        name: str,
        profile: dict[str, object],
        mtime: int,
    ) -> Path:
        path = directory / name
        path.write_text(
            json.dumps(profile, ensure_ascii=False),
            encoding="utf-8",
        )
        os.utime(path, (mtime, mtime))
        return path

    def test_latest_ready_profile_for_same_device_is_selected(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.write_profile(
                directory,
                "device_profile_old.json",
                ready_profile("device-a"),
                100,
            )
            newest = self.write_profile(
                directory,
                "device_profile_new.json",
                ready_profile("device-a"),
                200,
            )

            selected_path, selected = select_verified_profile(
                evidence_dir=directory
            )

            self.assertEqual(selected_path, newest)
            self.assertEqual(selected["address"], "device-a")

    def test_multiple_verified_devices_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            self.write_profile(
                directory,
                "device_profile_a.json",
                ready_profile("device-a"),
                100,
            )
            self.write_profile(
                directory,
                "device_profile_b.json",
                ready_profile("device-b"),
                200,
            )

            with self.assertRaisesRegex(SimpleSendError, "複数"):
                select_verified_profile(evidence_dir=directory)

    def test_public_example_profile_cannot_be_selected_for_writing(self) -> None:
        example_path = PROJECT_ROOT / "examples" / "device_profile.example.json"
        example = json.loads(example_path.read_text(encoding="utf-8"))

        self.assertFalse(profile_is_ready(example))
        self.assertFalse(example["write_allowed"])
        self.assertTrue(
            all(value is False for value in example["hard_gates"].values())
        )


class LocalPlanTests(unittest.TestCase):
    def test_plan_is_hash_bound_and_requires_confirmation(self) -> None:
        payload = bytes([0xAA]) * 4125
        profile = ready_profile("device-a")
        plan = make_local_plan(
            image_metadata={
                "file": "sample.png",
                "source_sha256": "ABC",
                "source_mode": "RGB",
                "width": 250,
                "height": 132,
                "black_pixels": 1,
                "white_pixels": 32999,
                "conversion": "threshold_128_to_exact_bw",
            },
            payload=payload,
            profile_path=Path("profile.json"),
            profile=profile,
            scan_path=Path("scan.json"),
        )

        self.assertEqual(plan["payload"]["bytes"], 4125)
        self.assertEqual(plan["payload"]["chunk_count"], 18)
        self.assertEqual(plan["planned_writes"]["total"], 21)
        self.assertEqual(plan["confirmation_phrase"], "SEND")
        self.assertEqual(plan["automatic_retries"], 0)
        self.assertEqual(plan["device_writes_performed"], 0)


if __name__ == "__main__":
    unittest.main()
