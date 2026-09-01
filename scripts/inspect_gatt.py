"""Connect to one explicit BLE address and enumerate GATT without writes/notify."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from bleak import BleakClient

from common import LOG_DIR, configure_logging, iso_now, unique_path, write_json_new


SAFE_STANDARD_READ_UUIDS = {
    "00002a00-0000-1000-8000-00805f9b34fb",  # Device Name
    "00002a01-0000-1000-8000-00805f9b34fb",  # Appearance
    "00002a19-0000-1000-8000-00805f9b34fb",  # Battery Level
    "00002a24-0000-1000-8000-00805f9b34fb",  # Model Number
    "00002a26-0000-1000-8000-00805f9b34fb",  # Firmware Revision
    "00002a27-0000-1000-8000-00805f9b34fb",  # Hardware Revision
    "00002a28-0000-1000-8000-00805f9b34fb",  # Software Revision
    "00002a29-0000-1000-8000-00805f9b34fb",  # Manufacturer Name
}


def readable_text(value: bytes) -> str | None:
    try:
        text = value.decode("utf-8").strip("\x00")
    except UnicodeDecodeError:
        return None
    return text if text.isprintable() else None


async def inspect(address: str, timeout: float, read_standard: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "started_at": iso_now(),
        "address": address,
        "mode": "enumerate_and_standard_read" if read_standard else "enumerate_only",
        "writes": 0,
        "notifications_started": 0,
        "services": [],
    }
    async with BleakClient(address, timeout=timeout) as client:
        result["connected"] = bool(client.is_connected)
        for service in client.services:
            service_record: dict[str, Any] = {
                "uuid": service.uuid,
                "description": service.description,
                "handle": service.handle,
                "characteristics": [],
            }
            for characteristic in service.characteristics:
                characteristic_record: dict[str, Any] = {
                    "uuid": characteristic.uuid,
                    "description": characteristic.description,
                    "handle": characteristic.handle,
                    "properties": sorted(characteristic.properties),
                    "descriptors": [
                        {
                            "uuid": descriptor.uuid,
                            "description": descriptor.description,
                            "handle": descriptor.handle,
                        }
                        for descriptor in characteristic.descriptors
                    ],
                }
                normalized_uuid = characteristic.uuid.lower()
                if (
                    read_standard
                    and "read" in characteristic.properties
                    and normalized_uuid in SAFE_STANDARD_READ_UUIDS
                ):
                    try:
                        value = bytes(await client.read_gatt_char(characteristic))
                        characteristic_record["read"] = {
                            "status": "PASS",
                            "hex": value.hex().upper(),
                            "text": readable_text(value),
                        }
                    except Exception as error:
                        characteristic_record["read"] = {
                            "status": "FAIL",
                            "error": f"{type(error).__name__}: {error}",
                        }
                service_record["characteristics"].append(characteristic_record)
            result["services"].append(service_record)
    result["completed_at"] = iso_now()
    result["service_count"] = len(result["services"])
    result["characteristic_count"] = sum(
        len(service["characteristics"]) for service in result["services"]
    )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", required=True, help="Exact target address from a saved scan")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--read-standard",
        action="store_true",
        help="Read only an allow-list of standard Device Information/GAP values.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 5.0 <= args.timeout <= 60.0:
        raise SystemExit("--timeout must be between 5 and 60 seconds")
    logger, log_path = configure_logging("gatt")
    logger.info("GATT inspection started address=%s", args.address)
    try:
        result = asyncio.run(inspect(args.address, args.timeout, args.read_standard))
    except Exception as error:
        logger.error("GATT inspection failed type=%s error=%s", type(error).__name__, error)
        return 1
    output_path = unique_path(LOG_DIR, "gatt", ".json")
    write_json_new(output_path, result)
    logger.info(
        "GATT inspection completed services=%d characteristics=%d writes=0 notify=0",
        result["service_count"],
        result["characteristic_count"],
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"JSON: {output_path}")
    print(f"Log:  {log_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
