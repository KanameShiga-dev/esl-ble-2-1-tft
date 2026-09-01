"""Scan BLE advertisements without connecting, notifying, pairing, or writing."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from typing import Any

from bleak import BleakScanner

from common import LOG_DIR, bytes_map_to_hex, configure_logging, iso_now, unique_path, write_json_new


GICISKY_SERVICE_UUID = "0000fef0-0000-1000-8000-00805f9b34fb"
GICISKY_MANUFACTURER_ID = 0x5053
KNOWN_NAME_MARKERS = ("PICKSMART", "NEMR", "GICISKY", "TFT_ESL")


def compact_identifier(value: str | None) -> str:
    return re.sub(r"[^0-9A-F]", "", (value or "").upper())


def classify_advertisement(
    address: str,
    device_name: str | None,
    advertisement: Any,
    expected_suffix: str | None,
) -> dict[str, Any] | None:
    local_name = advertisement.local_name or device_name or ""
    upper_name = local_name.upper()
    service_uuids = sorted({str(value).lower() for value in advertisement.service_uuids})
    manufacturer_data = dict(advertisement.manufacturer_data)
    reasons: list[str] = []
    confidence = 0.0

    if any(marker in upper_name for marker in KNOWN_NAME_MARKERS):
        reasons.append("known_name_pattern")
        confidence += 0.25

    suffix = compact_identifier(expected_suffix)
    if suffix and (
        suffix in compact_identifier(local_name)
        or suffix in compact_identifier(address)
    ):
        reasons.append("front_label_hex_suffix_match")
        confidence += 0.30

    if GICISKY_SERVICE_UUID in service_uuids:
        reasons.append("gicisky_service_uuid")
        confidence += 0.20

    model_id: int | None = None
    vendor_payload = manufacturer_data.get(GICISKY_MANUFACTURER_ID)
    if vendor_payload:
        reasons.append("manufacturer_id_0x5053")
        confidence += 0.15
        model_id = int(vendor_payload[0])
        if model_id == 0xA0:
            reasons.append("advertised_model_id_0xA0")
            confidence += 0.30

    if not reasons:
        return None

    model_name = "TFT 2.1 BW" if model_id == 0xA0 else None
    return {
        "observed_at": iso_now(),
        "name": local_name or None,
        "address": address,
        "rssi_last": int(advertisement.rssi),
        "rssi_min": int(advertisement.rssi),
        "rssi_max": int(advertisement.rssi),
        "rssi_sample_count": 1,
        "service_uuids": service_uuids,
        "manufacturer_data": bytes_map_to_hex(manufacturer_data),
        "service_data": bytes_map_to_hex(dict(advertisement.service_data)),
        "candidate_model_id": f"0x{model_id:02X}" if model_id is not None else None,
        "candidate_model": model_name,
        "scan_confidence": round(min(confidence, 1.0), 2),
        "evidence": reasons,
    }


def merge_observation(existing: dict[str, Any], current: dict[str, Any]) -> None:
    rssi = current["rssi_last"]
    existing["observed_at"] = current["observed_at"]
    existing["rssi_last"] = rssi
    existing["rssi_min"] = min(existing["rssi_min"], rssi)
    existing["rssi_max"] = max(existing["rssi_max"], rssi)
    existing["rssi_sample_count"] += 1
    if current["scan_confidence"] > existing["scan_confidence"]:
        for key in (
            "name",
            "service_uuids",
            "manufacturer_data",
            "service_data",
            "candidate_model_id",
            "candidate_model",
            "scan_confidence",
            "evidence",
        ):
            existing[key] = current[key]


async def perform_scan(duration: float, expected_suffix: str | None) -> dict[str, Any]:
    started_at = iso_now()
    observed_addresses: set[str] = set()
    candidates: dict[str, dict[str, Any]] = {}

    def on_detection(device: Any, advertisement: Any) -> None:
        observed_addresses.add(device.address)
        candidate = classify_advertisement(
            device.address,
            device.name,
            advertisement,
            expected_suffix,
        )
        if candidate is None:
            return
        existing = candidates.get(device.address)
        if existing is None:
            candidates[device.address] = candidate
        else:
            merge_observation(existing, candidate)

    scanner = BleakScanner(detection_callback=on_detection)
    async with scanner:
        await asyncio.sleep(duration)

    ordered = sorted(
        candidates.values(),
        key=lambda item: (item["scan_confidence"], item["rssi_max"]),
        reverse=True,
    )
    return {
        "started_at": started_at,
        "completed_at": iso_now(),
        "duration_seconds": duration,
        "total_devices_observed": len(observed_addresses),
        "non_candidate_count": len(observed_addresses) - len(candidates),
        "candidate_count": len(ordered),
        "privacy": "Non-candidate names and addresses were not retained.",
        "candidates": ordered,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--duration", type=float, default=20.0)
    parser.add_argument(
        "--expected-suffix",
        help="Optional hexadecimal suffix derived from the physical label.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 5.0 <= args.duration <= 120.0:
        raise SystemExit("--duration must be between 5 and 120 seconds")

    logger, log_path = configure_logging("ble_scan")
    logger.info("BLE advertisement scan started duration=%.1fs", args.duration)
    try:
        result = asyncio.run(perform_scan(args.duration, args.expected_suffix))
    except Exception:
        logger.exception("BLE advertisement scan failed")
        return 1

    output_path = unique_path(LOG_DIR, "ble_scan", ".json")
    write_json_new(output_path, result)
    logger.info(
        "BLE scan completed devices=%d candidates=%d",
        result["total_devices_observed"],
        result["candidate_count"],
    )
    for candidate in result["candidates"]:
        logger.info(
            "Candidate name=%s address=%s rssi_max=%s confidence=%.2f evidence=%s",
            candidate["name"],
            candidate["address"],
            candidate["rssi_max"],
            candidate["scan_confidence"],
            ",".join(candidate["evidence"]),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"JSON: {output_path}")
    print(f"Log:  {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
