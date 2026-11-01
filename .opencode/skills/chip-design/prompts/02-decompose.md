# Stage 2 — Decompose one level

Return **JSON only**, no prose.

## Input

- the parent block (contract, ports, requirements, level);
- the project's target level and constraints;
- any existing children of the parent.

## Output

```json
{
  "children": [
    {
      "id": "arith",
      "parent": "alu",
      "level": "architecture",
      "kind": "combinational",
      "purpose": "Shared add/subtract datapath with carry out.",
      "status": "PENDING",
      "requirements": ["R1"],
      "required_checks": ["struct.widths", "func.arithmetic"],
      "contract": "y = sub ? a - b : a + b; carry is the 9th bit.",
      "ports": [
        {"name": "a", "direction": "input", "width": 8, "kind": "logic"},
        {"name": "y", "direction": "output", "width": 8, "kind": "logic"}
      ]
    }
  ],
  "connections": [
    {"from": "alu.a", "to": "arith.a"}
  ]
}
```

## Rules

- Children are exactly one level deeper than the parent.
- Keep the parent's ports unchanged; children are an implementation detail.
- Every child input must be driven exactly once: by a parent input or a sibling output.
- Widths and directions must match exactly.
- Every child references at least one existing requirement. Add no new requirements.
- Every child has a `purpose`, a `contract` and at least one `required_checks` entry.
- No block that the requirements do not justify.
- `struct.*` checks are built in. Name behavioral checks you expect an adapter to prove.
- If the parent contract cannot be split without more information, return
  `{"question": "..."}` and nothing else.
- Do not write an artifact path until the artifact exists.
- Do not change `status` to a verdict. `PENDING` and `GENERATED` only.

## After writing

Merge the children and connections into `design/design.json`, render the diagram, run the
loop. The loop will refuse to descend until the children's checks pass.
