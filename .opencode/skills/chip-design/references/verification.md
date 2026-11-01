# Verification gates and evidence

The design is not accepted because it looks plausible. Each gate names what must be
proven, what counts as evidence, and what to report when the evidence cannot be produced.

## Status vocabulary

Check statuses from the loop or the runner (never invent others):

| Status | Meaning |
|---|---|
| `PASS` | the latest run on the current design met the target |
| `FAIL` | the latest run measured the design and missed the target |
| `NOT_RUN` | the check did not execute (missing tool, missing source, cancelled) |
| `UNSUPPORTED` | no backend exists for this check |

Plan states in `design.json` (never `PASS`/`FAIL`):

| State | Meaning |
|---|---|
| `PENDING` | not generated yet, or invalidated by an upstream change |
| `GENERATED` | a representation exists and structural checks were attempted |
| `NEEDS_CLARIFICATION` | blocked on a user answer |
| `BLOCKED` | a required gate failed and the retry budget is spent |

`PASS` is only valid when it comes from a runner result whose design hash matches the
current design. A result from an older revision is stale; report it as stale, not as a pass.

## Loop order

`scripts/design_loop.py` enforces the order; the model cannot reorder it:

1. **Structure.** `validate_design.py` checks schema, hierarchy, ports, drivers, loops and
   traceability. Any error stops the loop with exit `2`.
2. **Leaf behavior.** Each leaf runs its non-`struct.*` checks. A failed check is `FAIL`
   (exit `1`); a missing adapter, binary or malformed reply is `NOT_RUN` (exit `4`). A
   leaf at `rtl`, `gate` or `transistor` with only `struct.*` checks is also `NOT_RUN`:
   structure alone cannot prove a lower level.
3. **Parent composition.** A parent's behavioral checks run only after every child is
   `PASS`. A parent with a failing descendant is `SKIPPED`, not guessed.
4. **Descent.** A `PASS` leaf below `target_level` produces `decompose` (exit `3`). Only a
   full pass at the target produces `complete` (exit `0`).

The loop aggregates the checks it actually received. It never fills a missing result with
`PASS`, and the model's prose cannot override the exit code.

## Gate 1 — structure and architecture

Prove, without a simulator:

- every requirement is represented and every block traces to a requirement;
- every required input/output exists at the boundary;
- widths and directions are consistent;
- every non-root input has exactly one driver;
- no unintended combinational loop;
- no block or behavior the requirements do not justify;
- the child contracts together imply the parent contract.

Evidence: loop structure stage (`scripts/validate_design.py`) plus adapter results for any
non-`struct.*` checks. If neither ran, say so.

## Gate 2 — RTL

Prove the RTL matches the verified architecture:

- module ports equal the block ports (name, direction, width);
- lint/compile passes;
- testbench is independent of implementation internals;
- vectors cover normal, boundary and reset/clock behavior;
- for sequential logic: reset values, state transitions and invariants — not just a
  combinational truth table;
- the reference model is derived from the block contract, not from the RTL itself.

Evidence: tool name and version, command, exit code, vector count, failures, artifact
hashes. If no Verilog tool is available, `NOT_RUN` with the reason.

## Gate 3 — gate level

Prove the gate network implements the verified RTL:

- connectivity and single-driver checks;
- logical equivalence against the RTL under the stated library;
- fan-in/fan-out within the stated limits;
- no combinational loops or invalid latch structures;
- unmapped Boolean networks are labelled as such, never as a technology netlist.

Evidence: equivalence tool and version, library name/version, counterexample if it fails.
Without a target library and mapper, report `UNSUPPORTED` and stop at RTL.

## Gate 4 — transistor level

Prove the SPICE representation against the constraints:

- every device has a model, terminals connected, and a bulk/supply path;
- the analyses named in `constraints.yaml` ran (DC operating point, AC, transient, …);
- measured values meet the targets, or the failure is reported with the margin;
- ERC/DRC only when the deck and PDK support it;
- no claim of foundry readiness without the PDK, models and rules that were actually used.

Evidence: engine `run_id`, netlist hash, tool version, analyses, measurements, waveform
dataset path. A generic/educational model is labelled as such.

## Independent verification

The thing that checks must not be the thing that is checked.

- Structural checks are deterministic code (`scripts/validate_design.py`) or the engine.
- The loop, not the model, aggregates statuses and decides descent.
- Behavioral reference models are written from the block contract, before or independently
  of the RTL; compare outputs, not source text.
- The LLM may propose a test, but its opinion is not evidence.
- A testbench the implementation can edit into passing is suspect; keep vectors in
  `tests/` and explain any testbench change.

## Repair loop

```text
repair(block, failed_checks, budget):
    for attempt in 1..budget:
        evidence = read_measurements_and_logs(failed_checks)
        hypothesis = one cause supported by evidence
        change = smallest edit that tests the hypothesis
        apply(change)
        rerun the loop
        if the loop returns 0 or 3: return PASS
        if no measurement improved after 2 attempts: change strategy
    block.status = BLOCKED
    return BLOCKED
```

Rules:

- The iteration budget is `agent.iteration_limit` from `constraints.yaml`; each executed
  engine job spends one.
- A duplicate of a design that already failed is refused before it runs. Do not try to
  bypass it by rephrasing the same change.
- Never edit `constraints.yaml`, `results/`, `design/checks.json` or the testbench to
  manufacture a pass.
- If a change alters an interface, invalidate descendants and ancestors that depend on it.
- On budget exhaustion, stop, summarise the failures and ask the user. Do not start a new
  "attempt" under a different name.
- Repair is complete only when the loop says `complete` or `decompose`; a local edit is not
  evidence.

## Invalidation

A verification result is valid only for the design hash and inputs it was produced from.
Invalidate when:

- the block's ports, contract or artifact changes;
- a child changes in a way that can affect the parent's outputs;
- a constraint or measurement formula changes;
- the tool version or PDK changes in a way that affects the result.

Invalidation means `PENDING` in `design.json` and a note in the report. Keeping a stale
`PASS` is worse than having no result.

## Honest final report

```text
Requirement coverage: R1, R2 covered; R3 NEEDS_CLARIFICATION
Blocks: opamp [transistor] PASS (run 12); bias [architecture] PENDING
Checks: dc_gain PASS (run 12, engine, ngspice 44); widths PASS (validator); drc NOT_RUN (no deck)
Iterations: 2/3
Limits: generic models only, not a foundry PDK
Next: answer R3, then decompose bias
```

Every number names its source. "Not run" is a complete answer; a guess is not.
