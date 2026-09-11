# Transfer result: an unseen procedure

Baseline A, the configuration retained after the held-out decision. Frozen at
`extraction/1.2.0`, `settings/2`, `parser/2`. Five lumbar fusion cases, 43
scorable criterion instances, run once on 2026-09-10.

Candidate B was not run here. The adoption decision was made on held-out per
Spec Section 9, and transfer measures the retained configuration on unfamiliar
material.

## Metrics

| Metric | Baseline A |
|---|---|
| Evidence recall | 31 of 44 (70.5%) |
| Evidence precision | 30 of 52 (57.7%) |
| **Status agreement** | **32 of 35 (91.4%)** |
| Complete processing | 35 of 43 (81.4%) |
| Citation validity | 51 of 52 (98.1%) |
| Mean returned spans | 1.21 per instance |
| Superset rate | 1 of 43 (2.3%) |

**Critical errors: 1.** `LF-201 C1`, reference AMBIGUOUS returned as NOT_MET.
Zero in the reference-NOT_MET-returned-MET direction.

Confusion, reference down:

| Reference | n | Returned |
|---|---|---|
| MET | 18 | MET 16, AMBIGUOUS 2 |
| AMBIGUOUS | 16 | AMBIGUOUS 15, NOT_MET 1 |
| NOT_MET | 1 | NOT_MET 1 |

Operational: 5 extraction calls, 48,474 input and 11,895 output tokens, 140.5
seconds.

## Status agreement is the highest of any split

91.4 percent, against 88.7 on held-out and 85.9 to 88.1 on development. On a
procedure never seen, with a nine-criterion set against five and seven
elsewhere.

Recall is the lowest of any split at 70.5 percent. Taken together the shape is
consistent: **the model reaches the right conclusion reliably while recovering
fewer of the required units.** On an unfamiliar criteria set it locates enough
to decide and less than the reference asks for.

## Complete processing at 81.4 percent is one packet

Eight of the 43 instances were contract rejections, and **seven of the eight
are LF-205**, with the eighth `LF-203 C3`. Every one is the same defect:

```
MISSING_EVIDENCE returned alongside cited evidence
```

LF-205 is the `silent_absence` case. Its funding request form marks eight
fields `NOT HELD` — neurological examination, smoking status, psychological
assessment, infection screening among them — and the attached transmittal
records the outside practice's notes as requested twice and not received.

The model read that correctly. `LF-205 C2` returned `AMBIGUOUS` with
`MISSING_EVIDENCE`, which is the reference answer exactly, and cited the
`NOT HELD` fields and the line *"none is available to this department."* The
output contract requires MISSING_EVIDENCE to carry an empty evidence list, so
the result was rejected.

**Strip LF-205 and complete processing is 34 of 34.**

### This was predicted before it was observed

While building the claim-verification set on the same day, LF-205's `NOT HELD`
fields were classified as `ruled_out` rather than `also_acceptable`, with the
reason recorded in `evals/amendment_log.md`:

> A model citing a NOT HELD line **alongside** MISSING_EVIDENCE would be
> rejected by the output contract, which requires that code to carry an empty
> evidence list.

That was a prediction about behaviour never observed, made from the contract
and the packet. Seven of nine LF-205 criteria were rejected in exactly that
way.

### It is a prompt gap, not a model error

Prompt 1.2.0 states that a passage which does not address the requirement goes
in the explanation rather than the evidence list. It does not anticipate a
document that **systematically enumerates absences**. A form of `NOT HELD`
fields is the most citable-looking evidence of absence a packet can contain,
and the instruction gives no guidance for it.

Per `decision_rules.md`, contract rejections are reported apart from clinical
errors and are never counted as status errors. That the seven carried correct
clinical readings is recorded as a diagnostic and enters no score: the system
did not produce a usable result, and crediting it for nearly doing so would
measure the wrong thing.

The fix is a prompt clause. It is **not applied**, because both configurations
are frozen and changing the prompt after the adoption decision would leave the
recorded comparison describing a system that no longer exists.

## What this establishes, and what it does not

**Establishes:** on an unseen procedure with a larger criteria set, the
retained configuration reached the reference status on 32 of 35 assessable
instances, with one critical error and no reference-NOT_MET returned as MET.

**Does not establish** anything about semantic interpretation or
document-density robustness on unfamiliar material. `decision_rules.md`
Section 3 records why: **the five fusion cases carry no semantic-interpretation
instance and no density pair.** Buried evidence in this split is positional —
the criterion's own vocabulary is present and only its location is unexpected.

Reported in those terms. "Held up on transfer" without that qualification would
read as a broader generalization claim than five cases of one procedure
support.

**One run.** No repeatability floor was measured on this split, and Baseline A's
development floor of 1.0 point on recall is a proxy across a different split
and procedure.
