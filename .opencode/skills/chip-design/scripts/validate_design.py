#!/usr/bin/env python3
"""Validate a RocketEDA hierarchical design description (design/design.json).

Structure and traceability only: verification verdicts come from Rocket Engine,
never from this file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

LEVELS = ("spec", "architecture", "rtl", "gate", "transistor")
STATUSES = ("PENDING", "GENERATED", "NEEDS_CLARIFICATION", "BLOCKED")
DIRECTIONS = ("input", "output", "inout")
KINDS = ("logic", "clock", "reset", "analog", "supply", "ground")
BLOCK_KINDS = ("combinational", "sequential", "unknown")
BLOCK_ID = re.compile(r"^[a-z][a-z0-9_]*$")
PORT_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SCHEMA = "rocketeda/design/v0.1"


def _text(value) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate(doc: dict) -> list[str]:
    errors: list[str] = []

    def err(msg: str) -> None:
        errors.append(msg)

    if not isinstance(doc, dict):
        return ["design must be a JSON object"]
    if doc.get("schema") != SCHEMA:
        err(f"schema must be {SCHEMA!r}")
    if not _text(doc.get("project")):
        err("project must be a non-empty string")
    target = doc.get("target_level")
    if target not in LEVELS:
        err(f"target_level must be one of {', '.join(LEVELS)}")

    requirements = doc.get("requirements")
    req_ids: dict[str, dict] = {}
    if not isinstance(requirements, list) or not requirements:
        err("requirements must be a non-empty list")
        requirements = []
    for req in requirements:
        if not isinstance(req, dict):
            err("each requirement must be an object")
            continue
        rid = req.get("id")
        if not _text(rid):
            err("requirement id must be a non-empty string")
            continue
        if rid in req_ids:
            err(f"requirement {rid}: duplicate id")
        req_ids[rid] = req
        if not _text(req.get("text")):
            err(f"requirement {rid}: text is required")
        acceptance = req.get("acceptance")
        if not isinstance(acceptance, list) or not acceptance or not all(_text(a) for a in acceptance):
            err(f"requirement {rid}: at least one non-empty acceptance criterion is required")

    blocks = doc.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        err("blocks must be a non-empty list")
        blocks = []

    by_id: dict[str, dict] = {}
    for block in blocks:
        if not isinstance(block, dict):
            err("each block must be an object")
            continue
        bid = block.get("id")
        if not isinstance(bid, str) or not BLOCK_ID.match(bid):
            err(f"block id {bid!r}: use lowercase letters, digits and underscores, starting with a letter")
            continue
        if bid in by_id:
            err(f"block {bid}: duplicate id")
            continue
        by_id[bid] = block

    roots = [b for b in by_id.values() if b.get("parent") is None]
    if len(roots) != 1:
        err(f"exactly one root block is required, found {len(roots)}")

    ports: dict[str, dict[str, dict]] = {}
    parents: dict[str, str | None] = {}

    for bid, block in by_id.items():
        parent = block.get("parent")
        if parent is not None and (not isinstance(parent, str) or parent not in by_id):
            err(f"block {bid}: unknown parent {parent!r}")
            parent = None
        if parent == bid:
            err(f"block {bid}: cannot be its own parent")
            parent = None
        parents[bid] = parent

        level = block.get("level")
        if level not in LEVELS:
            err(f"block {bid}: level must be one of {', '.join(LEVELS)}")
        elif parent is not None:
            parent_level = by_id[parent].get("level")
            if parent_level in LEVELS and LEVELS.index(level) < LEVELS.index(parent_level):
                err(f"block {bid}: level {level!r} is above its parent {parent!r} ({parent_level!r})")
        if level in LEVELS and target in LEVELS and LEVELS.index(level) > LEVELS.index(target):
            err(f"block {bid}: level {level!r} exceeds target_level {target!r}")

        status = block.get("status")
        if status not in STATUSES:
            err(f"block {bid}: status must be one of {', '.join(STATUSES)} (verification belongs to Rocket Engine)")

        block_kind = block.get("kind", "unknown")
        if block_kind not in BLOCK_KINDS:
            err(f"block {bid}: kind must be one of {', '.join(BLOCK_KINDS)}")

        if not _text(block.get("purpose")):
            err(f"block {bid}: purpose is required")

        refs = block.get("requirements")
        if not isinstance(refs, list) or not refs:
            err(f"block {bid}: at least one requirement reference is required")
        else:
            for rid in refs:
                if not isinstance(rid, str) or rid not in req_ids:
                    err(f"block {bid}: unknown requirement {rid!r}")

        checks = block.get("required_checks")
        if level in ("architecture", "rtl", "gate", "transistor") and (
            not isinstance(checks, list) or not checks or not all(_text(c) for c in checks)
        ):
            err(f"block {bid}: at least one required check is required at {level} level")

        artifact = block.get("artifact")
        if level in ("rtl", "gate", "transistor") and status == "GENERATED" and not _text(artifact):
            err(f"block {bid}: GENERATED at {level} level needs an artifact path")
        if artifact is not None:
            if not _text(artifact):
                err(f"block {bid}: artifact must be a non-empty path")
            else:
                artifact_path = Path(artifact)
                if artifact_path.is_absolute() or artifact_path.anchor or ".." in artifact_path.parts:
                    err(f"block {bid}: artifact must be a relative path inside the project")

        block_ports: dict[str, dict] = {}
        raw_ports = block.get("ports")
        if not isinstance(raw_ports, list) or not raw_ports:
            err(f"block {bid}: ports must be a non-empty list")
            raw_ports = []
        for port in raw_ports:
            if not isinstance(port, dict):
                err(f"block {bid}: each port must be an object")
                continue
            name = port.get("name")
            if not isinstance(name, str) or not PORT_ID.match(name):
                err(f"block {bid}: invalid port name {name!r}")
                continue
            if name in block_ports:
                err(f"block {bid}: duplicate port {name}")
                continue
            block_ports[name] = port
            if port.get("direction") not in DIRECTIONS:
                err(f"block {bid}.{name}: direction must be one of {', '.join(DIRECTIONS)}")
            width = port.get("width")
            if not isinstance(width, int) or isinstance(width, bool) or width < 1:
                err(f"block {bid}.{name}: width must be an integer >= 1")
            if port.get("kind") not in KINDS:
                err(f"block {bid}.{name}: kind must be one of {', '.join(KINDS)}")
        ports[bid] = block_ports

    for bid in by_id:
        seen: set[str] = set()
        cur: str | None = bid
        while cur is not None:
            if cur in seen:
                err(f"hierarchy cycle through block {cur}")
                break
            seen.add(cur)
            cur = parents.get(cur)

    connections = doc.get("connections", [])
    if not isinstance(connections, list):
        err("connections must be a list")
        connections = []

    def endpoint(value):
        if not _text(value) or "." not in value:
            err(f"connection endpoint {value!r}: expected 'block.port'")
            return None
        block_id, port_name = value.rsplit(".", 1)
        block = by_id.get(block_id)
        port = ports.get(block_id, {}).get(port_name)
        if block is None:
            err(f"connection endpoint {value!r}: unknown block {block_id!r}")
            return None
        if port is None:
            err(f"connection endpoint {value!r}: unknown port {port_name!r}")
            return None
        return block_id, port_name, port

    driven: dict[str, str] = {}
    combinational = {bid for bid, b in by_id.items() if b.get("kind", "unknown") == "combinational"}
    edges: dict[str, set[str]] = defaultdict(set)

    for conn in connections:
        if not isinstance(conn, dict):
            err("each connection must be an object")
            continue
        source = endpoint(conn.get("from"))
        sink = endpoint(conn.get("to"))
        if source is None or sink is None:
            continue
        from_block, from_port, from_def = source
        to_block, to_port, to_def = sink
        key = f"{to_block}.{to_port}"

        if from_block == to_block:
            err(f"connection {key}: a block cannot drive itself")
            continue
        if from_def.get("width") != to_def.get("width"):
            err(f"connection {from_block}.{from_port} -> {key}: width {from_def.get('width')} != {to_def.get('width')}")
        if key in driven:
            err(f"connection {key}: multiple drivers ({driven[key]} and {from_block}.{from_port})")
        driven[key] = f"{from_block}.{from_port}"

        from_parent = parents.get(from_block)
        to_parent = parents.get(to_block)
        if not (from_parent == to_parent or from_block == to_parent or to_block == from_parent):
            err(f"connection {from_block}.{from_port} -> {key}: endpoints are not in the same hierarchy scope")

        if from_block == to_parent:
            if from_def.get("direction") != "input":
                err(f"connection {from_block}.{from_port} -> {key}: a parent port feeding a child must be an input")
        elif to_block == from_parent:
            if to_def.get("direction") != "output":
                err(f"connection {from_block}.{from_port} -> {key}: a child driving a parent port must target an output")
        else:
            if from_def.get("direction") not in ("output", "inout"):
                err(f"connection {from_block}.{from_port} -> {key}: source must be an output or inout")
            if to_def.get("direction") not in ("input", "inout"):
                err(f"connection {key}: target must be an input or inout")

        if from_parent == to_parent and from_block in combinational and to_block in combinational:
            edges[from_block].add(to_block)

    for bid, block in by_id.items():
        if block.get("parent") is None:
            continue
        for name, port in ports.get(bid, {}).items():
            if port.get("direction") == "input" and f"{bid}.{name}" not in driven:
                err(f"block {bid}.{name}: input is not driven")

    # shortcut: recursive DFS + O(n^2) parent walks are fine for a few hundred blocks; upgrade to iterative traversal if designs grow.
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        state[node] = 1
        path.append(node)
        for nxt in sorted(edges.get(node, ())):
            if state.get(nxt) == 1:
                cycle = path[path.index(nxt):] + [nxt]
                err(f"combinational loop: {' -> '.join(cycle)}")
            elif state.get(nxt, 0) == 0:
                visit(nxt, path)
        path.pop()
        state[node] = 2

    for bid in sorted(edges):
        if state.get(bid, 0) == 0:
            visit(bid, [])

    covered = {
        rid
        for block in by_id.values()
        for rid in (block.get("requirements") or [])
        if isinstance(rid, str) and rid in req_ids
    }
    for rid in req_ids:
        if rid not in covered:
            err(f"requirement {rid}: not referenced by any block")

    return errors


def render_tree(doc: dict) -> list[str]:
    blocks = [b for b in doc.get("blocks", []) if isinstance(b, dict) and _text(b.get("id"))]
    children: dict[str | None, list[dict]] = defaultdict(list)
    for block in blocks:
        children[block.get("parent")].append(block)
    lines: list[str] = []

    def walk(parent: str | None, depth: int) -> None:
        for block in sorted(children.get(parent, []), key=lambda b: b["id"]):
            lines.append(f"{'  ' * depth}{block['id']} [{block.get('level')}] {block.get('status')}")
            walk(block["id"], depth + 1)

    walk(None, 0)
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", default="design/design.json")
    parser.add_argument("--quiet", action="store_true", help="only print the verdict")
    args = parser.parse_args(argv)

    path = Path(args.path)
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL: cannot read {path}: {exc}")
        return 2

    errors = validate(doc)
    if errors:
        print(f"FAIL: {len(errors)} error(s) in {path}")
        for message in errors:
            print(f" - {message}")
        return 1

    blocks = doc.get("blocks", [])
    connections = doc.get("connections", [])
    requirements = doc.get("requirements", [])
    print(f"OK {doc.get('project')}: {len(blocks)} blocks, {len(connections)} connections, "
          f"{len(requirements)} requirements, target {doc.get('target_level')}")
    if not args.quiet:
        for line in render_tree(doc):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
