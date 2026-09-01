"""Record the project-local Python and dependency environment."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
from importlib.metadata import PackageNotFoundError, version

from common import EVIDENCE_DIR, iso_now, unique_path, write_json_new


REQUIRED_PACKAGES = {
    "bleak": "3.0.2",
    "gicisky": "0.2.1",
    "numpy": "2.5.2",
    "pillow": "12.3.0",
    "qrcode": "8.2",
}


def package_versions() -> tuple[dict[str, str | None], list[str]]:
    installed: dict[str, str | None] = {}
    mismatches: list[str] = []
    for package, expected in REQUIRED_PACKAGES.items():
        try:
            actual = version(package)
        except PackageNotFoundError:
            actual = None
        installed[package] = actual
        if actual != expected:
            mismatches.append(f"{package}: expected {expected}, got {actual}")
    return installed, mismatches


def main() -> int:
    installed, mismatches = package_versions()
    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin()) if os.name == "nt" else False
    is_venv = sys.prefix != sys.base_prefix
    payload = {
        "checked_at": iso_now(),
        "status": "PASS" if os.name == "nt" and is_venv and not mismatches else "FAIL",
        "os": platform.platform(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "virtual_environment": is_venv,
        "administrator": is_admin,
        "packages": installed,
        "mismatches": mismatches,
    }
    output_path = unique_path(EVIDENCE_DIR, "environment", ".json")
    write_json_new(output_path, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Evidence: {output_path}")
    return 0 if payload["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
