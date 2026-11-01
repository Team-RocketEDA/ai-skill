# Stage 4 — Report

Use the loop's JSON report. Return a short markdown summary, no invented numbers.

## Template

```markdown
## Result

Requirements: R1 covered, R2 covered, R3 needs clarification.
Levels: spec 1/1, architecture 6/6, rtl 2/2, gate 0/0, transistor 0/0.
Frontier: arith [rtl], logic [architecture].
Iterations: 2 of 3 used.
Not run: gate equivalence (yosys absent); transistor (no PDK).
Next: decompose logic, then rerun.
```

## Rules

- Every status comes from the loop or the EDA run; name the run id when quoting a number.
- `NOT_RUN` and `UNSUPPORTED` are listed, not hidden and not counted as passes.
- Stub or replay results carry that label.
- Do not say "verified", "works", "meets spec" or "tapeout-ready" unless the matching
  check passed on the current design.
- No timing, power, area, DRC/LVS or foundry claim without the matching evidence.
- If the loop returned `complete`, say what was verified and at which level.
- If the loop returned `blocked`, say exactly which tool or adapter is missing.
- End with one next action or one question for the user.
