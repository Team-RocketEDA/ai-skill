---
name: Hierarchical Chip Design
description: Design a chip from a natural-language specification by decomposing it level by level and verifying every level with the project's EDA checks. Use when the user asks to design, decompose, or verify a digital or analog circuit in a RocketEDA project.
---

# Hierarchical Chip Design

This skill is **model- and agent-agnostic**. `skill.json` is the integration contract:
load it, read this file, and call the loop. Nothing here depends on a particular agent
framework.

The loop is the heartbeat:

```text
edit -> render diagram -> run loop -> read NEXT -> act -> repeat
```

You propose requirements, blocks and artifacts. **The loop decides whether the current
level is verified and whether you may descend.** Do not decide the next stage yourself,
and never report a check result you did not receive from the loop or the EDA.

## The one rule

Only the loop/EDA verifies. `PASS` means a current run on the current design said
`PASS`. `FAIL`, `NOT_RUN` and `UNSUPPORTED` are reported exactly as returned. If nothing
ran, say "not run".

## Files

| Path | Owner | Meaning |
|---|---|---|
| `design/design.json` | you | canonical requirements, hierarchy, ports, connections, traceability |
| `design/*.v`, `design/*.sv` | you | RTL artifacts referenced by blocks |
| `design/*.cir`, `design/*.sp` | you | SPICE artifacts referenced by blocks |
| `design/diagrams/*.mmd` | derived | Mermaid diagrams rendered from `design.json` |
| `design/checks.json` | user/CI | trusted adapter config — read-only to you |
| `tests/` | you | independent testbenches and vectors |
| `constraints.yaml` | user | targets, measurement formulas, iteration limit — read-only |
| `results/` | engine | evidence and waveforms — read-only |
| `ip/manifest.yaml` | engine | block registry — read-only; register via the engine tool |

`design.json` records plan state (`PENDING`, `GENERATED`, `NEEDS_CLARIFICATION`,
`BLOCKED`), never a verdict. The validator rejects `VERIFIED` and `FAILED`.

## Cadence

After **every** edit to `design.json` or an artifact:

1. Render the current diagram:
   ```bash
   python <skill>/scripts/render_diagram.py design/design.json --out design/diagrams/<block>.mmd
   ```
2. Run the loop:
   ```bash
   python <skill>/scripts/design_loop.py design/design.json
   ```
3. Read `NEXT` and do exactly that:
   - `repair <blocks>` → use `prompts/03-repair.md`.
   - `provide_check <ids>` → ask the user/CI to add the adapter or install the tool. Do
     not write a check that can only pass.
   - `decompose <block> (level -> next)` → use `prompts/02-decompose.md`.
   - `complete` → use `prompts/04-report.md` and stop.
4. Repeat. End the turn only when the loop says `complete` or you are blocked and have
   reported why.

Do not skip the loop after a "small" edit. A width change can invalidate a parent.

## Loop semantics

The loop runs in this order:

1. **Structure** — the validator checks ids, hierarchy, widths, directions, drivers,
   loops and requirement coverage. Structural failure stops everything (exit 2).
2. **Leaf behavior** — each leaf proves its own non-`struct.*` checks before it may be
   decomposed. Missing adapter or tool → `NOT_RUN`/`UNSUPPORTED` (exit 4). A leaf at
   `rtl`, `gate` or `transistor` that declares only `struct.*` checks is `NOT_RUN`:
   structure alone cannot prove a lower level.
3. **Parent composition** — a parent's behavior is checked only after every child
   passes. This avoids the deadlock of asking a parent to prove itself before its
   children exist.
4. **Descent** — only when the current level passes. A verified leaf below the target
   returns `decompose` (exit 3).

Exit codes: `0` complete, `1` repair, `2` invalid, `3` decompose, `4` blocked.

`design/checks.json` maps a check id to a command:

