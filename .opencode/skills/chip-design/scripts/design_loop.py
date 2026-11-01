#!/usr/bin/env python3
"""Level-by-level design gate for the chip-design skill.

The agent edits design/design.json and its artifacts. This loop decides whether the
current level is verified and whether the agent may descend. It never invents a
verdict: checks come from the structural validator or an external adapter.

Exit codes:
  0  every leaf reached the target level and all checks passed
  1  a check failed; repair the named block/check
  2  the design is structurally invalid
  3  checks passed but work remains; decompose the named leaves
  4  a check could not run; provide an adapter or install the tool
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import validate_design

STATUSES = ("PASS", "FAIL", "NOT_RUN", "UNSUPPORTED")
LEVELS = validate_design.LEVELS


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"cannot read {path}: {exc}"


def tree_order(blocks: list[dict]) -> list[dict]:
    children: dict[str | None, list[dict]] = defaultdict(list)
    for block in blocks:
        children[block.get("parent")].append(block)
    ordered: list[dict] = []

    def walk(parent: str | None) -> None:
        for block in sorted(children.get(parent, []), key=lambda b: b["id"]):
            ordered.append(block)
            walk(block["id"])

    walk(None)
    return ordered


def aggregate(statuses: list[str]) -> str:
    if "FAIL" in statuses:
        return "FAIL"
    if "UNSUPPORTED" in statuses:
        return "UNSUPPORTED"
    if "NOT_RUN" in statuses:
        return "NOT_RUN"
    return "PASS"


def run_adapter(check_id: str, block: dict, design: Path, spec: dict, config_error: str | None) -> dict:
    if config_error:
        return {"id": check_id, "status": "NOT_RUN", "reason": config_error}
    if not isinstance(spec, dict):
        return {"id": check_id, "status": "NOT_RUN", "reason": "no adapter configured"}

    command = spec.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) for a in command):
        return {"id": check_id, "status": "NOT_RUN", "reason": "adapter command must be a list of strings"}

    replacements = {
        "{design}": str(design),
        "{block}": block["id"],
        "{level}": block.get("level", ""),
        "{check}": check_id,
        "{artifact}": block.get("artifact", ""),
    }
    args = []
    for part in command:
        for needle, value in replacements.items():
            part = part.replace(needle, value)
        args.append(part)

    timeout = spec.get("timeout", 120)
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        timeout = 120
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"id": check_id, "status": "NOT_RUN", "reason": f"adapter did not run: {exc}"}
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        return {
            "id": check_id,
            "status": "NOT_RUN",
            "reason": f"adapter exited {proc.returncode}: {detail[0][:300] if detail else 'no output'}",
        }

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"id": check_id, "status": "NOT_RUN", "reason": "adapter did not return JSON"}

    candidates = payload.get("checks", []) if isinstance(payload, dict) else payload
    if isinstance(candidates, dict):
        candidates = [candidates]
    if isinstance(candidates, list):
        for result in candidates:
            if isinstance(result, dict) and result.get("id") == check_id:
                return _normalize(result, check_id)
    if isinstance(payload, dict) and payload.get("status") in STATUSES:
        return _normalize(payload, check_id)
    return {"id": check_id, "status": "NOT_RUN", "reason": f"adapter did not report {check_id!r}"}


def _normalize(result: dict, check_id: str) -> dict:
    status = result.get("status")
    if status not in STATUSES:
        return {"id": check_id, "status": "NOT_RUN", "reason": f"invalid adapter status {status!r}"}
    normalized = {"id": check_id, "status": status}
    for field in ("evidence", "reason", "measured", "target"):
        if result.get(field) is not None:
            normalized[field] = result[field]
    return normalized


def structural_checks(block: dict) -> list[dict]:
    return [
        {"id": check_id, "status": "PASS", "evidence": "validate_design.py"}
        for check_id in block.get("required_checks", [])
        if isinstance(check_id, str) and check_id.startswith("struct.")
    ]


def behavioral_checks(block: dict, design: Path, adapters: dict, config_error: str | None) -> list[dict]:
    results = []
    for check_id in block.get("required_checks", []):
        if not isinstance(check_id, str):
            results.append({"id": str(check_id), "status": "NOT_RUN", "reason": "check id must be a string"})
        elif not check_id.startswith("struct."):
            results.append(run_adapter(check_id, block, design, adapters.get(check_id), config_error))
    return results


def build_report(doc: dict, design: Path, adapters: dict, config_error: str | None) -> dict:
    target = doc["target_level"]
    blocks = doc["blocks"]
    ordered = tree_order(blocks)
    parents = {b["id"]: b.get("parent") for b in blocks}
    children: dict[str | None, list[dict]] = defaultdict(list)
    for block in blocks:
        children[block.get("parent")].append(block)
    leaves = [b for b in blocks if not children.get(b["id"])]

    block_results: dict[str, dict] = {}
    blocked: dict[str, str] = {}

    # Structure gates descent: a parent must be structurally sound before its children run.
    for block in ordered:
        bid = block["id"]
        parent = parents.get(bid)
        if parent in blocked:
            block_results[bid] = {
                "status": "SKIPPED",
                "reason": f"ancestor {parent} is {blocked[parent]}",
                "checks": [],
            }
            blocked[bid] = "SKIPPED"
            continue
        checks = structural_checks(block)
        status = aggregate([c["status"] for c in checks])
        block_results[bid] = {"status": status, "checks": checks}
        if status != "PASS":
            blocked[bid] = status

    # A leaf proves its own behavior before it may be decomposed.
    for block in ordered:
        bid = block["id"]
        if bid in blocked or children.get(bid):
            continue
        checks = block_results[bid]["checks"] + behavioral_checks(block, design, adapters, config_error)
        level = block.get("level")
        if level in ("rtl", "gate", "transistor") and not any(
            not check["id"].startswith("struct.") for check in checks
        ):
            checks.append(
                {
                    "id": f"behavioral.{bid}",
                    "status": "NOT_RUN",
                    "reason": f"{level} leaf declares no behavioral check",
                }
            )
        status = aggregate([c["status"] for c in checks])
        block_results[bid] = {"status": status, "checks": checks}
        if status != "PASS":
            blocked[bid] = status

    # A parent's behavior is checked only after every child passed (composition gate).
    for block in reversed(ordered):
        bid = block["id"]
        if bid in blocked or not children.get(bid):
            continue
        bad = [c["id"] for c in children[bid] if block_results[c["id"]]["status"] != "PASS"]
        if bad:
            block_results[bid] = {
                "status": "SKIPPED",
                "reason": f"child {bad[0]} is {block_results[bad[0]]['status']}",
                "checks": block_results[bid]["checks"],
            }
            blocked[bid] = "SKIPPED"
            continue
        checks = block_results[bid]["checks"] + behavioral_checks(block, design, adapters, config_error)
        status = aggregate([c["status"] for c in checks])
        block_results[bid] = {"status": status, "checks": checks}
        if status != "PASS":
            blocked[bid] = status

    summary = {status: 0 for status in (*STATUSES, "SKIPPED")}
    for result in block_results.values():
        summary[result["status"]] += 1

    failing = [bid for bid, r in block_results.items() if r["status"] == "FAIL"]
    missing = sorted(
        {
            check["id"]
            for result in block_results.values()
            for check in result["checks"]
            if check["status"] in ("NOT_RUN", "UNSUPPORTED")
        }
    )
    unfinished = []
    for block in leaves:
        if block_results[block["id"]]["status"] != "PASS":
            continue
        level = block.get("level")
        if level not in LEVELS or level == target:
            continue
        if LEVELS.index(level) < LEVELS.index(target):
            unfinished.append(
                {"block": block["id"], "level": level, "to": LEVELS[LEVELS.index(level) + 1]}
            )

    if failing:
        code, action = 1, "repair"
    elif missing:
        code, action = 4, "provide_check"
    elif unfinished:
        code, action = 3, "decompose"
    else:
        code, action = 0, "complete"

    return {
        "project": doc.get("project"),
        "target": target,
        "structure": "OK",
        "blocks": block_results,
        "summary": summary,
        "next": {
            "action": action,
            "failing": failing,
            "missing_checks": missing,
            "decompose": unfinished,
        },
        "exit": code,
    }


def print_human(report: dict, doc: dict) -> None:
    print(f"chip-design loop: {report['project']} | target {report['target']}")
    print(f"structure: OK ({len(doc['blocks'])} blocks, {len(doc.get('connections', []))} connections)")
    for level in LEVELS:
        blocks = [b for b in doc["blocks"] if b.get("level") == level]
        if not blocks:
            continue
        passed = sum(1 for b in blocks if report["blocks"][b["id"]]["status"] == "PASS")
        print(f"LEVEL {level}: {passed}/{len(blocks)} PASS")
        for block in blocks:
            result = report["blocks"][block["id"]]
            print(f"  [{result['status']}] {block['id']}")
            for check in result["checks"]:
                if check["status"] != "PASS":
                    reason = check.get("reason") or check.get("measured") or ""
                    print(f"    {check['id']}: {check['status']} {reason}".rstrip())

    next_action = report["next"]
    if next_action["action"] == "complete":
        print("NEXT: complete — every leaf reached the target with passing checks")
    elif next_action["action"] == "repair":
        print(f"NEXT: repair {', '.join(next_action['failing'])}; change one cause, rerun this loop")
    elif next_action["action"] == "provide_check":
        print(f"NEXT: provide a check adapter for {', '.join(next_action['missing_checks'])}")
    else:
        targets = ", ".join(f"{item['block']} ({item['level']} -> {item['to']})" for item in next_action["decompose"])
        print(f"NEXT: decompose {targets}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("design", nargs="?", default="design/design.json")
    parser.add_argument("--config", default="design/checks.json", help="check adapter config")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    design = Path(args.design)
    doc, error = load_json(design)
    if error:
        print(f"FAIL: {error}")
        return 2

    errors = validate_design.validate(doc)
    if errors:
        print(f"FAIL: {len(errors)} structural error(s)")
        for message in errors:
            print(f" - {message}")
        return 2

    adapters: dict = {}
    config_error = None
    config_path = Path(args.config)
    if config_path.is_file():
        config, config_error = load_json(config_path)
        if config_error is None and isinstance(config, dict):
            adapters = config.get("checks", {})
            if not isinstance(adapters, dict):
                config_error = "checks must be an object"
                adapters = {}

    report = build_report(doc, design, adapters, config_error)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report, doc)
    return report["exit"]


if __name__ == "__main__":
    sys.exit(main())
