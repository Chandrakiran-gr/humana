# Cite

**Evidence mapping for utilization management.**

Given the clinical documents submitted with a prior authorization request and the
procedure code for the requested service, Cite produces an **evidence map**: one
row per medical necessity requirement, showing the requirement, a clinical
result, a processing state, the passages from the record relevant to that
requirement, and a link to each passage in its source document.

The user is a utilization management reviewer. The system produces **no coverage
determination, recommendation, or aggregate score**. The reviewer inspects the
evidence and continues the organization's established review or escalation
workflow.

> **Synthetic demonstration.** All criteria are synthetic demonstration criteria
> modeled on published coverage determination patterns. They are **not Humana
> coverage policies**. All clinical records are synthetic. No real or
> de-identified patient data is used.

---

## What was measured

29 cases, 121 documents, 189 criterion instances of which 183 are scorable.
Splits were assigned before any tuning: 15 development, 9 held-out test, 5
transfer. Held-out and transfer were opened once each.

Reference labels: MET 89 (47.1%), AMBIGUOUS 88 (46.6%), NOT_MET 6 (3.2%),
NOT_APPLICABLE 6 (3.2%). NOT_MET is rare by design — Spec Section 4 gives it a
high bar, requiring evidence to be shown affirmatively contradictory rather
than merely absent, and a label that cannot meet that bar is AMBIGUOUS.
`scripts/validate_labels.py` reprints this distribution and checks the
invariants behind it.

**You do not need to run anything to check these.** Every number below comes
from a run artifact committed to `runs/`, named in the last column. Each
artifact carries the full input hashes, prompt and model versions, settings,
every attempt including the rejected ones, tokens, timing, and the final
output.

### The A/B experiment

Two configurations sharing one prompt builder, so they cannot drift.
**Baseline A** makes one extraction call for all criteria. **Candidate B**
makes one call per criterion. Per-criterion calls were a testable hypothesis,
not an assumed improvement.

Decision rules were frozen in `evals/decision_rules.md`, copied verbatim from
Spec Section 9, **before any result existed**. `tests/test_decision_rules.py`
compares that block against the spec byte-for-byte on every run.

Held-out test, where Spec Section 9 places the decision:

| | Baseline A | Candidate B | Δ | Threshold |
|---|---|---|---|---|
| Evidence recall | **43 of 53 (81.1%)** | 40 of 53 (75.5%) | −5.7 pp | +10 required |
| Evidence precision | **46 of 85 (54.1%)** | 46 of 108 (42.6%) | −11.5 pp | −5 tolerated |
| Status agreement | 47 of 53 (88.7%) | 46 of 52 (88.5%) | −0.2 pp | |
| Complete processing | 53 of 53 (100%) | 52 of 53 (98.1%) | −1.9 pp | |
| Citation validity | 84 of 85 (98.8%) | 108 of 108 (100%) | +1.2 pp | |

**Candidate B was not adopted. Baseline A is retained.** Two of three
pre-registered conditions failed, and not narrowly.

> Artifacts — A: `20260910T223110Z_eval_batch5_A.json`,
> `20260910T223755Z_eval_batch4_A.json`. B:
> `20260910T224634Z_eval_batch5_B.json`, `20260910T225318Z_eval_batch4_B.json`.
> Write-up: `evals/results/heldout_A_vs_B.md`.

On development, B's recall was **+8.3** — still short of the +10 bar, with
precision at −14.5. **Recall reversed sign between splits** (+8.3 development,
−5.7 held-out). That reversal is recorded as an open question, not explained
away: development was inspected for days and held-out was opened once, which
is the split discipline working rather than a result to investigate after the
fact.

> Artifacts — A: `20260910T213858Z_eval_batch7_A.json`,
> `20260910T213538Z_eval_batch8_A.json`. B:
> `20260910T222444Z_eval_batch7_B.json`, `20260910T221928Z_eval_batch8_B.json`.
> Write-up: `evals/results/development_A_vs_B.md`.

### Transfer, on a procedure never used for tuning

| | Baseline A |
|---|---|
| Status agreement | **32 of 35 (91.4%)** — highest of any split |
| Evidence recall | 31 of 44 (70.5%) |
| Evidence precision | 30 of 52 (57.7%) |
| Complete processing | 35 of 43 (81.4%) |
| Citation validity | 51 of 52 (98.1%) |

One critical error; no reference-NOT_MET returned as MET.

> Artifact: `20260910T230714Z_eval_transfer_A.json`.
> Write-up: `evals/results/transfer_A.md`.

### Prompt injection

