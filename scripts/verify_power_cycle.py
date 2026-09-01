"""Verify target disappearance and reappearance using saved scan evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from common import EVIDENCE_DIR, iso_now, unique_path, write_json_new


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def candidate_matches(profile: dict[str, Any], candidate: dict[str, Any]) -> bool:
    return (
        candidate.get("address") == profile.get("address")
        and candidate.get("candidate_model_id") == profile.get("candidate_model_id")
        and candidate.get("manufacturer_data") == profile.get("manufacturer_data")
    )


def assess_power_cycle(
    profile: dict[str, Any],
    off_scan: dict[str, Any],
    on_scan: dict[str, Any],
) -> dict[str, Any]:
    off_matches = [
        candidate
        for candidate in off_scan.get("candidates", [])
        if candidate_matches(profile, candidate)
    ]
    on_matches = [
        candidate
        for candidate in on_scan.get("candidates", [])
        if candidate_matches(profile, candidate)
    ]
    passed = not off_matches and len(on_matches) == 1
    return {
        "assessed_at": iso_now(),
        "status": "PASS" if passed else "BLOCKED",
        "target_address": profile.get("address"),
        "off_scan_target_absent": not off_matches,
        "on_scan_single_exact_match": len(on_matches) == 1,
        "off_scan_candidate_count": off_scan.get("candidate_count"),
        "on_scan_candidate_count": on_scan.get("candidate_count"),
        "matched_model_id": (
            on_matches[0].get("candidate_model_id") if len(on_matches) == 1 else None
        ),
        "writes": 0,
        "notifications_started": 0,
        "write_allowed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--off-scan", required=True, type=Path)
    parser.add_argument("--on-scan", required=True, type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = assess_power_cycle(
        load_json(args.profile),
        load_json(args.off_scan),
        load_json(args.on_scan),
    )
    result["profile_file"] = str(args.profile)
    result["off_scan_file"] = str(args.off_scan)
    result["on_scan_file"] = str(args.on_scan)
    output_path = unique_path(EVIDENCE_DIR, "power_cycle", ".json")
    write_json_new(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_path}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
