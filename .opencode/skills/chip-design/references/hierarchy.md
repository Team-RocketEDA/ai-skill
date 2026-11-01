# Hierarchy and the canonical design model

`design/design.json` is the source of truth for **what the design is and what must be
proven**. It is not the source of truth for **whether it works** — that is the EDA's
evidence (engine runs or adapter output).

## Levels

| Level | Representation | A block is done when |
|---|---|---|
| `spec` | requirements and acceptance criteria | every requirement is testable and unambiguous |
| `architecture` | blocks, ports, connections, contracts | structure and traceability validate; every requirement is covered |
| `rtl` | Verilog/SystemVerilog + testbench | compiles/lints and passes functional vectors; otherwise `NOT_RUN` and stop |
| `gate` | Boolean network or mapped netlist | equivalent to the verified RTL under the stated library, or `UNSUPPORTED` |
| `transistor` | SPICE netlist with devices and models | the stated analyses meet the constraints; otherwise `NOT_RUN` |

A block may stop below the project's `target_level` when the required tool is missing.
Report it as a frontier, not as completion. A child's level must be the same as or
deeper than its parent's level (deeper = later in the table).

## Who descends

`scripts/design_loop.py` is the only authority on descent. After each edit it runs
structure, then leaf behavior, then parent composition, and returns `NEXT`:

| `NEXT` | Meaning | Exit |
|---|---|---|
| `repair <blocks>` | a check ran and failed | 1 |
| `provide_check <ids>` | no adapter or tool, so the check did not run | 4 |
| `decompose <block> (level -> next)` | the leaf passed and is below target | 3 |
| `complete` | every leaf reached target with passing checks | 0 |

The agent does not choose the next level. It edits `design.json`, runs the loop, and does
what `NEXT` says. A parent's own behavioral check is deferred until all its children pass,
so a parent is never asked to prove itself before its implementation exists. A leaf at
`rtl`, `gate` or `transistor` must declare at least one non-`struct.*` check; otherwise the
loop reports `NOT_RUN` and refuses to complete.

## Block record

```json
{
  "id": "arith",
  "parent": "alu",
  "level": "architecture",
  "kind": "combinational",
  "purpose": "Shared add/subtract datapath with carry out.",
  "status": "GENERATED",
  "requirements": ["R1", "R4"],
  "required_checks": ["struct.widths", "func.arithmetic"],
  "contract": "y = sub ? a-b : a+b; carry is the 9th bit.",
  "ports": [
    {"name": "a", "direction": "input", "width": 8, "kind": "logic"},
    {"name": "y", "direction": "output", "width": 8, "kind": "logic"}
  ],
  "artifact": "design/arith.v"
}
```

| Field | Rule |
|---|---|
| `id` | `^[a-z][a-z0-9_]*$`, unique |
| `parent` | `null` for the single root, otherwise an existing block id |
| `level` | one of the five levels, never deeper than `target_level` |
| `kind` | `combinational`, `sequential`, `unknown` |
| `status` | `PENDING`, `GENERATED`, `NEEDS_CLARIFICATION`, `BLOCKED` only |
| `requirements` | non-empty list of existing requirement ids |
| `required_checks` | non-empty for architecture and below; names the proof, not a verdict |
| `ports` | at least one; unique names; `width` integer ≥ 1; `kind` is logic/clock/reset/analog/supply/ground |
| `artifact` | required when `GENERATED` at rtl/gate/transistor; relative path inside the project |
| `contract` | behavior and assumptions the children must preserve (string) |

Requirements carry `id`, `text`, `source` (`user` or `inferred`) and at least one
`acceptance` criterion. Inferred requirements are allowed only when labelled; they still
need a criterion.

Verdicts, measurements, tool versions and waveform paths live in
`results/engine-runs/<run_id>.json`; revision history is the project git log. `design.json`
references artifacts and evidence by path and never duplicates a result.

## Connections

Flat list of `"block.port"` endpoints:

```json
{"from": "arith.y", "to": "select.arith_y"}
```

Valid shapes:

- parent input → child input (the parent's boundary feeds the child)
- child output → parent output (the child drives the parent's boundary)
- sibling output → sibling input

Everything else is a cross-hierarchy short. Every non-root input is driven exactly once;
outputs may fan out. Widths must match exactly.

## Decomposition algorithm

```text
decompose(block):
    if block.contract is empty: block.status = NEEDS_CLARIFICATION; return
    children = propose_children(block.contract, block.requirements)
    for child in children:
        child.parent = block.id
        child.level = next_level(block.level)
        child.requirements = subset that justifies it
        child.required_checks = checks_for(child)
    connections = wire(children, block.ports)
    errors = structural_checks(children, connections, block.contract)
    if errors: revise once, then block.status = BLOCKED and report
    else: block.status = GENERATED

# The loop, not this function, decides the next descent.
loop():
    structure()                         # validator
    for leaf in leaves: leaf_behavior() # adapters
    for parent in post_order: parent_behavior()  # only if all children passed
    if all pass and leaf.level < target: NEXT = decompose(leaf)
```

Rules:

- Propose children only from the parent contract. A block with no requirement is deleted.
- Keep the parent's ports unchanged when splitting; children are an implementation detail.
- A split must preserve every parent behavior and add none.
- Do not split a leaf whose next level has no available verification. Stop and say so.
- Sequential blocks split into state registers, next-state logic and output logic; a
  combinational loop through state is valid, a loop through only combinational blocks is not.

## Traceability

- Every requirement is referenced by at least one block (validator enforces).
- Every block references at least one requirement (validator enforces).
- A requirement's acceptance criteria name the checks that prove it.
- When a requirement changes, mark every referencing block `PENDING` and re-verify its
  descendants. Do not keep stale PASS results for a changed design.

## Validator coverage

`scripts/validate_design.py` checks:

- schema, project, target level, requirement acceptance criteria
- unique block ids, one root, known parents, no hierarchy cycles
- level ordering and target ceiling
- status enum (rejects `VERIFIED`/`FAILED`)
- port names, directions, widths, kinds
- connection endpoints, widths, directions, hierarchy scope
- exactly one driver per non-root input
- combinational loops among sibling blocks
- artifact paths are relative and inside the project
- requirement coverage

It does **not** check electrical behavior, timing, synthesis, layout or PDK rules. Those
belong to the runner and its tools.
