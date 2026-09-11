# Development result: Baseline A against Candidate B

**This is not the adoption decision.** Spec Section 9 places that on the
held-out test, and Section 7 requires both frozen configurations to run there.
What follows is development evidence: strong, consistent with a decision, and
not the pre-registered basis for one.

Recorded 2026-09-10. Both configurations under `extraction/1.2.0`,
`settings/2`, `parser/2`, `claude-sonnet-5`, sequential execution. Artifacts
selected by version recorded in the run, not by file order.

## Primary metrics

Baseline A was run twice to measure repeatability before Candidate B ran once.

| Metric | A run 1 | A run 2 | Candidate B | B − A mean | Floor |
|---|---|---|---|---|---|
| Evidence recall | 81 of 103 (78.6%) | 82 of 103 (79.6%) | **90 of 103 (87.4%)** | **+8.3 pp** | 1.0 |
| Evidence precision | 93 of 130 (71.5%) | 94 of 132 (71.2%) | **107 of 188 (56.9%)** | **−14.5 pp** | 0.3 |
| Status agreement | 73 of 85 (85.9%) | 74 of 84 (88.1%) | 76 of 85 (89.4%) | +2.4 pp | 2.2 |
| Complete processing | 85 of 87 (97.7%) | 84 of 87 (96.6%) | 85 of 87 (97.7%) | +0.6 pp | 1.1 |
| Citation validity | 128 of 130 (98.5%) | 132 of 132 (100%) | 188 of 188 (100%) | +0.8 pp | 1.5 |

The floor column is the difference between the two Baseline A runs, measured
before B ran and recorded in `evals/decision_rules.md`. It is what this corpus
can resolve, not a threshold.

## The threshold, applied as written

Section 1 adopts Candidate B only if all three hold. On development:

| Condition | Development result |
|---|---|
| Evidence recall improves by at least 10 pp | +8.3. **Not met.** |
| Incorrect mismatch count does not increase | 1–3 to 6. **Increased.** |
| Evidence precision does not fall by more than 5 pp | −14.5. **Not met.** |

Two of three fail and neither is marginal. **The decision itself is deferred to
held-out, where both configurations run frozen at these versions.**

## What each figure means

**Recall +8.3 is real and short.** Eight times the floor, so this is not noise.
It is also below 10, and the threshold was fixed before any result existed and
does not move. Candidate B improves recall by a genuine margin that does not
reach the pre-registered bar.

**Precision −14.5 is the decisive movement**, at 48 times the floor. The
mechanism is in the denominators: **B returned 188 spans against A's 130** for
the same 87 instances. Per-criterion calls make the model cite more, and the
additional citations largely fall outside the acceptable sets. Recall rose
because citing more catches more required units; precision fell further
because most of the extra citing is not required evidence.

That is a coherent account of the same cause producing both movements, and it
is the kind of trade the comparison exists to expose. Whether it holds on
held-out is the question the held-out run answers.

**Critical errors rose from 1–3 to 6.** Applying the rule recorded before B
ran: Baseline A's own floor is ±2 instances, so an increase of 3 or more falls
outside it. Six against a 1–3 baseline is outside the floor and is reported as
a real increase, with every instance named:

```
MRI-001 C4, MRI-007 C1, MRI-007 C3, MRI-007 C4, MRI-008 C3, TKA-001 C3
```

Only `MRI-007 C3` is shared with Baseline A. Section 1: *a candidate gaining
recall while introducing a critical error is not an improvement.*

Candidate B's own repeatability is unmeasured. Baseline A's floor is used as a
proxy and that is an assumption, not a measurement: B makes 90 extraction calls
against A's 16, so it has more exposure to whatever varies.

## Operational

| | Baseline A | Candidate B | Ratio |
|---|---|---|---|
| Extraction calls | 16 | 90 | 5.6x |
| Input tokens | 139,665 | 706,848 | **5.1x** |
| Output tokens | 26,321 | 41,564 | 1.6x |
| Wall clock | 340s | 587s | **1.7x** |

`decision_rules.md` recorded before B ran that its cost would be roughly six
times the tokens and twice the wall clock, because Step 5 scales with claims
produced rather than with how they were produced. **Measured at 5.1x and
1.7x.** The predicted mechanism held, and the two operational measures do move
by different factors as recorded.

## Why one B run is enough here

The rule was that a difference close to the floor justifies a second run and
one clearly outside it does not. Precision is 48 times the floor and recall is
8 times it. A second B run would not plausibly move precision by 14.5 points.

The exception is critical errors, where B's floor is unmeasured. The
development conclusion does not rest on that figure.

## What this does not establish

Development is the split that has been looked at throughout. Every prompt
change, every parser fix and every reference amendment was made with these
cases in view. **A development result is the weakest form of evidence this
project produces**, and it is reported here because Section 1 requires
development, held-out and transfer to be reported separately, not because it
decides anything.
