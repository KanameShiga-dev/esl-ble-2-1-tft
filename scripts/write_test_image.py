"""Perform one bounded TEST-image transfer after explicit user approval.

This is the only project script allowed to call BLE write/notify APIs. It
accepts a previously prepared, hash-bound plan and a fresh advertisement scan,
uses only the verified FEF1/FEF2 display path, performs no automatic retries,
and disconnects once the device reports completion.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import struct
from pathlib import Path
from typing import Any, Callable

from bleak import BleakClient

from common import EVIDENCE_DIR, iso_now, unique_path, write_json_new


SERVICE_UUID = "0000fef0-0000-1000-8000-00805f9b34fb"
COMMAND_UUID = "0000fef1-0000-1000-8000-00805f9b34fb"
IMAGE_UUID = "0000fef2-0000-1000-8000-00805f9b34fb"
FORBIDDEN_UUIDS = {
    "0000fef3-0000-1000-8000-00805f9b34fb",
    "00010203-0405-0607-0809-0a0b0c0d1912",
    "00010203-0405-0607-0809-0a0b0c0d2b12",
}
CHUNK_SIZE = 240
EXPECTED_PAYLOAD_BYTES = 4125
MODEL_ID = "0xA0"
MAX_RESPONSE_TIMEOUT = 15.0
MAX_TRANSFER_SECONDS = 90.0


class TransferAbort(RuntimeError):
    """Raised when a precondition, response, or safety check fails."""


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TransferAbort(f"Expected JSON object: {path}")
    return value


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def validate_scan(scan: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    address = profile.get("address")
    matches = [
        candidate
        for candidate in scan.get("candidates", [])
        if candidate.get("address") == address
    ]
    if scan.get("candidate_count") != 1 or len(matches) != 1:
        raise TransferAbort("Fresh scan does not contain exactly one target candidate")
    candidate = matches[0]
    if candidate.get("candidate_model_id") != MODEL_ID:
        raise TransferAbort("Fresh scan model is not 0xA0")
    if SERVICE_UUID not in {str(item).lower() for item in candidate.get("service_uuids", [])}:
        raise TransferAbort("Fresh scan is missing the verified FEF0 service")
    if candidate.get("scan_confidence", 0) < 0.80:
        raise TransferAbort("Fresh scan confidence is below the hard safety threshold")
    return candidate


def validate_plan(
    plan: dict[str, Any], profile: dict[str, Any], scan: dict[str, Any]
) -> tuple[Path, bytes, dict[str, Any]]:
    gates = profile.get("hard_gates", {})
    required = {
        "unique_candidate",
        "power_cycle_verified",
        "model_id_verified",
        "gatt_profile_verified",
        "image_dimensions_verified",
        "non_dfu_write_path_verified",
    }
    missing = sorted(name for name in required if gates.get(name) is not True)
    if missing:
        raise TransferAbort(f"Profile hard gates are incomplete: {', '.join(missing)}")
    if profile.get("candidate_model_id") != MODEL_ID:
        raise TransferAbort("Profile model is not 0xA0")
    if plan.get("target_model_id") != MODEL_ID:
        raise TransferAbort("Write plan model is not 0xA0")
    if plan.get("target_address") != profile.get("address"):
        raise TransferAbort("Write plan and profile addresses do not match")
    if plan.get("user_approval_required") is not True:
        raise TransferAbort("Write plan is missing the explicit-approval requirement")
    if plan.get("write_allowed") is not False:
        raise TransferAbort("Write plan approval state is unexpectedly mutable")
    if set(plan.get("forbidden_uuids", [])) != FORBIDDEN_UUIDS:
        raise TransferAbort("Forbidden UUID guard does not match the audited set")
    validate_scan(scan, profile)

    payload_info = plan.get("payload", {})
    payload_path = Path(payload_info.get("file", "")).resolve()
    if not payload_path.is_file():
        raise TransferAbort(f"Payload does not exist: {payload_path}")
    payload_hash = sha256_file(payload_path)
    payload = payload_path.read_bytes()
    if payload_hash != payload_info.get("sha256"):
        raise TransferAbort("Payload SHA-256 does not match the approved plan")
    if len(payload) != EXPECTED_PAYLOAD_BYTES or payload_info.get("bytes") != len(payload):
        raise TransferAbort("Payload length is not the approved 4,125 bytes")
    expected_chunks = (len(payload) + CHUNK_SIZE - 1) // CHUNK_SIZE
    if payload_info.get("chunk_size") != CHUNK_SIZE or payload_info.get("chunk_count") != expected_chunks:
        raise TransferAbort("Payload chunk plan does not match the bounded writer")
    if any(uuid.lower() in FORBIDDEN_UUIDS for uuid in (COMMAND_UUID, IMAGE_UUID)):
        raise TransferAbort("Display UUID unexpectedly overlaps a forbidden UUID")
    return payload_path, payload, validate_scan(scan, profile)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--scan", required=True, type=Path)
    parser.add_argument(
        "--approve",
        action="store_true",
        help="Required explicit authorization switch for the one test write.",
    )
    parser.add_argument(
        "--approval-note",
        default="ユーザー承認: 進めてください",
        help="Short local record of the user's approval context.",
    )
    parser.add_argument("--connection-timeout", type=float, default=15.0)
    parser.add_argument("--response-timeout", type=float, default=5.0)
    return parser.parse_args()


async def bounded_transfer(
    address: str,
    payload: bytes,
    connection_timeout: float,
    response_timeout: float,
) -> dict[str, Any]:
    if not 5.0 <= connection_timeout <= 60.0:
        raise TransferAbort("Connection timeout must be between 5 and 60 seconds")
    if not 1.0 <= response_timeout <= MAX_RESPONSE_TIMEOUT:
        raise TransferAbort("Response timeout must be between 1 and 15 seconds")

    result: dict[str, Any] = {
        "connected": False,
        "service_preflight": "NOT_RUN",
        "notifications_started": 0,
        "writes": 0,
        "command_writes": 0,
        "image_writes": 0,
        "notifications": [],
        "completed_chunks": 0,
        "disconnected": False,
    }
    notifications: asyncio.Queue[bytes] = asyncio.Queue()
    notify_started = False
    client: BleakClient | None = None

    async def on_notification(_sender: Any, data: bytearray) -> None:
        await notifications.put(bytes(data))

    async def wait_for_notification(
        step: str, predicate: Callable[[bytes], bool]
    ) -> bytes:
        try:
            while True:
                data = await asyncio.wait_for(notifications.get(), response_timeout)
                result["notifications"].append(
                    {"step": step, "length": len(data), "prefix": data[:8].hex().upper()}
                )
                if predicate(data):
                    return data
                raise TransferAbort(
                    f"Unexpected notification during {step}: {data[:8].hex().upper()}"
                )
        except asyncio.TimeoutError as error:
            raise TransferAbort(f"Notification timeout during {step}") from error

    async def write(uuid: str, data: bytes, kind: str) -> None:
        if uuid.lower() in FORBIDDEN_UUIDS:
            raise TransferAbort("Attempted write to a forbidden UUID")
        assert client is not None
        await client.write_gatt_char(uuid, data, response=False)
        result["writes"] += 1
        result[f"{kind}_writes"] += 1

    try:
        client = BleakClient(address, timeout=connection_timeout)
        await client.connect()
        result["connected"] = bool(client.is_connected)
        if not client.is_connected:
            raise TransferAbort("BLE connection did not become active")

        services = client.services
        service = next(
            (item for item in services if item.uuid.lower() == SERVICE_UUID), None
        )
        chars = {
            characteristic.uuid.lower(): characteristic
            for item in services
            for characteristic in item.characteristics
        }
        command = chars.get(COMMAND_UUID)
        image = chars.get(IMAGE_UUID)
        if service is None or command is None or image is None:
            raise TransferAbort("Connected GATT profile no longer matches FEF0/FEF1/FEF2")
        if "notify" not in command.properties:
            raise TransferAbort("FEF1 no longer supports notifications")
        if not ({"write", "write-without-response"} & set(command.properties)):
            raise TransferAbort("FEF1 no longer supports writes")
        if not ({"write", "write-without-response"} & set(image.properties)):
            raise TransferAbort("FEF2 no longer supports writes")
        result["service_preflight"] = "PASS"

        await client.start_notify(command, on_notification)
        notify_started = True
        result["notifications_started"] = 1
        # The independently audited writer waits for CCCD/device state to
        # settle before the first command. This is a fixed delay, not a retry.
        await asyncio.sleep(1.0)

        await write(COMMAND_UUID, b"\x01", "command")
        await wait_for_notification("init", lambda data: data.startswith(b"\x01\xF4\x00"))

        size_command = b"\x02" + struct.pack("<I", len(payload)) + b"\x00\x00\x00"
        await write(COMMAND_UUID, size_command, "command")
        await wait_for_notification("size", lambda data: data.startswith(b"\x02"))

        await write(COMMAND_UUID, b"\x03", "command")
        response = await wait_for_notification(
            "start_image", lambda data: len(data) >= 6 and data[:2] == b"\x05\x00"
        )

        chunks = [payload[offset : offset + CHUNK_SIZE] for offset in range(0, len(payload), CHUNK_SIZE)]
        expected_part = 0
        while True:
            if len(response) < 2 or response[0] != 0x05:
                raise TransferAbort("Malformed image acknowledgement")
            error_code = response[1]
            if error_code == 0x08:
                if expected_part != len(chunks):
                    raise TransferAbort("Device reported completion before all chunks were sent")
                break
            if error_code != 0x00:
                raise TransferAbort(f"Device rejected image chunk with code 0x{error_code:02X}")
            if len(response) < 6:
                raise TransferAbort("Image acknowledgement is missing its part index")
            part = int.from_bytes(response[2:6], "little")
            if part != expected_part:
                raise TransferAbort(
                    f"Device requested part {part}, expected {expected_part}"
                )
            if part == len(chunks):
                break
            packet = struct.pack("<I", part) + chunks[part]
            await write(IMAGE_UUID, packet, "image")
            result["completed_chunks"] = part + 1
            expected_part += 1
            await asyncio.sleep(0.03)
            response = await wait_for_notification(
                f"image_part_{part}", lambda data: len(data) >= 2 and data[0] == 0x05
            )
        result["status"] = "PASS"
    except Exception as error:
        result["status"] = "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if client is not None:
            if notify_started:
                try:
                    await client.stop_notify(COMMAND_UUID)
                except Exception as error:
                    result["stop_notify_error"] = f"{type(error).__name__}: {error}"
            try:
                await client.disconnect()
                result["disconnected"] = True
            except Exception as error:
                result["disconnect_error"] = f"{type(error).__name__}: {error}"
    return result


def main() -> int:
    args = parse_args()
    plan_path = args.plan.resolve()
    profile_path = args.profile.resolve()
    scan_path = args.scan.resolve()
    result: dict[str, Any] = {
        "started_at": iso_now(),
        "status": "BLOCKED",
        "device_writes_performed": 0,
        "automatic_retries": 0,
        "approval_switch": bool(args.approve),
        "approval_note": args.approval_note if args.approve else None,
        "plan": str(plan_path),
        "profile": str(profile_path),
        "scan": str(scan_path),
    }
    try:
        if not args.approve:
            raise TransferAbort("Explicit --approve switch is required")
        plan = load_json(plan_path)
        profile = load_json(profile_path)
        scan = load_json(scan_path)
        payload_path, payload, candidate = validate_plan(plan, profile, scan)
        result["target_address"] = profile["address"]
        result["target_model_id"] = MODEL_ID
        result["fresh_candidate"] = {
            "model_id": candidate.get("candidate_model_id"),
            "confidence": candidate.get("scan_confidence"),
            "rssi_max": candidate.get("rssi_max"),
        }
        result["payload"] = {
            "file": str(payload_path),
            "bytes": len(payload),
            "sha256": sha256_file(payload_path),
        }
        result["user_approval"] = {
            "approved_at": iso_now(),
            "statement": args.approval_note,
            "scope": "one TEST image write to the hash-bound target using FEF1/FEF2 only",
        }
        transfer = asyncio.run(
            asyncio.wait_for(
                bounded_transfer(
                    profile["address"],
                    payload,
                    args.connection_timeout,
                    args.response_timeout,
                ),
                timeout=MAX_TRANSFER_SECONDS,
            )
        )
        result.update(transfer)
        result["device_writes_performed"] = int(transfer.get("writes", 0))
        if result.get("status") == "PASS" and not result.get("disconnected"):
            result["status"] = "FAIL"
            result["error"] = "Transfer completed but disconnect confirmation failed"
    except Exception as error:
        result["status"] = "BLOCKED" if result["device_writes_performed"] == 0 else "FAIL"
        result["error"] = f"{type(error).__name__}: {error}"
    result["completed_at"] = iso_now()
    output_path = unique_path(EVIDENCE_DIR, "write_attempt", ".json")
    write_json_new(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_path}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
