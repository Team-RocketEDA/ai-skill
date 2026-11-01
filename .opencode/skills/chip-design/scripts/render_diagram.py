#!/usr/bin/env python3
"""Render one block's children and connections as a Mermaid flowchart.

The diagram is derived from design/design.json. Never edit the output by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_design


def label(block: dict) -> str:
    return f'{block["id"]}<br/>{block.get("level", "")}'


def port_label(block: dict, name: str) -> str:
    for port in block.get("ports", []):
        if port.get("name") == name:
            return f'{name}[{port.get("width")}] {port.get("direction")}'
    return name


def render(doc: dict, block_id: str | None = None) -> str:
    blocks = {block["id"]: block for block in doc["blocks"]}
    root_id = block_id or next(
        (block["id"] for block in doc["blocks"] if block.get("parent") is None), None
    )
    if root_id not in blocks:
        raise SystemExit(f"unknown block {root_id!r}")
    root = blocks[root_id]
    children = [b for b in doc["blocks"] if b.get("parent") == root_id]
    child_ids = {b["id"] for b in children}

    lines = ["flowchart LR", f"  %% {root_id} ({root.get('level')})"]
    if not children:
        lines.append(f'  {root_id}["{label(root)}"]')
        return "\n".join(lines) + "\n"

    for child in sorted(children, key=lambda b: b["id"]):
        lines.append(f'  {child["id"]}["{label(child)}"]')

    for conn in doc.get("connections", []):
        source, target = conn["from"], conn["to"]
        source_block, source_port = source.rsplit(".", 1)
        target_block, target_port = target.rsplit(".", 1)
        if source_block == root_id and target_block in child_ids:
            lines.append(f'  in_{source_port}["{port_label(root, source_port)}"] --> {target_block}')
        elif target_block == root_id and source_block in child_ids:
            lines.append(f'  {source_block} --> out_{target_port}["{port_label(root, target_port)}"]')
        elif source_block in child_ids and target_block in child_ids:
            lines.append(f'  {source_block} -->|"{source_port} -> {target_port}"| {target_block}')

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", nargs="?", default="design/design.json")
    parser.add_argument("--block", help="block id; defaults to the root")
    parser.add_argument("--out", help="write to this path instead of stdout")
    args = parser.parse_args(argv)

    path = Path(args.design)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read {path}: {exc}")
        return 2
    errors = validate_design.validate(doc)
    if errors:
        print(f"FAIL: {len(errors)} structural error(s); fix the design before rendering")
        return 2

    text = render(doc, args.block)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(out)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