Five documents carrying instruction-like text, appended to a real packet one
at a time. Both arms run twice. No status moved toward an injected
instruction, and **0 of 10 injected documents were cited as evidence**.

An isolation arm removed the record fencing and the system-prompt separation
clause and changed nothing else. The unfenced arm behaved the same, so **on
these documents the separation is not doing detectable work** — the second of
the two outcomes named before the run. No claim of resistance is made; five
unsophisticated documents on one case cannot support one.

> Artifacts: `20260911T002810Z_injection_challenge.json`,
> `20260911T002922Z_injection_challenge_unfenced.json`, and the first run,
> `20260911T001324Z...` / `20260911T001751Z...`.

### What the measurements cost to get

Findings that changed the engineering, all in `docs/DATA_CARD.md`:

- **Extended thinking was on by default** and was the single cause of token
  variance, latency variance, and truncation failures previously attributed to
  service throughput. One case produced 6,893 / 7,732 / 11,288 / >16,000 tokens
  from identical input. Disabling it produced 2,232 tokens with *more* content.
  Every run before that fix is invalidated and excluded here.
- **Reference defect rate scales with the strength of the claim**: NOT_MET 50%,
  MET 23%, AMBIGUOUS 0%. A NOT_MET label asserts what the record *does not
  say*, which cannot be checked by reading the passage that prompted it.
- **Six of six checkers passed their first run while broken.** Generalised:
  anything verified only against material its author constructed inherits the
  author's assumptions about what the failure looks like. The scorer was built
  the other way round and nine mutations confirm each figure is load-bearing.
- **Timing is unpredictable, not slow.** The same case ranged 27 s to 238 s
  across three runs on identical input.

### What was not measured

No clinician has reviewed the output. There is no inter-rater agreement on the
reference labels — they are one author's, written before the documents existed
and validated by invariant checks, not by a second reader. Three limitations
found on the last day are recorded unfixed, because changing frozen
configurations would leave the recorded comparison describing a system that no
longer exists.

---

## Inspecting it without running it

| To see | Read |
|---|---|
| Every measured result, in full | `evals/results/*.md` |
| What went wrong and what it cost | `docs/DATA_CARD.md` |
| Decision rules, frozen before results | `evals/decision_rules.md` |
| Reference labels and acceptable evidence | `corpus/labels.json` |
| Every reference defect, cause, and how it was found | `evals/amendment_log.md` |
| Raw model output including rejected attempts | `runs/*.json` |
| The authoritative specification | `docs/PROTOTYPE_SPEC.md` |

A run artifact is self-contained. `runs/20260910T230714Z_eval_transfer_A.json`
holds all five transfer cases: for each criterion, the extracted evidence, the
quote-verification outcome per span, the support-verification outcome, the
final status, and the reference comparison.

---

## Architecture

Six steps. Steps 3 and 5 call the model; steps 1, 2, 4, and 6 are deterministic.

1. **Load criteria** — deterministic lookup by procedure code, returning a
   versioned criteria set.
2. **Ingest documents** — stable document ids, content hashes, canonical span
   positions. Text and text-based PDF. Scanned or empty documents are detected
   and reported explicitly. No OCR.
3. **Evidence extraction** — two configurations sharing an identical prompt.
4. **Quote verification** — string match against a canonical representation of
   the source. A mismatch means the quote is *unverifiable*; it does not by
   itself establish fabrication.
5. **Support verification** — a second model call receiving the criterion,
   exceptions, proposed status, and evidence spans. No packet.
6. **Assemble** — build the evidence map. Processing state and clinical result
   are shown separately.

Execution is sequential; concurrency is not implemented, and latency
conclusions depend on that. One model version throughout.

Three rules the code enforces structurally rather than by convention:

- **Clinical status and processing status are separate fields.** A parse
  failure or timeout is `processing_status: FAILED`, never a clinical result.
- **"Not found" is not "not present."** A retrieval failure resolves to
  AMBIGUOUS with MISSING_EVIDENCE, never to NOT_MET.
- **Evidence is a list.** A duration cites a start and an end; a contradiction
  cites both sides.

---

## Running it

### Recorded mode needs no API key

The repository ships with the run artifacts that back every number above, so
the interface works on a fresh clone with no credentials:

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Recorded mode is the default. It loads a saved artifact and walks through it
with citations intact, resolving each quote to its character offsets in the
source document.

### Live mode needs a key

```bash
cp .env.example .env      # then add ANTHROPIC_API_KEY
```

Live mode executes Steps 1–5 against the selected case now. It costs money,
takes roughly 15 seconds for a five-criterion case, and can fail, which is why
it is not the default. A live run shows its work as it happens: every row
appears pending, all rows wait together on the single extraction call — that
shared wait is the visible signature of Baseline A — then move one at a time
through quote verification and support verification.

