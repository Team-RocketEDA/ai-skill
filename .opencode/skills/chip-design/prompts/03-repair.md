# Stage 3 — Repair one failure

Return **JSON only**, no prose.

## Input

- the failing block and check id;
- the measured value, target and margin;
- the log excerpt or waveform evidence;
- the iteration budget left.

## Output

```json
{
  "hypothesis": "The carry chain is 8 bits, so the 9th bit is dropped.",
  "edits": [
    {
      "file": "design/arith.v",
      "old_text": "assign carry = y[7];",
      "new_text": "assign carry = sum[8];"
    }
  ],
  "rerun": ["func.arithmetic"]
}
```

Or, when the evidence is insufficient:

```json
{"question": "Is the carry flag expected for subtraction too, or only for addition?"}
```

## Rules

- One cause per attempt. Do not bundle unrelated edits.
- Quote the evidence that supports the hypothesis.
- The smallest edit that tests the hypothesis. `old_text` must appear exactly once.
- Never edit `constraints.yaml`, `results/`, `tests/` or `design/checks.json` to make a
  check pass.
- Do not repeat a change the runner already recorded as failed.
- If two attempts do not improve the measurement, change strategy, not parameters.
- If the budget is exhausted, return `{"stop": "iteration limit", "summary": "..."}`.
- Do not claim the fix works. The loop will rerun the check.

## After writing

Apply the edit, render the diagram, run the loop. Read the new result; do not assume it.
