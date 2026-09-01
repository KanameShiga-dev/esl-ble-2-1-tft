"""Combine completed scan JSON files into a cautious device profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import EVIDENCE_DIR, iso_now, timestamp_slug, write_json_new


def load_scan(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if "candidates" not in payload:
        raise ValueError(f"Not a scan result: {path}")
    return payload


def build_profile(scan_paths: list[Path]) -> dict[str, Any]:
    observations: dict[str, dict[str, Any]] = {}
    for scan_path in scan_paths:
        scan = load_scan(scan_path)
        for candidate in scan["candidates"]:
            address = candidate["address"]
            item = observations.setdefault(
                address,
                {"candidate": candidate, "scan_files": [], "scan_count": 0},
            )
            item["scan_files"].append(str(scan_path))
            item["scan_count"] += 1
            if candidate["scan_confidence"] > item["candidate"]["scan_confidence"]:
                item["candidate"] = candidate

    ranked = sorted(
        observations.values(),
        key=lambda item: (
            item["candidate"]["scan_confidence"],
            item["scan_count"],
            item["candidate"]["rssi_max"],
        ),
        reverse=True,
    )
    if not ranked:
        return {
            "created_at": iso_now(),
            "status": "BLOCKED",
            "reason": "No ESL candidate appeared in the supplied scans.",
            "write_allowed": False,
        }

    best = ranked[0]
    candidate = best["candidate"]
    ambiguous = len(ranked) > 1 and (
        ranked[1]["candidate"]["scan_confidence"]
        >= candidate["scan_confidence"] - 0.10
    )
    evidence = list(candidate["evidence"])
    if best["scan_count"] >= 2:
        evidence.append(f"observed_in_{best['scan_count']}_scans")

    hard_gates = {
        "unique_candidate": not ambiguous,
        "power_cycle_verified": False,
        "model_id_verified": candidate["candidate_model_id"] == "0xA0",
        "gatt_profile_verified": False,
        "image_dimensions_verified": False,
        "non_dfu_write_path_verified": False,
        "user_device_write_approval": False,
    }
    return {
        "created_at": iso_now(),
        "status": "PASS" if not ambiguous else "BLOCKED",
        "reason": None if not ambiguous else "Multiple similarly ranked candidates remain.",
        "observed_name": candidate["name"],
        "address": candidate["address"],
        "rssi_max": candidate["rssi_max"],
        "manufacturer_data": candidate["manufacturer_data"],
        "service_uuids": candidate["service_uuids"],
        "service_data": candidate["service_data"],
        "candidate_family": "Gicisky/PICKSMART",
        "candidate_model": candidate["candidate_model"],
        "candidate_model_id": candidate["candidate_model_id"],
        "confidence": candidate["scan_confidence"],
        "evidence": evidence,
        "scan_files": best["scan_files"],
        "hard_gates": hard_gates,
        "write_allowed": False,
    }


def apply_gatt_evidence(profile: dict[str, Any], gatt_path: Path) -> None:
    with gatt_path.open(encoding="utf-8") as handle:
        gatt = json.load(handle)

    if profile.get("address") != gatt.get("address"):
        profile["status"] = "BLOCKED"
        profile["reason"] = "GATT evidence address does not match the scan profile."
        profile["write_allowed"] = False
        return

    services = {service["uuid"].lower(): service for service in gatt.get("services", [])}
    gicisky_service = services.get("0000fef0-0000-1000-8000-00805f9b34fb")
    characteristic_uuids = {
        characteristic["uuid"].lower()
        for service in gatt.get("services", [])
        for characteristic in service.get("characteristics", [])
    }
    required_characteristics = {
        "0000fef1-0000-1000-8000-00805f9b34fb",
        "0000fef2-0000-1000-8000-00805f9b34fb",
    }
    safe_capture = (
        gatt.get("connected") is True
        and gatt.get("writes") == 0
        and gatt.get("notifications_started") == 0
    )
    matched = (
        gicisky_service is not None
        and required_characteristics.issubset(characteristic_uuids)
        and safe_capture
    )
    profile["gatt_file"] = str(gatt_path)
    profile["gatt_summary"] = {
        "connected": gatt.get("connected"),
        "service_count": gatt.get("service_count"),
        "characteristic_count": gatt.get("characteristic_count"),
        "required_fef0_fef1_fef2_match": matched,
        "writes": gatt.get("writes"),
        "notifications_started": gatt.get("notifications_started"),
    }
    profile["hard_gates"]["gatt_profile_verified"] = matched
    if matched and "gatt_fef0_fef1_fef2_match" not in profile["evidence"]:
        profile["evidence"].append("gatt_fef0_fef1_fef2_match")


def apply_power_cycle_evidence(profile: dict[str, Any], evidence_path: Path) -> None:
    with evidence_path.open(encoding="utf-8") as handle:
        evidence = json.load(handle)
    matched = (
        evidence.get("status") == "PASS"
        and evidence.get("target_address") == profile.get("address")
        and evidence.get("off_scan_target_absent") is True
        and evidence.get("on_scan_single_exact_match") is True
        and evidence.get("writes") == 0
    )
    profile["power_cycle_file"] = str(evidence_path)
    profile["hard_gates"]["power_cycle_verified"] = matched
    if matched and "power_off_absent_on_reappeared" not in profile["evidence"]:
        profile["evidence"].append("power_off_absent_on_reappeared")


def apply_protocol_assessment(profile: dict[str, Any], assessment_path: Path) -> None:
    with assessment_path.open(encoding="utf-8") as handle:
        assessment = json.load(handle)
    model_matches = assessment.get("model_id") == profile.get("candidate_model_id")
    dimensions_verified = (
        model_matches and assessment.get("image_dimensions_verified") is True
    )
    display_path = assessment.get("display_update_path", {})
    non_dfu_verified = (
        model_matches and display_path.get("non_dfu_write_path_verified") is True
    )
    profile["protocol_assessment_file"] = str(assessment_path)
    profile["verified_dimensions"] = assessment.get("logical_dimensions")
    profile["hard_gates"]["image_dimensions_verified"] = dimensions_verified
    profile["hard_gates"]["non_dfu_write_path_verified"] = non_dfu_verified
    if dimensions_verified and "model_0xA0_dimensions_250x132" not in profile["evidence"]:
        profile["evidence"].append("model_0xA0_dimensions_250x132")
    if non_dfu_verified and "display_path_separate_from_telink_ota" not in profile["evidence"]:
        profile["evidence"].append("display_path_separate_from_telink_ota")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan", type=Path, nargs="+")
    parser.add_argument("--gatt", type=Path, help="Optional saved read-only GATT result")
    parser.add_argument("--power-cycle", type=Path, help="Optional power-cycle evidence")
    parser.add_argument("--protocol", type=Path, help="Optional protocol assessment")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    profile = build_profile(args.scan)
    if args.gatt and profile.get("hard_gates"):
        apply_gatt_evidence(profile, args.gatt)
    if args.power_cycle and profile.get("hard_gates"):
        apply_power_cycle_evidence(profile, args.power_cycle)
    if args.protocol and profile.get("hard_gates"):
        apply_protocol_assessment(profile, args.protocol)
    preferred = EVIDENCE_DIR / "device_profile.json"
    output_path = (
        preferred
        if not preferred.exists()
        else EVIDENCE_DIR / f"device_profile_{timestamp_slug()}.json"
    )
    write_json_new(output_path, profile)
    print(json.dumps(profile, ensure_ascii=False, indent=2))
    print(f"Profile: {output_path}")
    return 0 if profile["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
