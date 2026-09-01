"""Check the Git public-candidate set for local or sensitive artifacts.

This script is read-only. It examines files that Git would track, including
untracked files not excluded by .gitignore, and fails closed on suspicious
paths or common machine/device identifiers.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SELF_PATH = "scripts/check_public_release.py"
PUBLIC_PLACEHOLDERS = {
    "logs/.gitkeep",
    "evidence/.gitkeep",
    "images/.gitkeep",
}

FORBIDDEN_PATH_PATTERNS = (
    re.compile(r"(?:^|/)\.venv(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)__pycache__(?:/|$)", re.IGNORECASE),
    re.compile(r"^logs(?:/|$)", re.IGNORECASE),
    re.compile(r"^evidence(?:/|$)", re.IGNORECASE),
    re.compile(r"^images(?:/|$)", re.IGNORECASE),
    re.compile(r"^reports/assets/device_.*\.jpe?g$", re.IGNORECASE),
    re.compile(r"^reports/assets/qr_decode_result\.jpe?g$", re.IGNORECASE),
    re.compile(r"^reports/display_results_report\.html$", re.IGNORECASE),
    re.compile(r"(?:^|/)\.env(?:\.|$)", re.IGNORECASE),
    re.compile(r"\.(?:key|pem|p12|pfx)$", re.IGNORECASE),
)

TEXT_SUFFIXES = {
    "",
    ".cmd",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}

MACHINE_PATH_RE = re.compile(
    r"(?i)(?:[A-Z]:[\\/](?:Users|AI_Work)[\\/]|/Users/|/home/)"
)
MAC_ADDRESS_RE = re.compile(r"(?i)(?<![0-9a-f])(?:[0-9a-f]{2}:){5}[0-9a-f]{2}(?![0-9a-f])")
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
IPV4_RE = re.compile(r"(?<![0-9])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9])")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(?:api[_-]?key|access[_-]?token|password|secret)\b\s*[:=]\s*[\"'][^<{$][^\"']{5,}[\"']"
)


def normalize_git_path(value: str) -> str:
    return PurePosixPath(value.replace("\\", "/")).as_posix()


def path_is_forbidden(relative_path: str) -> bool:
    normalized = normalize_git_path(relative_path)
    if normalized in PUBLIC_PLACEHOLDERS:
        return False
    return any(pattern.search(normalized) for pattern in FORBIDDEN_PATH_PATTERNS)


def private_ipv4_values(text: str) -> list[str]:
    found: list[str] = []
    for candidate in IPV4_RE.findall(text):
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.is_private and not address.is_loopback:
            found.append(candidate)
    return sorted(set(found))


def find_private_markers(text: str) -> list[str]:
    markers: list[str] = []
    if MACHINE_PATH_RE.search(text):
        markers.append("machine-specific absolute path")
    if MAC_ADDRESS_RE.search(text):
        markers.append("MAC-like address")
    if EMAIL_RE.search(text):
        markers.append("email address")
    if private_ipv4_values(text):
        markers.append("private IPv4 address")
    if SECRET_ASSIGNMENT_RE.search(text):
        markers.append("possible embedded credential")
    return markers


def git_public_candidates(root: Path) -> list[str]:
    command = [
        "git",
        "-C",
        str(root),
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    result = subprocess.run(command, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "This directory is not a Git repository. Run the check after "
            "initializing the local repository."
        )
    return sorted(
        normalize_git_path(item.decode("utf-8", errors="strict"))
        for item in result.stdout.split(b"\0")
        if item
    )


def main() -> int:
    try:
        candidates = git_public_candidates(PROJECT_ROOT)
    except (RuntimeError, UnicodeDecodeError) as error:
        print(f"PUBLIC RELEASE CHECK: ERROR\n{error}")
        return 2

    failures: list[str] = []
    scanned_text_files = 0
    for relative_path in candidates:
        if path_is_forbidden(relative_path):
            failures.append(f"{relative_path}: forbidden public path")
            continue

        path = PROJECT_ROOT / Path(relative_path)
        if path.is_symlink():
            try:
                path.resolve().relative_to(PROJECT_ROOT.resolve())
            except ValueError:
                failures.append(f"{relative_path}: symlink leaves repository")
            continue
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        if relative_path == SELF_PATH:
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            failures.append(f"{relative_path}: expected UTF-8 text")
            continue
        scanned_text_files += 1
        for marker in find_private_markers(text):
            failures.append(f"{relative_path}: {marker}")

    if failures:
        print("PUBLIC RELEASE CHECK: FAIL")
        for failure in failures:
            print(f"- {failure}")
        print("No files were changed. Remove or ignore the reported material.")
        return 1

    print("PUBLIC RELEASE CHECK: PASS")
    print(f"Git public candidates: {len(candidates)}")
    print(f"UTF-8 text files scanned: {scanned_text_files}")
    print("No local evidence, device identifiers, private paths, or credentials detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
