# Held-out result: the adoption decision

**Spec Section 9 places the decision here.** Both configurations frozen at
`extraction/1.2.0`, `settings/2`, `parser/2`, `claude-sonnet-5`, sequential.
Nine cases, 53 scorable criterion instances, **7 independent observations** —
TKA-103V is derived from TKA-103 and MRI-103's variant likewise, so case-level
differences driven by those pairs are one finding observed twice.

Run 2026-09-10, once per configuration, after the development comparison and
after both configurations were frozen.

## Primary metrics

| Metric | Baseline A | Candidate B | B − A |
|---|---|---|---|
| Evidence recall | **43 of 53 (81.1%)** | 40 of 53 (75.5%) | **−5.7 pp** |
| Evidence precision | **46 of 85 (54.1%)** | 46 of 108 (42.6%) | **−11.5 pp** |
| Status agreement | 47 of 53 (88.7%) | 46 of 52 (88.5%) | −0.2 pp |
| Complete processing | 53 of 53 (100%) | 52 of 53 (98.1%) | −1.9 pp |
| Citation validity | 84 of 85 (98.8%) | 108 of 108 (100%) | +1.2 pp |

**Critical errors**, counts with instances named, never a rate:

| | Count | Instances |
|---|---|---|
| Baseline A | 1 | `TKA-103V C4` |
| Candidate B | 2 | `TKA-103 C4`, `TKA-103V C4` |

Zero instances in the reference-NOT_MET-returned-MET direction under either
configuration.

## The threshold, applied as written

Section 1 adopts Candidate B only if all three hold:

| Condition | Result |
|---|---|
| Evidence recall improves by at least 10 pp | **−5.7. Not met.** |
| Incorrect mismatch count does not increase | 1 to 2. Within the measured ±2 floor. |
| Evidence precision does not fall by more than 5 pp | **−11.5. Not met.** |

## The decision

**Candidate B is not adopted. Baseline A is retained for the prototype.**

Stated in the form Section 13 requires: *this small held-out evaluation did not
provide sufficient evidence to justify the candidate's additional operating
cost, and the baseline was retained for the prototype.* No claim of equivalence
is made, and no claim that per-criterion calls never help.

## Reading the critical error count

An increase of one falls **inside Baseline A's measured floor of ±2 instances**,
recorded in `decision_rules.md` before Candidate B ran anywhere. It is
reported as an increase that cannot be distinguished from noise at this corpus
size, with both instances named. Not as Candidate B failing this condition, and
not as passing it.

The decision does not rest on it. Recall and precision both fail outside any
plausible floor.

Note also that `TKA-103 C4` and `TKA-103V C4` are the density pair. Candidate
B's two critical errors are the same criterion in a concise and a verbose
rendering of one case.

## Recall reversed direction between splits

On development Candidate B gained **+8.3 points** of recall. On held-out it
lost **5.7**. A fourteen-point swing on the primary objective.

**This is the expected direction of the split discipline working, and it is
recorded as the finding rather than as an anomaly.**

Development was inspected continuously for days. Every prompt version, parser
fix, reference amendment and settings change in this project was made with
those fifteen cases in view. Held-out was never inspected: it was enumerated
from its packets before any model call touched it, locked, and opened once.

A metric that looks better on the inspected split and worse on the uninspected
one is what that asymmetry predicts. The development recall figure was the only
number that favoured Candidate B, and it did not survive the split reserved for
deciding.

**Precision, by contrast, was consistent across both splits**: −14.5 on
development, −11.5 on held-out, with the same mechanism visible in both
denominators. Candidate B returned 108 spans against Baseline A's 85 here, and
188 against 130 on development. Per-criterion calls make the model cite more,
and the additional citations largely fall outside the acceptable sets. Recall
rises where extra citing happens to catch a required unit and precision falls
because most of it does not.

That a metric behaved consistently across splits while another reversed is
itself informative: the precision effect is a property of the call structure,
and the development recall gain was not.

## Operational

| | Baseline A | Candidate B | Ratio |
|---|---|---|---|
| Extraction calls | 9 | 55 | 6.1x |
| Input tokens | 78,471 | 430,437 | **5.5x** |
| Wall clock | 211s | 372s | **1.8x** |

Recorded in `decision_rules.md` before Candidate B ran anywhere: roughly six
times the tokens and twice the wall clock, because Step 5 scales with claims
produced rather than with how they were produced. Measured 5.1x and 1.7x on
development, 5.5x and 1.8x here. **The predicted mechanism held on both
splits**, and the two operational measures move by different factors as
recorded.

Cost was not binding at prototype scale and did not enter the decision. It is
recorded because Section 1 requires it.

## Open question, not investigated

**Whether Candidate B is inconsistent across runs, or whether something about
the held-out split interacts with per-criterion calls, is unresolved.**

What would resolve it: repeated Candidate B runs on both splits, enough to
measure its own repeatability floor rather than borrowing Baseline A's. That
floor is currently unmeasured, and Candidate B makes six times the calls, so it
has more exposure to whatever varies.

**Not done, and the reason is that the decision does not turn on it.** Both
failing conditions are outside any plausible floor: recall is 5.7 points in the
wrong direction against a 10-point improvement requirement, and precision falls
11.5 against a 5-point tolerance. No repeatability measurement would move
either across its threshold.

A partial investigation would also weaken the split-discipline finding above,
which is well supported by the asymmetry in how the two splits were treated.

## What this establishes and what it does not

**Establishes:** on 53 held-out criterion instances across 7 independent
observations, per-criterion extraction calls did not improve evidence recall
and reduced evidence precision, at 5.5 times the input token cost.

**Does not establish:** that per-criterion calls never help, that the effect
would hold at a different corpus size, or that a differently written
per-criterion prompt would behave the same way. Both configurations share one
prompt builder by construction, so what was tested is call structure holding
prompt constant, which is the question Section 7 poses and no more.
