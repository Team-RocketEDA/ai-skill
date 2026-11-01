# EDA adapter protocol

The skill never talks to a simulator directly. It calls a command that returns a
normalized result. That command is the adapter between this skill and your EDA.

This keeps the skill independent of the model, the agent framework and the EDA vendor.

## Configuration

`design/checks.json`:

```json
{
  "checks": {
    "func.truth_table": {
      "command": ["python", "tools/check_truth_table.py", "--design", "{design}", "--block", "{block}", "--check", "{check}"],
      "timeout": 120
    },
    "rtl.compile": {
      "command": ["verilator", "--lint-only", "-Wall", "{artifact}"],
      "timeout": 60
    }
  }
}
```

| Placeholder | Replaced with |
|---|---|
| `{design}` | absolute path to `design/design.json` |
| `{block}` | block id |
| `{level}` | block level (`spec`, `architecture`, `rtl`, `gate`, `transistor`) |
| `{check}` | check id |
| `{artifact}` | the block's `artifact` path |

Commands are argument arrays, never shell strings. No pipes, redirects or `&&`.

## Result

The command exits `0` and prints one JSON object:

```json
{
  "status": "PASS",
  "checks": [
    {"id": "func.truth_table", "status": "PASS", "evidence": "run-17", "measured": "1024/1024 vectors"}
  ]
}
```

- `status` is `PASS`, `FAIL`, `NOT_RUN` or `UNSUPPORTED`.
- If `checks` is present, the entry whose `id` matches the requested check wins.
- If no entry matches, the top-level `status` is used.
- Any other status, invalid JSON, a non-zero exit, a timeout or empty output is
  `NOT_RUN` with the reason. It is never a pass.
- `evidence` names the run id, file, command or tool version behind the result.
- `measured` and `target` are optional but recommended for the report.

## Rules

- A missing adapter is `NOT_RUN`, not `PASS`.
- A missing binary is `NOT_RUN` or `UNSUPPORTED`, with the reason.
- A stub or replay result must carry that label in `evidence` or `reason`.
- Timeouts are mandatory; default 120 s, capped by the adapter.
- The adapter must not edit the design. It reads and reports.
- The adapter config is trusted project infrastructure. The agent must not edit
  `design/checks.json`; when the loop returns `provide_check`, it asks the user/CI to add
  the adapter or install the tool.
- The adapter must not edit `constraints.yaml` or `results/`.
- The adapter must confine itself to the project and the read-only PDK roots.
- If the adapter changes the design (for example a formatter), that is a separate,
  explicit step, not a check.

## Loop contract

The loop maps each block's `required_checks` to an adapter:

- `struct.*` is built in (the validator).
- everything else must have an entry in `design/checks.json`.
- a leaf at `rtl`, `gate` or `transistor` with only `struct.*` checks is reported as
  `NOT_RUN` with id `behavioral.<block>`.

It runs structure first, then leaf behavior, then parent behavior after all children pass.
Exit codes: `0` complete, `1` repair, `2` invalid, `3` decompose, `4` blocked.

## RocketEDA mapping

When the EDA is Rocket Engine, wrap its MCP tools in a small command adapter:

| Skill check | Rocket call |
|---|---|
| `spice.dc`, `spice.ac`, `spice.tran` | `engine_run_spice` then `engine_run_job` |
| run status | `engine_get_job_status` |
| logs | `engine_get_logs` |
| latest verdicts | `engine_get_check_results` |
| available job kinds | `engine_list_job_kinds` |
| targets and formulas | `constraints.yaml` via `rocket_get_constraints` |

The engine owns targets and measurement formulas. Do not pass `min`, `max` or `expr`;
do not recompute a measurement the engine already reports. Runs are two-phase:
`engine_run_spice` admits and returns `request_id`; `engine_run_job` executes it.

The stub runner (`rocket_run_job`) is not a simulation. If its result is used, the
adapter must report `evidence: "stub"` and the skill must label it.

## Project layout the IDE reads

```text
constraints.yaml            targets, measurement definitions, iteration limit
design/                     design.json, RTL, SPICE, diagrams, checks.json
tests/                      testbenches and vectors
ip/manifest.yaml            read-only block registry
results/engine-runs/        engine evidence: <run_id>.json, <run_id>-ac.raw
exports/                    user-triggered exports
```

- Verification table: reads `results/engine-runs/` and `constraints.yaml`.
- Schematic: draws SPICE netlists from `design/` and `tests/`; RTL has no schematic
  surface today.
- Plots: read `<run_id>-ac.raw`.
- Export: project archive plus a markdown verification report.

## Permissions

If the agent framework restricts paths, the adapter and the loop run outside that
restriction as trusted tools. The agent itself must not edit `constraints.yaml`,
`design/checks.json`, `results/`, `.rocket/`, `ip/manifest.yaml` or anything outside the
project. The harness should enforce `design/checks.json` as read-only for the agent.

If the agent cannot run commands, expose the loop as a tool. A gate result the agent did
not receive is not a result.

## Known gaps

- `run_spice` is the implemented engine job kind. Digital RTL/gate jobs are planned;
  until `engine_list_job_kinds` lists them, those checks are `NOT_RUN`/`UNSUPPORTED`.
- The structural validator is not an engine operation; it runs as a script or CI step.
- PDK catalog and transistor checks depend on the engine's `library` module.