Live runs write to `runs/live/`, never to `runs/`. The evaluation harness and
the recorded-run picker both read `runs/*.json`, a non-recursive glob, so a
demonstration cannot drop a file where a scored run is looked for.

The theme is pinned to light in `.streamlit/config.toml`. Without it Streamlit
follows the viewer's system preference and a palette chosen for light paper
renders unreadably on dark.

### The evaluation harness

```bash
python3 scripts/run_eval.py --split development --config A
python3 scripts/compare_runs.py <run_a.json> <run_b.json>
```

Metrics print with numerators and denominators, never as bare percentages:
`evidence recall: 43 of 53 (81.1%)`.

---

## Checking the checks

No check in this project is trusted until it has been shown to fail on a real
instance of the defect it targets. That rule exists because six of six
checkers passed their first run while broken.

```bash
python3 -m unittest discover -s tests -q    # 265 tests
python3 scripts/mutation_check.py           # 65 mutations
python3 scripts/validate_labels.py
python3 scripts/check_lexical_constraints.py
python3 scripts/check_criteria_contamination.py
python3 scripts/check_unit_counts.py
```

`scripts/mutation_check.py` breaks the code in specific ways and requires the
tests to notice. A mutation that survives is a test that proves nothing.

---

## Not in the active path

Excluded by Spec Section 14, not deferred:

- Coverage determination output in any form. No approve, deny, recommendation,
  or aggregate score anywhere in code, output, or interface
- Vector retrieval, embeddings, or graph infrastructure
- Automated policy extraction or applicability resolution
- Fine-tuning, autonomous agents, agent frameworks
- OCR, a second model, calibrated confidence
- Protected health information handling, production access control, system
  integration
- Concurrency, in this build
- Reproduction of MCG or InterQual criteria, which are licensed products
- Add-document-and-re-run in the interface: a second run for one case needs a
  supersession model, and without one the interface would show stale clinical
  statuses as current

Standards alignment is light only. Evidence references a document identifier and
version rather than a filename, criteria sets carry a version, and results are
QuestionnaireResponse-shaped. **No conformance to FHIR R4 or Da Vinci
implementation guides is claimed**, and no resource classes, `Claim/$submit`,
CQL, or X12 transport are implemented.

---

## Reviewer corrections

A reviewer can record a disagreement with any row. Corrections are append-only
JSON Lines in `corrections/`, stored separately from model output and from
reference labels, and they never overwrite either.

**Nothing in the correction store is readable by the scorer.**
`um_evidence/score.py` does not import `um_evidence/corrections.py` and must
not: a reviewer disagreeing with a result is not evidence about whether the
result matched the reference, and letting corrections reach the scorer would
let the evaluation be tuned by the people reading it. There is deliberately no
function that promotes a correction into `corpus/labels.json`.

---

## Repository structure

```
.
├── app.py                        Reviewer interface (Streamlit)
├── .streamlit/config.toml        Pinned light theme and palette
├── CLAUDE.md                     Orientation and hard constraints
├── BUILD_SEQUENCE.md             Ordered build tasks
├── NOTICE                        Rights, synthetic-material, scope
├── .env.example                  Copy to .env; keys never enter source
├── criteria/criteria_sets.json   Versioned synthetic criteria, 3 procedures
├── corpus/                       29 cases, 121 documents, labels, manifest
│   └── injection/                Instruction-like documents for the challenge
├── um_evidence/                  The pipeline
│   ├── criteria.py  ingest.py  spans.py       Steps 1-2, deterministic
│   ├── prompts.py   extract.py                Step 3
│   ├── verify.py                              Steps 4-5
│   ├── results.py                             Step 6, status vocabulary
│   ├── score.py                               Metrics with denominators
│   ├── live.py                                Live execution with progress
│   ├── faults.py                              Deterministic fault injection
│   └── corrections.py                         Reviewer store, scorer-invisible
├── scripts/                      Harness, checkers, mutation testing
├── tests/                        265 tests
├── evals/                        Frozen decision rules, results, amendments
├── docs/                         Spec and data card
└── runs/                         Artifacts backing every reported number
```

---

## Notes

`docs/PROTOTYPE_SPEC.md` is authoritative. `BUILD_SEQUENCE.md` is the ordering.
`CLAUDE.md` is orientation for Claude Code.

This is a prototype, not production software. A licensed physician must be
involved before a Medicare Advantage plan denies coverage, and some states
require medical necessity determinations to come from a licensed professional
rather than software. The architecture reflects that: the system surfaces
evidence and a person decides.
