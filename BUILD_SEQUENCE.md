# Build Sequence

Work in order. Each task is one Claude Code session. `docs/PROTOTYPE_SPEC.md` is authoritative; this is the ordering.

---

## Before starting

Verify model API access works end to end with a trivial call.

Record decision rules in `evals/decision_rules.md` before any experiment runs. The numbers are in Spec Section 9. Copy them verbatim so they cannot drift after results are seen.

---

# Stage 1: Reference data

Everything downstream depends on this. If the reference data is wrong, every metric produced later is meaningless.

## Task 1.1: Splits and reference labels

Assign splits before writing anything.

| Split | Cases | Procedures |
|---|---|---|
| Development | 12 | MRI and knee |
| Held-out test | 8 | MRI and knee |
| Transfer | 5 | Fusion |

Build `corpus/labels.json`. One entry per case, written **before any document exists**:

```json
{
  "case_id": "TKA-014",
  "parent_case_id": null,
  "procedure_id": "total_knee_arthroplasty",
  "criteria_set_version": "1.0.0",
  "split": "development",
  "scenario_tags": ["near_threshold_duration", "silent_absence"],
  "reference_version": "1.0",
  "expected": {
    "C1": {"clinical_status": "MET", "evidence_units_required": 1},
    "C3": {"clinical_status": "AMBIGUOUS", "reason_codes": ["VAGUE_DURATION"], "evidence_units_required": 2}
  },
  "notes": "Therapy documented without dates. C6 infection status never addressed."
}
```

Scenario coverage required across the set: evidence in an unrelated section, duration without dates, contradictory statements, near-threshold documentation, requirements never addressed, and concise versus verbose versions of the same facts.

**NOT_MET is used sparingly.** Only where the label can state why the evidence is affirmatively contradictory, that the record is complete on that point, and that no exception applies. Everything else that falls short is AMBIGUOUS.

Report the distribution when done. Heavy skew toward MET means the set will not discriminate.

## Task 1.2: Generate documents

For each label, write a packet embodying exactly that truth. Multiple documents, different clinical voices, realistic clutter including irrelevant history and copy-forward text.

Never annotate the evidence. No `(C3 NOT MET)` markers.

Store as `corpus/cases/{case_id}/`.

## Task 1.3: Manual check

Read every case against its label. If the correct answer cannot be determined from the documents alone, either the document or the label is wrong. Fix before proceeding.

**This check cannot be skipped.** Without it the evaluation is circular.

Lock the held-out and transfer splits after this check. Do not open them again until Stage 3.

## Task 1.4: Dataset manifest

`corpus/manifest.json` with case id, parent case id, procedure, split, scenario tags, reference version.

---

# Stage 2: Pipeline and evaluation

## Task 2.1: Steps 1 and 2

Criteria loading by procedure code, returning a versioned set. Document ingestion with stable ids, content hashes, canonical span positions.

Text and text-based PDF. Detect scanned or empty documents and report explicitly. Count tokens before any model call and return an explicit input-limit result rather than truncating.

## Task 2.2: Step 3, both configurations

Baseline A and Candidate B sharing an **identical prompt**. The only difference is call structure.

Schema-validated output per Spec Section 3. Retain raw extraction output separately from verified output.

Sequential execution. No concurrency.

## Task 2.3: Steps 4 and 5

Quote verification by string match against a canonical representation, retaining a mapping back to source where normalization is applied.

Support verification receiving criterion, exceptions, proposed status, evidence spans, and surrounding context. No packet. Skip for missing-evidence outputs making no affirmative claim.

## Task 2.4: Evaluation harness

Command line, independent of any interface.

Primary metrics, fully graded: evidence recall, evidence precision, incorrect mismatch count with affected cases listed, complete-processing rate, cost and latency per case.

Supporting diagnostics, reported without exhaustive grading: citation validity, ambiguous behavior, verifier false acceptance.

Results written to timestamped files so runs are comparable.

## Task 2.5: Claim-verification set

Twelve to eighteen evidence bundles, separately annotated. Include supported claims, real but irrelevant quotes, incorrect dates, negation errors, incomplete evidence, contradictions.

These validate the support verifier. They are **not** the criterion-status labels and cannot be substituted for them.

## Task 2.6: Development run

Run A and B on the 12 development cases. Record everything.

---

# Stage 3: Experiment, interface, demonstration

## Task 3.1: Improvement round — NOT PERFORMED

**Scope decision, recorded 2026-09-10 with the reasoning rather than omitted
silently.**

The task as written: inspect development failures, identify one targeted
change, apply it to **both** configurations, re-run both on development, record
before and after, then freeze.

### What it was for

Two things. A measurable improvement, and a demonstration purpose — showing
that measurement drove a decision rather than decorating one already made.

### Why it is not performed

**The demonstration purpose is better served by the comparison itself.** The
A-versus-B result is a case of measurement producing an unwelcome answer:
Candidate B, the hypothesis the architecture was built to test, improved recall
by a real margin and failed the threshold on precision. That is a stronger
demonstration of measurement driving a decision than a tuning round chosen to
succeed, because nobody selected the outcome.

**Three targeted changes were already made and measured**, each prompted by a
failure and applied to both configurations because both share one prompt
builder:

| Change | Prompted by | Measured effect |
|---|---|---|
| Prompt 1.1.0 | TKA-004 C7 contract rejection: `addresses_rule` and the output contract disagreed | Rejection removed |
| Prompt 1.2.0 | Two of 114 citations failed on one letter's case | Case failures 2 to 0 |
| `settings/2` and `parser/2` | Extended thinking consuming most of the output budget invisibly | MRI-007 from failing at the token limit to 22 seconds; run variance from a ninefold spread to 1.1 percent |

