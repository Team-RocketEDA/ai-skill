import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("render_diagram", ROOT / "scripts" / "render_diagram.py")
render_diagram = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_diagram)


def alu():
    return json.loads((ROOT / "examples" / "alu8" / "design.json").read_text(encoding="utf-8"))


class RenderDiagramTest(unittest.TestCase):
    def test_renders_root_children_and_connections(self):
        text = render_diagram.render(alu())
        self.assertIn("flowchart LR", text)
        self.assertIn('arith["arith<br/>architecture"]', text)
        self.assertIn('in_a["a[8] input"] --> arith', text)
        self.assertIn('arith -->|"y -> arith_y"| select', text)
        self.assertIn('select --> out_y["y[8] output"]', text)

    def test_leaf_renders_as_single_node(self):
        text = render_diagram.render(alu(), "arith")
        self.assertIn("flowchart LR", text)
        self.assertIn('arith["arith<br/>architecture"]', text)
        self.assertNotIn("in_a", text)

    def test_unknown_block_fails(self):
        with self.assertRaises(SystemExit):
            render_diagram.render(alu(), "missing")

    def test_writes_output_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "alu.mmd"
            code = render_diagram.main([
                str(ROOT / "examples" / "alu8" / "design.json"),
                "--out", str(out),
            ])
            self.assertEqual(code, 0)
            self.assertIn("flowchart LR", out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
