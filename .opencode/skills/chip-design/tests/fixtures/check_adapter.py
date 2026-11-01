"""Test adapter for design_loop: prints a normalized check result."""

import json
import sys

args = sys.argv[1:]
status = "PASS"
check = ""
if "--status" in args:
    status = args[args.index("--status") + 1]
if "--check" in args:
    check = args[args.index("--check") + 1]

payload = {"status": status, "evidence": "test fixture"}
if check:
    payload["checks"] = [{"id": check, "status": status, "evidence": "test fixture"}]
print(json.dumps(payload))