The third is the improvement round in substance. It was prompted by inspecting
a development failure, applied to both configurations, and both were re-run
with before and after recorded.

**A fourth change now would confound the comparison.** Development has been
looked at throughout, and the obvious targeted change from these results —
addressing Candidate B's precision, which fell 14.5 points because it returns
188 spans against Baseline A's 130 — would be a change aimed at one
configuration's failure mode. Applying it to both, as the task requires, would
mean changing Baseline A to fix a problem it does not have.

### What this costs

A tuning round with a clean before-and-after on a single named change is not
in the record. The three changes above were each made mid-investigation, and
while each was measured, none was isolated the way this task intended.

Configurations are frozen at `extraction/1.2.0`, `settings/2`, `parser/2` for
held-out and transfer.

## Task 3.2: Held-out and transfer

Run both frozen configurations on the 8 held-out cases. Run the 5 transfer cases separately.

Report paired results: for the same cases, which improved, which worsened, which unchanged. Report criterion-level counts alongside case-level.

Apply the decision rule as written. If the threshold is not met, retain the baseline and record why.

Do not tune after this. If a finding prompts a change, disclose that the test has been used for development.

## Task 3.3: Interface

Streamlit. Case selection, criteria version displayed, run analysis, evidence map showing processing state and clinical result separately.

Click a citation to open the source at the cited span. AMBIGUOUS visually distinct from NOT_MET with reason codes visible.

Reviewer correction. Corrections stored separately from model output and
reference labels, and unreadable by the scorer.

**Reviewer correction is in scope and the reason is specific.** The design
claims the system surfaces evidence and a person decides. Without somewhere to
record that decision, the claim is asserted and never demonstrated. A read-only
evidence map shows the first half of the claim and leaves the second half as
an assertion about a workflow nobody can see.

**Add-document and re-run are deliberately out of scope.**

The requirement is that a new document creates a linked run without
overwriting history. The hard part is not adding the document — it is run
lineage. Once two runs exist for one case, every status in the earlier run is
either superseded or still current, and nothing about a stored result says
which. An interface that shows both, or shows the newer without marking the
older as replaced, presents stale clinical statuses as though they were
current. That is the failure mode this whole system is built to avoid, arriving
through the back door.

Doing it properly means a supersession model: which run replaces which, at
what granularity, what happens to a criterion the new document does not touch,
and how a reviewer sees that a row they read yesterday no longer holds. That is
real design work and it is not worth doing badly to reach a checkbox.

Recorded as a scope decision rather than an omission.

Synthetic notice on screen. No decision control anywhere.

**Latency was a design constraint and is no longer one.** This note previously
described an unpredictable multi-minute wait. That problem had a cause, the
cause was found, and the numbers below replace the earlier ones entirely.

Measured over two Baseline A runs of the development split under
`extraction/1.2.0`, `settings/2`, `parser/2`:

| | run 1 | run 2 |
|---|---|---|
| slowest case | 36.2s | 38.7s |
| total wall clock, 15 cases | 338s | 342s |
| difference between runs | | **1.1 percent** |

**The slowest case is under 40 seconds and stable across runs.** A live
demonstration can hold that, and because the pair agrees to within about one
percent, the figure can be relied on rather than hoped for.

### What the earlier note said, and why it was wrong

It recorded MRI-007 running at 151, 238 and 27 seconds on identical input, and
MRI-008 hitting a 433-second timeout, and concluded that no maximum bounded the
wait and that pre-selecting a fast case gave no protection. Both statements
were true of the system as it then stood and neither is true now.

The cause was **extended thinking, on by default and never disabled**,
consuming most of the output budget invisibly and varying adaptively per
request. Disabling it cut MRI-007 from 238 seconds to 22 and removed the
variance. `docs/DATA_CARD.md` records the finding in full.

The lesson worth keeping is not about latency. **A performance characteristic
attributed to the service turned out to be a configuration nobody had set**,
and it was described in this file as an unavoidable constraint for several
hours before anyone looked underneath it.

### What Task 3.3 should still do

Streaming step completion remains worthwhile — a reviewer watching Steps 1, 2
and 4 finish while Step 3 runs is better served than one watching a spinner —
but it is now a courtesy rather than a mitigation. Candidate B's incremental
per-criterion results are likewise a nice-to-have rather than a necessity.

Concurrency is still excluded: Spec Section 11 fixes sequential execution for
the duration of the experiment.

## Task 3.4: Fault injection controls

Two clearly labeled deterministic controls:
- Force an unverifiable quote, showing rejection and preserved reason
- Force a document read failure or model timeout, showing PARTIAL or FAILED processing rather than a clinical result

Labeled as injected faults. They demonstrate handling, not observed error rates.

## Task 3.5: Prompt injection challenge

A small set of documents containing instruction-like text. Confirm structural separation holds. Report results without claiming resistance is guaranteed.

## Task 3.6: Demonstration rehearsal

Run the six required demonstrations from Spec Section 13 end to end.

---

## Session notes

One task per session. Long sessions drift.

Commit between tasks.

Track where Claude Code needed correcting, particularly any drift toward producing a recommendation or converting missing evidence into NOT_MET.

---

## Scope discipline

Stage 1 carries the most work and produces nothing visible. It is the stage most likely to be shortened under pressure, and the one that cannot be shortened without invalidating everything built on top of it.

If Stage 1 must be reduced, cut transfer cases from five to three. Do not cut the manual check in Task 1.3.