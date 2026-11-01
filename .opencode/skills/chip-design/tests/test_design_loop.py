import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / "tests" / "fixtures" / "check_adapter.py"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


design_loop = load("design_loop")


def base():
    return {
        "schema": "rocketeda/design/v0.1",
        "project": "loop",
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
                "required_checks": ["struct.widths"],
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


def command(status):
    return [sys.executable, str(ADAPTER), "--status", status, "--check", "{check}"]


def run(tmp: Path, doc: dict, adapters: dict | None = None, as_json: bool = False):
    design = tmp / "design.json"
    design.write_text(json.dumps(doc), encoding="utf-8")
    args = [str(design)]
    if adapters is not None:
        config = tmp / "checks.json"
        config.write_text(json.dumps({"checks": adapters}), encoding="utf-8")
        args += ["--config", str(config)]
    if as_json:
        args.append("--json")
    out = io.StringIO()
    with redirect_stdout(out):
        code = design_loop.main(args)
    return code, out.getvalue()


class DesignLoopTest(unittest.TestCase):
    def test_complete_when_leaf_is_at_target(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.inv")
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, {"func.inv": {"command": command("PASS")}})
        self.assertEqual(code, 0)
        self.assertIn("NEXT: complete", out)

    def test_rtl_leaf_without_behavioral_check_exits_four(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), base(), as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 4)
        self.assertIn("behavioral.inv", report["next"]["missing_checks"])

    def test_failing_check_exits_one(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.truth_table")
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, {"func.truth_table": {"command": command("FAIL")}}, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(report["next"]["action"], "repair")
        self.assertIn("inv", report["next"]["failing"])

    def test_missing_adapter_exits_four(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.truth_table")
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 4)
        self.assertEqual(report["next"]["action"], "provide_check")
        self.assertEqual(report["next"]["missing_checks"], ["func.truth_table"])

    def test_verified_leaf_below_target_asks_for_decomposition(self):
        doc = base()
        doc["blocks"][1]["level"] = "architecture"
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 3)
        self.assertEqual(report["next"]["action"], "decompose")
        self.assertEqual(report["next"]["decompose"][0]["block"], "inv")

    def test_parent_behavior_runs_after_children(self):
        doc = base()
        doc["blocks"][0]["required_checks"].append("func.top")
        doc["blocks"][1]["required_checks"].append("func.inv")
        adapters = {
            "func.top": {"command": command("FAIL")},
            "func.inv": {"command": command("PASS")},
        }
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, adapters, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 1)
        self.assertEqual(report["blocks"]["inv"]["status"], "PASS")
        self.assertEqual(report["blocks"]["top"]["status"], "FAIL")

    def test_artifact_placeholder_is_substituted(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.artifact")
        adapters = {
            "func.artifact": {
                "command": [
                    sys.executable,
                    "-c",
                    "import json,sys; print(json.dumps({'status':'PASS','evidence':sys.argv[1]}))",
                    "{artifact}",
                ]
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, adapters, as_json=True)
        report = json.loads(out)
        check = next(c for c in report["blocks"]["inv"]["checks"] if c["id"] == "func.artifact")
        self.assertEqual(code, 0)
        self.assertEqual(check["evidence"], "design/inv.v")

    def test_malformed_adapter_output_is_not_run(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.truth_table")
        adapters = {"func.truth_table": {"command": [sys.executable, "-c", "print('not json')"]}}
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, adapters, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 4)
        self.assertEqual(report["next"]["action"], "provide_check")

    def test_adapter_exit_code_is_not_run(self):
        doc = base()
        doc["blocks"][1]["required_checks"].append("func.truth_table")
        adapters = {"func.truth_table": {"command": [sys.executable, "-c", "import sys; sys.exit(3)"]}}
        with tempfile.TemporaryDirectory() as tmp:
            code, out = run(Path(tmp), doc, adapters, as_json=True)
        report = json.loads(out)
        self.assertEqual(code, 4)
        self.assertEqual(report["next"]["action"], "provide_check")

    def test_structural_error_exits_two(self):
        doc = base()
        doc["connections"].append({"from": "top.a", "to": "inv.a"})
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(Path(tmp), doc)
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
