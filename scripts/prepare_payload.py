"""Prepare and document a TFT payload locally; this script has no BLE access."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from PIL import Image
from gicisky.image.conversion import convert_to_gicisky_bytes

from common import EVIDENCE_DIR, iso_now, unique_path, write_json_new


MODEL_ID = 0xA0
LOGICAL_SIZE = (250, 132)
COMMAND_UUID = "0000fef1-0000-1000-8000-00805f9b34fb"
IMAGE_UUID = "0000fef2-0000-1000-8000-00805f9b34fb"
FORBIDDEN_UUIDS = {
    "0000fef3-0000-1000-8000-00805f9b34fb",
    "00010203-0405-0607-0809-0a0b0c0d1912",
    "00010203-0405-0607-0809-0a0b0c0d2b12",
}
CHUNK_SIZE = 240


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def build_payload(image: Image.Image) -> bytes:
    if image.size != LOGICAL_SIZE:
        raise ValueError(f"Expected image size {LOGICAL_SIZE}, got {image.size}")
    transformed = image.convert("RGB").resize((125, 264), Image.Resampling.BICUBIC)
    transformed = transformed.rotate(90, expand=True)
    pixels = transformed.load()
    width, height = transformed.size

    payload = bytearray()
    current_byte = 0
    bit_position = 7
    for y in range(height):
        for x in range(width - 1, -1, -1):
            r, g, b = pixels[x, y]
            if r > 128 and g > 128 and b > 128:
                current_byte |= 1 << bit_position
            bit_position -= 1
            if bit_position < 0:
                payload.append(current_byte)
                current_byte = 0
                bit_position = 7
    if bit_position != 7:
        payload.append(current_byte)
    return bytes(payload)


def validate_gates(profile: dict[str, Any], protocol: dict[str, Any]) -> None:
    required_profile_gates = {
        "unique_candidate",
        "power_cycle_verified",
        "model_id_verified",
        "gatt_profile_verified",
        "image_dimensions_verified",
        "non_dfu_write_path_verified",
    }
    gates = profile.get("hard_gates", {})
    missing = sorted(name for name in required_profile_gates if gates.get(name) is not True)
    if missing:
        raise ValueError(f"Profile hard gates are incomplete: {', '.join(missing)}")
    if profile.get("candidate_model_id") != "0xA0":
        raise ValueError("Profile is not model 0xA0")
    if protocol.get("model_id") != "0xA0":
        raise ValueError("Protocol assessment is not model 0xA0")
    if protocol.get("logical_dimensions") != {
        "width": 250,
        "height": 132,
        "color_mode": "BW",
    }:
        raise ValueError("Protocol dimensions/color mode do not match the approved layout")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--protocol", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    image_path = args.image.resolve()
    profile = load_json(args.profile)
    protocol = load_json(args.protocol)
    validate_gates(profile, protocol)

    with Image.open(image_path) as opened:
        image = opened.convert("RGB")
    payload = build_payload(image)
    if len(payload) != 4125:
        raise SystemExit(f"Unexpected payload length: {len(payload)}")

    output_path = (args.output or image_path.with_suffix(".payload.bin")).resolve()
    if output_path.exists():
        raise SystemExit(f"Refusing to overwrite existing file: {output_path}")
    output_path.write_bytes(payload)

    installed_library_payload = convert_to_gicisky_bytes(image, MODEL_ID)
    chunk_count = math.ceil(len(payload) / CHUNK_SIZE)
    plan = {
        "prepared_at": iso_now(),
        "status": "READY_FOR_USER_REVIEW",
        "target_address": profile["address"],
        "target_model_id": profile["candidate_model_id"],
        "logical_image": {
            "file": str(image_path),
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest().upper(),
            "width": image.width,
            "height": image.height,
            "mode": image.mode,
        },
        "payload": {
            "file": str(output_path),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            "bytes": len(payload),
            "chunk_size": CHUNK_SIZE,
            "chunk_count": chunk_count,
            "last_chunk_bytes": len(payload) % CHUNK_SIZE,
            "compression": False,
        },
        "audited_transform": {
            "logical_size": [250, 132],
            "tft_resize": [125, 264],
            "rotation_degrees": 90,
            "mirror_x": True,
        },
        "installed_gicisky_comparison": {
            "bytes": len(installed_library_payload),
            "sha256": hashlib.sha256(installed_library_payload).hexdigest().upper(),
            "identical_to_audited_transform": installed_library_payload == payload,
        },
        "planned_device_operations": [
            {"uuid": COMMAND_UUID, "operation": "start notify", "count": 1},
            {"uuid": COMMAND_UUID, "operation": "init command 0x01", "bytes": 1},
            {"uuid": COMMAND_UUID, "operation": "size command 0x02", "bytes": 8},
            {"uuid": COMMAND_UUID, "operation": "start image command 0x03", "bytes": 1},
            {"uuid": IMAGE_UUID, "operation": "indexed image chunks", "count": chunk_count},
            {"operation": "disconnect to refresh", "count": 1},
        ],
        "forbidden_uuids": sorted(FORBIDDEN_UUIDS),
        "automatic_retries": 0,
        "device_writes_performed": 0,
        "user_approval_required": True,
        "write_allowed": False,
    }
    evidence_path = unique_path(EVIDENCE_DIR, "write_plan", ".json")
    write_json_new(evidence_path, plan)
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    print(f"Plan: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