```json
{
  "checks": {
    "func.truth_table": {
      "command": ["python", "tools/check_truth_table.py", "--design", "{design}", "--block", "{block}", "--check", "{check}"],
      "timeout": 120
    }
  }
}
```

The command prints one JSON result:

```json
{"status": "PASS", "checks": [{"id": "func.truth_table", "status": "PASS", "evidence": "run-17"}]}
```

`struct.*` checks are built in. Everything else needs an adapter; a missing adapter is
`NOT_RUN`, never a pass. The full protocol is in `references/eda-adapter.md`.

## Workflow

### 0. Read

- Load `skill.json`, `constraints.yaml` (via the engine tool) and any existing
  `design/design.json`.
- Read the iteration limit and the checks the user requires.
- Search the IP catalog before creating a block.

### 1. Specification — `prompts/01-spec.md`

Write requirements with stable ids, text, `source` (`user` or `inferred`) and at least one
testable `acceptance` criterion. Add a `spec`-level root block with the boundary ports.
If a critical fact is missing or contradictory, ask one targeted question and set the
block to `NEEDS_CLARIFICATION`. Never invent a width, clock or reset.

### 2. Architecture and decomposition — `prompts/02-decompose.md`

Create children one level deeper than the block being split. For each child: `purpose`,
`ports`, `requirements`, `required_checks`, `contract`, `kind`. Connect ports with
`{"from": "parent.port", "to": "child.port"}`. A parent input may drive a child input; a
child output may drive a parent output; otherwise connect siblings only.

Split only when the children's contracts together implement the parent contract. Keep
the parent's boundary unchanged. Do not add a block without a requirement.

### 3. Verify and descend

Run the loop. A level is not done because the diagram looks right; it is done when the
loop returns `PASS` for every block at that level. If the loop says `decompose`, split the
named leaves. If it says `repair`, fix one cause at a time. If it says `provide_check`,
do not fake the check: ask for the adapter or report the tool as missing.

### 4. Levels

| Level | Artifact | What proves it |
|---|---|---|
| `spec` | requirements + root ports | validator: acceptance criteria present |
| `architecture` | blocks, ports, connections, contracts | structural checks + requirement coverage |
| `rtl` | Verilog/SystemVerilog + testbench | compile/lint + independent vectors |
| `gate` | Boolean network or mapped netlist | equivalence under a named library |
| `transistor` | SPICE netlist + models | DC/AC/transient vs constraints |

Stop at `target_level`. Different branches may stop at different levels; report the
frontier instead of forcing symmetry. A Boolean network is not a mapped netlist. A
generic transistor model is not a foundry PDK.

### 5. Repair — `prompts/03-repair.md`

1. Quote the measurement or log line that shows the failure.
2. State one hypothesis linking evidence to cause.
3. Make the smallest edit that tests it.
4. Rerun the loop.
5. If two attempts do not improve the measurement, change strategy.

Never edit `constraints.yaml`, `results/` or a testbench to manufacture a pass. If a
change alters a parent interface, mark dependents `PENDING`; the loop will re-gate them.

### 6. Report — `prompts/04-report.md`

End with a short report: requirement coverage, per-level pass counts, the frontier,
iterations used, and what was not run. Name the run id behind every number.

## Stopping

Stop and report when the loop returns `0` (complete), `1` (after the repair budget),
`4` (missing tool/adapter), or the runner reports `iteration_limit_reached`. Partial
completion is valid. Never claim success after exhausting retries.

## If your agent cannot run commands

Expose the loop and renderer as tools. Do not simulate their output, and do not decide a
gate result yourself. If the loop cannot run, the design is `BLOCKED`, not `PASS`.

## References

- `references/hierarchy.md` — data model, levels, decomposition rules.
- `references/verification.md` — gates, statuses, evidence, invalidation.
- `references/eda-adapter.md` — check protocol, adapter config, Rocket mapping.
- `prompts/` — one prompt per stage, JSON-shaped for small models.
