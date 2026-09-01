from __future__ import annotations

import ast
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
READ_ONLY_SCRIPTS = (
    PROJECT_ROOT / "scripts" / "scan_ble.py",
    PROJECT_ROOT / "scripts" / "inspect_gatt.py",
    PROJECT_ROOT / "scripts" / "verify_power_cycle.py",
    PROJECT_ROOT / "scripts" / "render_test_image.py",
    PROJECT_ROOT / "scripts" / "prepare_payload.py",
)
PROHIBITED_CALL_NAMES = {"write_gatt_char", "start_notify", "pair"}


class SafetyBoundaryTests(unittest.TestCase):
    def test_read_only_scripts_do_not_call_prohibited_ble_apis(self) -> None:
        violations: list[str] = []
        for path in READ_ONLY_SCRIPTS:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in PROHIBITED_CALL_NAMES:
                        violations.append(f"{path.name}:{node.lineno}:{node.func.attr}")
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()
