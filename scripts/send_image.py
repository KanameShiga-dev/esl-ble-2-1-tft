"""Beginner-friendly, single-image sender for the verified 0xA0 TFT ESL.

The user supplies one 250 x 132 image. This wrapper keeps the existing safety
gates: a verified local profile, a fresh single-candidate scan, live GATT
preflight, strict acknowledgements, no automatic retry, and an interactive
SEND confirmation before the first device write.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

from PIL import Image, UnidentifiedImageError

from common import (
    CONFIG_DIR,
    EVIDENCE_DIR,
    LOG_DIR,
    iso_now,
    unique_path,
    write_json_new,
)
from prepare_payload import LOGICAL_SIZE, build_payload, validate_gates
from scan_ble import perform_scan
from write_test_image import (
    MAX_TRANSFER_SECONDS,
    bounded_transfer,
    validate_scan,
)


MODEL_ID = "0xA0"
EXPECTED_PAYLOAD_BYTES = 4125
CONFIRMATION_PHRASE = "SEND"
REQUIRED_PROFILE_GATES = {
    "unique_candidate",
    "power_cycle_verified",
    "model_id_verified",
    "gatt_profile_verified",
    "image_dimensions_verified",
    "non_dfu_write_path_verified",
}


class SimpleSendError(RuntimeError):
    """A failure that can be explained to a non-technical operator."""


def configure_console_output() -> None:
    """Keep Japanese readable in both Windows terminals and captured logs."""

    if (
        os.name == "nt"
        and not sys.stdout.isatty()
        and hasattr(sys.stdout, "reconfigure")
    ):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise SimpleSendError(f"設定ファイルを読めません: {path.name}") from error
    if not isinstance(value, dict):
        raise SimpleSendError(f"設定ファイルの形式が正しくありません: {path.name}")
    return value


def profile_is_ready(profile: dict[str, Any]) -> bool:
    gates = profile.get("hard_gates", {})
    return (
        profile.get("candidate_model_id") == MODEL_ID
        and isinstance(profile.get("address"), str)
        and bool(profile["address"])
        and all(gates.get(name) is True for name in REQUIRED_PROFILE_GATES)
    )


def select_verified_profile(
    explicit_path: Path | None = None,
    evidence_dir: Path = EVIDENCE_DIR,
) -> tuple[Path, dict[str, Any]]:
    """Select one verified local profile without exposing its address."""

    if explicit_path is not None:
        path = explicit_path.resolve()
        profile = load_json_object(path)
        if not profile_is_ready(profile):
            raise SimpleSendError(
                "指定した端末設定は送信準備が完了していません。"
                "先に開発仕様書の端末識別手順を実行してください。"
            )
        return path, profile

    candidates: list[tuple[Path, dict[str, Any]]] = []
    for path in evidence_dir.glob("device_profile*.json"):
        try:
            profile = load_json_object(path)
        except SimpleSendError:
            continue
        if profile_is_ready(profile):
            candidates.append((path, profile))

    if not candidates:
        raise SimpleSendError(
            "確認済みの端末設定がありません。"
            "このPCで端末識別を一度完了する必要があります。"
        )

    addresses = {profile["address"] for _, profile in candidates}
    if len(addresses) != 1:
        raise SimpleSendError(
            "確認済み端末が複数あります。誤送信防止のため --profile で1台を指定してください。"
        )

    return max(candidates, key=lambda item: item[0].stat().st_mtime)


def normalize_image(image_path: Path) -> tuple[Image.Image, dict[str, Any]]:
    """Load a 250 x 132 image and convert it to exact black and white."""

    path = image_path.resolve()
    if not path.is_file():
        raise SimpleSendError(f"画像ファイルが見つかりません: {path}")
    try:
        with Image.open(path) as opened:
            opened.load()
            original_size = opened.size
            original_mode = opened.mode
            if original_size != LOGICAL_SIZE:
                raise SimpleSendError(
                    "画像サイズが違います。"
                    f"必要: {LOGICAL_SIZE[0]}x{LOGICAL_SIZE[1]} / "
                    f"現在: {original_size[0]}x{original_size[1]}"
                )
            normalized = (
                opened.convert("L")
                .point(lambda value: 255 if value >= 128 else 0, mode="1")
                .convert("RGB")
            )
    except SimpleSendError:
        raise
    except (OSError, UnidentifiedImageError) as error:
        raise SimpleSendError(
            "画像を開けません。PNG形式を推奨します。"
        ) from error

    black_pixels = sum(
        count
        for count, color in normalized.getcolors(maxcolors=3) or []
        if color == (0, 0, 0)
    )
    total_pixels = normalized.width * normalized.height
    metadata = {
        "file": str(path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest().upper(),
        "source_mode": original_mode,
        "width": normalized.width,
        "height": normalized.height,
        "black_pixels": black_pixels,
        "white_pixels": total_pixels - black_pixels,
        "conversion": "threshold_128_to_exact_bw",
    }
    return normalized, metadata


def make_local_plan(
    *,
    image_metadata: dict[str, Any],
    payload: bytes,
    profile_path: Path,
    profile: dict[str, Any],
    scan_path: Path | None,
) -> dict[str, Any]:
    """Create a local, hash-bound summary for confirmation and evidence."""

    return {
        "created_at": iso_now(),
        "status": "WAITING_FOR_LOCAL_CONFIRMATION",
        "target_alias": "ESL-0xA0",
        "target_address": profile["address"],
        "target_model_id": MODEL_ID,
        "profile": str(profile_path),
        "fresh_scan": str(scan_path) if scan_path else None,
        "image": image_metadata,
        "payload": {
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
            "chunk_image_bytes": 240,
            "chunk_count": 18,
        },
        "planned_writes": {
            "command": 3,
            "image": 18,
            "total": 21,
        },
        "automatic_retries": 0,
        "confirmation_phrase": CONFIRMATION_PHRASE,
        "device_writes_performed": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "250x132の画像1枚を、確認済み0xA0 ESLへ安全に送ります。"
            "実際の送信前にSEND入力が必要です。"
        )
    )
    parser.add_argument("image", type=Path, help="送信する250x132画像（PNG推奨）")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="画像と設定だけを確認し、BLEスキャン・送信を行いません。",
    )
    parser.add_argument(
        "--profile",
        type=Path,
        help="通常は不要。複数端末がある場合だけ確認済みprofileを指定します。",
    )
    parser.add_argument(
        "--scan-seconds",
        type=float,
        default=20.0,
        help="送信直前の端末スキャン時間（既定20秒、5〜120秒）",
    )
    return parser.parse_args()


def print_image_summary(image_metadata: dict[str, Any], payload: bytes) -> None:
    print("")
    print("ESL かんたん画像送信")
    print("====================")
    print(f"画像   : {Path(image_metadata['file']).name}")
    print(f"サイズ : {image_metadata['width']} x {image_metadata['height']}")
    print("色     : 白黒に自動変換済み")
    print(f"送信量 : {len(payload):,} bytes")
    print("対象   : 確認済み ESL-0xA0（アドレスは画面に表示しません）")
    print("")


def main() -> int:
    configure_console_output()
    args = parse_args()
    if not 5.0 <= args.scan_seconds <= 120.0:
        print("エラー: --scan-seconds は5〜120秒で指定してください。")
        return 2

    try:
        protocol_path = CONFIG_DIR / "protocol_model_a0.json"
        protocol = load_json_object(protocol_path)
        profile_path, profile = select_verified_profile(args.profile)
        validate_gates(profile, protocol)
        image, image_metadata = normalize_image(args.image)
        payload = build_payload(image)
        if len(payload) != EXPECTED_PAYLOAD_BYTES:
            raise SimpleSendError(
                f"内部変換後のデータ長が異常です: {len(payload)} bytes"
            )
    except (SimpleSendError, ValueError) as error:
        print(f"エラー: {error}")
        print("端末への書込みは行っていません。")
        return 2

    print_image_summary(image_metadata, payload)
    if args.check_only:
        print("確認OK: 画像と端末設定に問題はありません。")
        print("--check-only のためBLE通信と送信は行っていません。")
        return 0

    print(f"1/3 端末を探しています（約{args.scan_seconds:g}秒）...")
    try:
        scan = asyncio.run(perform_scan(args.scan_seconds, expected_suffix=None))
        scan_path = unique_path(LOG_DIR, "ble_scan_simple", ".json")
        write_json_new(scan_path, scan)
        validate_scan(scan, profile)
    except Exception as error:
        print("エラー: 対象端末を1台に確認できませんでした。")
        print("電池、PCのBluetooth、スマホアプリの接続を確認してください。")
        print(f"詳細: {type(error).__name__}: {error}")
        print("端末への書込みは行っていません。")
        return 2

    plan = make_local_plan(
        image_metadata=image_metadata,
        payload=payload,
        profile_path=profile_path,
        profile=profile,
        scan_path=scan_path,
    )
    plan_path = unique_path(EVIDENCE_DIR, "simple_send_plan", ".json")
    write_json_new(plan_path, plan)

    print("2/3 対象端末を確認しました。")
    print("")
    print("注意: 送信すると、現在のESL画面はこの画像に置き換わります。")
    print("中止する場合は、そのままEnterを押してください。")
    try:
        answer = input(f"送信する場合だけ {CONFIRMATION_PHRASE} と入力: ").strip()
    except EOFError:
        answer = ""
    if answer != CONFIRMATION_PHRASE:
        cancelled = {
            **plan,
            "completed_at": iso_now(),
            "status": "CANCELLED",
            "device_writes_performed": 0,
        }
        result_path = unique_path(EVIDENCE_DIR, "simple_send_attempt", ".json")
        write_json_new(result_path, cancelled)
        print("キャンセルしました。端末への書込みは行っていません。")
        return 0

    print("3/3 画像を送信しています。電池を外さず、そのままお待ちください...")
    try:
        transfer = asyncio.run(
            asyncio.wait_for(
                bounded_transfer(
                    profile["address"],
                    payload,
                    connection_timeout=15.0,
                    response_timeout=5.0,
                ),
                timeout=MAX_TRANSFER_SECONDS,
            )
        )
    except Exception as error:
        transfer = {
            "status": "FAIL",
            "error": f"{type(error).__name__}: {error}",
            "writes": 0,
            "image_writes": 0,
            "disconnected": False,
        }

    result = {
        **plan,
        **transfer,
        "completed_at": iso_now(),
        "approval": {
            "method": "interactive_exact_phrase",
            "phrase": CONFIRMATION_PHRASE,
        },
        "automatic_retries": 0,
        "device_writes_performed": int(transfer.get("writes", 0)),
    }
    result_path = unique_path(EVIDENCE_DIR, "simple_send_attempt", ".json")
    write_json_new(result_path, result)

    if result.get("status") == "PASS":
        print("")
        print("送信完了: ESLの画面を目で確認してください。")
        print("位置や向きが違う場合は、続けて送信せず結果を報告してください。")
        print(f"記録: {result_path}")
        return 0

    print("")
    print("送信に失敗しました。自動再試行はしていません。")
    print("同じコマンドを連続実行せず、端末の画面と電池状態を確認してください。")
    print(f"記録: {result_path}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
