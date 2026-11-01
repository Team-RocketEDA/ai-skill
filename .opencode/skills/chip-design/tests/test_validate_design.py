import copy
import importlib.util
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("validate_design", ROOT / "scripts" / "validate_design.py")
validate_design = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate_design)


def base():
    return {
        "schema": "rocketeda/design/v0.1",
        "project": "inverter",
        "target_level": "rtl",
        "requirements": [
            {"id": "R1", "text": "y is the inverse of a", "acceptance": ["y == not a"]}
        ],
        "blocks": [
            {
                "id": "top",
                "parent": None,
                "level": "architecture",
                "kind": "combinational",
                "purpose": "top level",
                "status": "GENERATED",
                "requirements": ["R1"],
                "required_checks": ["struct.widths"],
                "ports": [
                    {"name": "a", "direction": "input", "width": 1, "kind": "logic"},
                    {"name": "y", "direction": "output", "width": 1, "kind": "logic"},
                ],
            },
            {
                "id": "inv",
                "parent": "top",
                "level": "rtl",
                "kind": "combinational",
                "purpose": "inverter",
                "status": "GENERATED",
                "requirements": ["R1"],
                "required_checks": ["func.truth_table"],
                "artifact": "design/inv.v",
                "ports": [
                    {"name": "a", "direction": "input", "width": 1, "kind": "logic"},
                    {"name": "y", "direction": "output", "width": 1, "kind": "logic"},
                ],
            },
        ],
        "connections": [
            {"from": "top.a", "to": "inv.a"},
            {"from": "inv.y", "to": "top.y"},
        ],
    }


def errors_after(mutate):
    doc = base()
    mutate(doc)
    return validate_design.validate(doc)


class ValidateDesignTest(unittest.TestCase):
    def test_base_is_valid(self):
        self.assertEqual(validate_design.validate(base()), [])

    def test_example_is_valid(self):
        doc = json.loads((ROOT / "examples" / "alu8" / "design.json").read_text(encoding="utf-8"))
        self.assertEqual(validate_design.validate(doc), [])

    def test_width_mismatch(self):
        def mutate(doc):
            doc["blocks"][1]["ports"][0]["width"] = 2

        self.assertTrue(any("width" in e for e in errors_after(mutate)))

    def test_undriven_child_input(self):
        def mutate(doc):
            doc["connections"] = [{"from": "inv.y", "to": "top.y"}]

        self.assertTrue(any("not driven" in e for e in errors_after(mutate)))

    def test_multiple_drivers(self):
        def mutate(doc):
            doc["connections"].append({"from": "top.a", "to": "inv.a"})

        self.assertTrue(any("multiple drivers" in e for e in errors_after(mutate)))

    def test_unknown_parent(self):
        def mutate(doc):
            doc["blocks"][1]["parent"] = "missing"

        self.assertTrue(any("unknown parent" in e for e in errors_after(mutate)))

    def test_hierarchy_cycle(self):
        def mutate(doc):
            doc["blocks"].append(
                {
                    "id": "mid",
                    "parent": "inv",
                    "level": "rtl",
                    "kind": "combinational",
                    "purpose": "cycle member",
                    "status": "PENDING",
                    "requirements": ["R1"],
                    "required_checks": ["struct.widths"],
                    "ports": [{"name": "a", "direction": "input", "width": 1, "kind": "logic"}],
                }
            )
            doc["blocks"][1]["parent"] = "mid"
            doc["connections"] = []

        self.assertTrue(any("hierarchy cycle" in e for e in errors_after(mutate)))

    def test_requirement_coverage(self):
        def mutate(doc):
            doc["requirements"].append(
                {"id": "R2", "text": "unused", "acceptance": ["never checked"]}
            )

        self.assertTrue(any("R2" in e and "not referenced" in e for e in errors_after(mutate)))

    def test_verified_status_is_rejected(self):
        def mutate(doc):
            doc["blocks"][1]["status"] = "VERIFIED"

        self.assertTrue(any("status" in e for e in errors_after(mutate)))

    def test_cross_hierarchy_connection(self):
        def mutate(doc):
            doc["blocks"].append(
                {
                    "id": "deep",
                    "parent": "inv",
                    "level": "gate",
                    "kind": "combinational",
                    "purpose": "deeper block",
                    "status": "PENDING",
                    "requirements": ["R1"],
                    "required_checks": ["struct.widths"],
                    "ports": [{"name": "y", "direction": "output", "width": 1, "kind": "logic"}],
                }
            )
            doc["connections"].append({"from": "deep.y", "to": "top.a"})

        self.assertTrue(any("same hierarchy scope" in e for e in errors_after(mutate)))

    def test_combinational_loop(self):
        def mutate(doc):
            doc["blocks"].append(
                {
                    "id": "buf",
                    "parent": "top",
                    "level": "rtl",
                    "kind": "combinational",
                    "purpose": "buffer",
                    "status": "GENERATED",
                    "requirements": ["R1"],
                    "required_checks": ["struct.widths"],
                    "artifact": "design/buf.v",
                    "ports": [
                        {"name": "a", "direction": "input", "width": 1, "kind": "logic"},
                        {"name": "y", "direction": "output", "width": 1, "kind": "logic"},
                    ],
                }
            )
            doc["connections"] = [
                {"from": "inv.y", "to": "buf.a"},
                {"from": "buf.y", "to": "inv.a"},
                {"from": "inv.y", "to": "top.y"},
            ]

        self.assertTrue(any("combinational loop" in e for e in errors_after(mutate)))

    def test_absolute_artifact_is_rejected(self):
        def mutate(doc):
            doc["blocks"][1]["artifact"] = "/tmp/inv.v"

        self.assertTrue(any("relative path" in e for e in errors_after(mutate)))

    def test_cli_reports_ok(self):
        path = ROOT / "examples" / "alu8" / "design.json"
        out = io.StringIO()
        with redirect_stdout(out):
            code = validate_design.main([str(path)])
        self.assertEqual(code, 0)
        self.assertIn("OK alu8", out.getvalue())


if __name__ == "__main__":
    unittest.main()
