"""Shared, side-effect-limited helpers for the ESL investigation scripts."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
LOG_DIR = PROJECT_ROOT / "logs"
EVIDENCE_DIR = PROJECT_ROOT / "evidence"


class IsoFormatter(logging.Formatter):
    """Render local timestamps as timezone-aware ISO 8601 values."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        del datefmt
        return datetime.fromtimestamp(record.created).astimezone().isoformat(
            timespec="milliseconds"
        )


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def timestamp_slug() -> str:
    return datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")


def unique_path(directory: Path, prefix: str, suffix: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{prefix}_{timestamp_slug()}{suffix}"


def write_json_new(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def configure_logging(prefix: str) -> tuple[logging.Logger, Path]:
    log_path = unique_path(LOG_DIR, prefix, ".log")
    logger = logging.getLogger(f"esl_control.{prefix}.{timestamp_slug()}")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    formatter = IsoFormatter("%(asctime)s [%(levelname)s] %(message)s")
    file_handler = logging.FileHandler(log_path, mode="x", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger, log_path


def bytes_map_to_hex(values: dict[Any, bytes]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in values.items():
        rendered_key = f"0x{key:04X}" if isinstance(key, int) else str(key)
        result[rendered_key] = bytes(value).hex().upper()
    return result
