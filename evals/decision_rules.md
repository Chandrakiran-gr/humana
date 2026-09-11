# Decision Rules

Recorded before any experiment runs, per BUILD_SEQUENCE.md "Before starting".

**Section 1 is copied verbatim from `docs/PROTOTYPE_SPEC.md` Section 9.** Do not
edit it. Copying it here rather than referring to it is the point: the numbers
must be fixed in writing before results are seen, so they cannot be adjusted
afterwards to fit an outcome. `tests/test_decision_rules.py` re-extracts Section
9 from the spec and fails if this block has drifted from it by a single
character.

**Sections 2 and 3 are authored supplements.** They introduce no numbers and
change no threshold. Section 2 records how the reference data must be read by
the Task 2.4 harness. Section 3 records what must be said when results are
reported. Both exist because the information they carry currently lives only
inside `corpus/labels.json`, where a harness author or a reader of results would
not find it.

---

## 1. Decision rules, verbatim from Spec Section 9

<!-- BEGIN VERBATIM: docs/PROTOTYPE_SPEC.md Section 9 -->
Reference annotations define evaluable evidence units and expected criterion statuses. A returned quote counts as located evidence **only when relevant to the criterion**. Matching rules and treatment of equivalent passages are defined before scoring.

| Metric | Definition |
|---|---|
| Evidence recall | Required reference evidence units recovered, divided by required reference evidence units. Supporting and contradicting evidence reported where applicable. |
| Evidence precision | Correct and relevant returned units divided by all returned units. Repeated spans deduplicated consistently. |
| Status performance | Per-class precision, recall, and confusion matrix against reference statuses. Processing failures held as explicit nonanswers, not clinical labels. |
| Incorrect mismatch rate | Reference MET or AMBIGUOUS instances output as NOT_MET, divided by all reference MET or AMBIGUOUS instances. Counts and affected cases shown. |
| Citation validity | Raw returned spans verifying in the cited source, divided by all returned spans. Rejection rate and retained-answer coverage also reported. |
| Support quality | Manually supported final claim bundles divided by final claim bundles. Verifier accuracy and false acceptance reported separately. |
| Ambiguous behavior | Appropriate AMBIGUOUS on unresolved references reported separately from avoidable abstention on answerable references. |
| End-to-end success | Cases meeting all predefined critical conditions divided by all attempted cases. Conditions: complete processing, valid provenance, correct critical statuses, supported conclusions. |
| Operational | Failed and partial cases, wall-clock latency, token use, cost per case. Retries and both extraction and verification calls included. |

### Grading priority

**Primary comparison, fully graded:** evidence recall, evidence precision, incorrect mismatch count with affected cases listed, complete-processing rate, and actual cost and latency per case.

**Supporting diagnostics, reported without exhaustive manual grading:** citation validity, ambiguous behavior, and verifier false acceptance.

Manually grading every dimension across all splits is disproportionate to what the comparison requires. The primary set carries the product decision.

### Reporting requirements

Raw and verified scores are shown for both configurations, with counts and denominators. Development, held-out, transfer, and silver results are reported separately. Results are reported by procedure and scenario tag. A procedure difference is not attributed solely to requirement count.

**Paired results are reported for the held-out test:** for the same cases run under both configurations, which improved, which worsened, and which were unchanged.

**Criterion-level counts are reported alongside case-level results.** Criteria within a single case are not independent observations.

With small samples, tail latency and subgroup percentages are treated as exploratory.

### Decision rules, recorded before the locked run

**Primary objective:** evidence recall at criterion-instance level.

**Adoption threshold.** The held-out test contains approximately 48 criterion instances across 8 cases. A difference of fewer than 5 instances, roughly 10 percentage points, is not distinguishable from noise at this size. Candidate B is adopted only if:

- Evidence recall improves by at least 10 percentage points, and
- Incorrect mismatch count does not increase, and
- Evidence precision does not fall by more than 5 percentage points

**Cost limit.** Not binding at prototype scale. Actual cost per case is recorded for both configurations.

**Latency limit.** Not binding at prototype scale. Actual wall-clock latency per case is recorded. Sequential execution means Candidate B latency scales with criterion count.

**Critical statuses.** A criterion instance is critical where the reference status is MET or NOT_MET, meaning a determinate answer exists. Critical errors are reference MET output as NOT_MET, and reference NOT_MET output as MET. These are counted and every affected case is listed.

**Equivalent evidence scoring.** Where the reference lists alternative acceptable passages for one criterion, returning any one counts as recovered. Where the reference requires multiple passages, such as a start and end date establishing duration, all required units must be recovered to count. Alternative paths and composite requirements are marked distinctly in the reference before scoring.

A candidate gaining recall while introducing a critical error is not an improvement.

Critical failures require investigation. Zero observed failures in a small test is not proof of safety.

If the candidate does not meet the adoption threshold, the baseline is retained and the reason stated.

---
<!-- END VERBATIM -->

---

## 2. Scoring contract

Authored supplement. Operationalizes the **Equivalent evidence scoring** rule in
Section 1 against the actual shape of `corpus/labels.json`.

### Read evidence requirements from the instance, never from the criteria set

`criteria/criteria_sets.json` declares an `evidence_requirement` per criterion.
**That is the default shape of the criterion, not the shape of every instance of
it.** The value on each entry in `corpus/labels.json` under
`cases[].expected.{criterion_id}` governs scoring.

Read these two fields per criterion instance:

| Field | Meaning |
|---|---|
| `evidence_units_required` | Number of distinct reference evidence units that must be recovered |
| `evidence_requirement` | `ALTERNATIVE`, `COMPOSITE`, or `NONE` |

- **ALTERNATIVE** — any one of the listed acceptable passages counts as recovered.
- **COMPOSITE** — all required units must be recovered to count.
- **NONE** — zero units exist. The instance is scored on abstention behavior, not
  on recall, and contributes nothing to the recall denominator.

### Exclude NOT_APPLICABLE from every denominator

A criterion waived by a triggered exception pathway carries
`clinical_status: NOT_APPLICABLE`. It is out of scope for the request: not
failed, not unresolved, not asked. Six of the 189 criterion instances are of
this kind — MRI-003 C2 and C3, MRI-103 C2 and C3, LF-202 C3, LF-204 C3 — so
**183 are scorable**, split 87 development, 53 held-out, 43 transfer.

Exclude them from evidence recall, evidence precision, status performance, and
the incorrect mismatch rate. Do not count a NOT_APPLICABLE instance as a correct
abstention, and do not count a system that outputs AMBIGUOUS on one as wrong on
recall; report waiver handling separately.

Each such instance carries `if_not_waived`, recording what the documents would
have supported absent the waiver. That is diagnostic only. It is never scored,
and it must not be substituted for the criterion status.

**Effect on the held-out denominator.** Section 1 states the adoption threshold
over approximately 48 criterion instances across 8 held-out cases. The split
has since grown to 9 cases and 55 instances, of which MRI-103 C2 and C3 are
NOT_APPLICABLE, leaving **53 scorable**. Report 53 as the denominator.

The threshold is unchanged, and the reasoning is recorded here rather than
adjusted after the fact. Section 1 declares a resolution of "fewer than 5
instances, roughly 10 percentage points". At 53 instances, 5 instances is 9.4
percentage points, so the stated 10-point threshold and the stated 5-instance
resolution remain consistent with each other. The split grew because the
learnability work in Task 1.3 required additional cases, not because a
denominator was chosen after seeing a result. Section 1 is frozen verbatim and
is not edited to match; this note records the divergence instead.

### Why this is stated explicitly

28 of the 189 criterion instances carry an `evidence_requirement`
that differs from their criterion's set-level default in a way that changes
recall scoring: 16 where the set says COMPOSITE and the instance is
ALTERNATIVE, and 12 the reverse. A further 55 diverge to NONE because
the packet does not address the criterion at all. 83 instances diverge in
total, which is 44 percent of the set.

The divergence is correct and intended. `lumbar_mri` C2 is COMPOSITE by default
because a six-week duration usually has to be derived from two dated encounters,
but MRI-001 states "10 weeks" outright, so that instance requires one unit.
Conversely a set-level ALTERNATIVE criterion becomes COMPOSITE wherever the
packet makes it a contradiction, a progression across two timepoints, or a
documented complete negative, because those cannot be represented by a single
passage.

A harness that reads set-level values scores all 28 of those
instances against the wrong denominator. It raises no error and produces a
recall figure that looks plausible. The failure would not surface until someone
recomputed it by hand.

### Returning more acceptable passages than the instance requires

Recorded before the second and third development cases were run, and before any
precision figure had been computed. The first case, MRI-005, returned two
acceptable passages on C1 and two on C3 where each instance requires one under
ALTERNATIVE. The question of how that scores is settled here rather than after
the numbers exist.

**Rule. A returned span counts as correct and relevant if it matches any passage
in the instance's reference acceptable set, whether or not the instance needed
it.** Under ALTERNATIVE the acceptable set contains every listed alternative,
not only the one that satisfies recall. An instance requiring one unit that
receives two acceptable alternatives scores 2/2, not 1/2.

Section 1 defines evidence precision as "correct and relevant returned units
divided by all returned units". It does not define it as minimal units. A
second passage drawn from the reference's own acceptable list is by
construction both correct and relevant, because the reference author put it
there. Scoring it as a miss would penalize the system against a requirement the
reference never states, and would produce the perverse result that the more
thoroughly a record documents a criterion, the worse the system scores for
finding it. A reviewer checking whether low back pain is documented is helped,
not hindered, by seeing it at both encounters.

**Recall is unaffected.** Section 1 already settles it: returning any one listed
alternative counts as recovered. Extra acceptable alternatives neither raise nor
lower recall.

**Verbosity is measured separately, not folded into precision.** Two diagnostics
are reported alongside the primary metrics:

| Diagnostic | Definition |
|---|---|
| Mean returned spans per scorable instance | Citation volume, per configuration |
| Superset rate | Share of instances where accepted returned spans exceed `evidence_units_required` |

Precision must measure one thing. Folding citation volume into it would make any
movement uninterpretable, because a fall could mean the system became less
accurate or merely less talkative, and those call for opposite responses. If
Candidate B turns out to cite more per criterion than Baseline A, that shows up
here as a volume difference rather than as a phantom precision difference.

**Deduplication.** Section 1 requires repeated spans to be deduplicated
consistently. Two returned spans are the same unit when they resolve to
overlapping character ranges in the same `document_id`. Deduplicate before
computing either the numerator or the denominator. Spans in different documents
are distinct units even where the text is identical, because copy-forward makes
identical text common and the provenance differs: MRI-005 carries a
299-character block verbatim in two notes nine weeks apart, and which encounter
a fact came from is exactly what C2 turns on.

**A returned passage that is relevant but not enumerated.** The acceptable sets
are authored, and an author enumerates what they thought of. Where a returned
span is judged relevant on manual review but is absent from the reference:

- **Development split.** Adjudicate manually, record the decision in
  `evals/precision_adjudications.md` with the reasoning, and amend the reference
  as a versioned change to `corpus/labels.json` with the reason recorded. Rerun
  affected figures against the amended reference and report both.
- **Held-out and transfer.** Score it as a precision miss and list the case.
  **The reference is not amended.** Amending a locked reference after seeing
  model output is the contamination the lock exists to prevent, and an
  adjudication made while looking at what the system produced is not
  independent of it.

The asymmetry is deliberate and it is a known cost: held-out precision is
therefore a slight underestimate wherever the reference is less than exhaustive.
That is the correct direction for the error to run. Reporting a figure that is
too low for a stated reason is recoverable; reporting one inflated by amendments
made after seeing the output is not.

### Prerequisite: the acceptable sets do not exist yet

**No instance in `corpus/labels.json` currently enumerates its acceptable
passages.** Every instance carries `evidence_units_required`,
`evidence_requirement`, and a prose `evidence_note`, and none carries quotes or
spans. Section 1 assumes reference annotations that "define evaluable evidence
units"; the counts exist, the units do not.

Evidence recall and evidence precision are the primary comparison metric and
neither can be computed mechanically until this is closed. The rule above is
well defined and unimplementable as things stand.

**How this is resolved. Task 2.3b, before Task 2.4.** Recorded here as a
decision, not a plan, because the ordering is the part that carries the
integrity.

**1. Enumerate from the packet, never from model output.** For each scorable
instance, add `acceptable_evidence`: a list of *units*, where each unit is a
list of one or more equivalent quotes. Equivalence within a unit means either
quote recovers the same fact — the dog-walking goal restated in a discharge
summary is the same unit as its first statement, not a second one.

```
"acceptable_evidence": [
  {"unit": 1, "quotes": ["Date of Visit:  06/15/2026"], "role": "supporting"},
  {"unit": 2, "quotes": ["Date of Visit:  08/17/2026"], "role": "supporting"}
]
```

**2. The unit count is the authority; `evidence_units_required` must agree.**
`scripts/validate_labels.py` gains a check that the number of units equals
`evidence_units_required`, that every quote resolves via
`IngestedPacket.locate` to exactly one span, and that `NONE` instances carry an
empty list. A quote that resolves nowhere, or in two places, fails validation:
the reference may not cite what the system would be forbidden from citing.

**3. ALTERNATIVE and COMPOSITE are both expressed by the same structure.**
Under ALTERNATIVE with one required unit, list every acceptable alternative as
quotes *within* that single unit. Recall needs any one of them; precision
accepts all of them. That is what makes the superset rule above computable:
"is this returned span in the acceptable set" becomes a lookup rather than a
judgement.

**4. Enumerate for all three splits before any scoring run, and enumerate
held-out and transfer before any model call is made against them.** Reading a
packet to enumerate what it contains is authoring work on material already
written, and is permitted. Enumerating after seeing what a model returned on
that packet is not, because the enumeration would then be shaped by the output
it is meant to score. The split lock hashes are rebuilt afterwards with the
reason recorded, as they were on 2026-09-10 when `no_bypass` was added to
MRI-101 C3.

**5. Enumeration is adversarial to the label, not confirmatory.** For each
instance, the question asked is "what else in this packet would satisfy this
criterion", not "where is the passage I had in mind". TKA-004 C4 was marked as
requiring a semantic reading of a nutrition note while physical therapy — an
explicitly listed modality — sat in the packet with a documented outcome. No
check caught it; a live run did, when the model took the easier path and was
right to. Enumeration performed confirmatorily would have reproduced the error
into the acceptable set and then scored the correct answer as a precision miss.

---

### Contract rejections are reported apart from clinical errors

A result can fail because the model read the record wrongly, or because it read
the record correctly and returned a shape the output contract refuses. These
are different failures and pooling them misstates status performance in both
directions at once.

On TKA-004 C7 the model returned the reference status and the reference reason
code, then cited two passages alongside MISSING_EVIDENCE, and the result was
rejected. Scoring that as a status error would say the system misread the
record, which it did not. Scoring it as correct would ignore that the row could
not be shown to a reviewer.

`CriterionExtraction.failure_kind` carries the distinction at runtime:

| Value | Meaning |
|---|---|
| `CONTRACT_REJECTION` | The model answered; the output shape was refused |
| `NO_RESPONSE` | The call failed, or the response never parsed |
| `NOT_ATTEMPTED` | Ingestion failed; nothing was sent |

**Reporting rule.** Contract rejections are excluded from the status
performance denominator and reported as a separate rate, with the rejected
payload and the reason, per configuration. They are never counted as correct
abstentions. Where a rejected payload's clinical reading matches the reference,
that is recorded as a diagnostic and does not enter any score: the system did
not produce a usable result, and a comparison that credits it for nearly doing
so is measuring the wrong thing.

A rise in contract rejections is a prompt or contract problem, not a clinical
one, and it is actionable in a different way. Candidate B making more of them
than Baseline A would be a finding about call structure interacting with the
output format, which is precisely the kind of confound the paired design exists
to expose.

### Related invariants the harness may rely on

- `MISSING_EVIDENCE` in `reason_codes` and `evidence_units_required == 0` are
  equivalent, enforced in both directions.
- `CONFLICTING_EVIDENCE` always carries at least 2 units, because a contradiction
  cannot be represented by one side.
- `MET` and `NOT_MET` always carry an empty `reason_codes` list.
- Reference labels never contain `UNVERIFIABLE_QUOTE`,
  `UNSUPPORTED_CONCLUSION`, or `PROCESSING_ERROR`. Those are runtime outcomes and
  cannot be properties of a document set.

All of the above are checked by `scripts/validate_labels.py`.

---

## 3. Reporting requirements beyond Spec Section 9

Authored supplement. Section 1 already requires that results be reported by
procedure and scenario tag, that paired held-out results be shown, and that
criterion-level counts accompany case-level ones. The following three additions
record limits that are properties of this corpus rather than of the metric
definitions.

### Transfer tests procedure generalization only, not scenario generalization

The five fusion cases carry **no semantic-interpretation instance and no density
pair**. Buried evidence in the transfer split is positional: the criterion's own
vocabulary is present, and only its location is unexpected.

The transfer result therefore speaks to performance on an unfamiliar procedure
with a larger criteria set. It says nothing about semantic interpretation or
document-density robustness on unfamiliar material.

Report it in those terms. "Held up on transfer" without this qualification reads
as a broader generalization claim than the split supports.

### Held-out independence is 7, not 8

The held-out split has 8 cases but 7 independent observations, because TKA-103V
is derived from TKA-103 and differs only in verbosity. The criterion-instance
denominator is unaffected and remains exactly 48, so the adoption threshold in
Section 1 is unchanged.

What degrades is confidence in any case-level difference driven by that pair. A
difference appearing in both TKA-103 and TKA-103V is one finding observed twice,
not two findings. State the independent count alongside the raw count.

### When a returned span counts as citing a reference passage

**Recorded after the first development run, which this rule was missing from.**
That ordering is stated rather than hidden: the rule is written here now
because its absence caused a defect, and the absence is the lesson.

Section 2 above specifies deduplication by overlapping character ranges and
says nothing about **acceptance**. A scorer needs both. With no acceptance rule
written down, the first implementation compared a returned quote to a reference
quote by exact equality after canonicalization — not because that was chosen,
but because it is what you get when the question is never asked. It scored the
first development run at **23% recall against 87% status agreement**, and 97%
of quotes resolving in their document against 27% matching the reference.

The model was citing the right passages with different boundaries. Reference:
`No prior lumbar imaging on file for this patient.` Returned: `PRIOR IMAGING:
No prior lumbar imaging on file for this patient. No outside stud...`. The
reference span sits wholly inside the returned one and scored zero.

**The rule.** A returned span cites a reference passage when all three hold:

1. **Same document.** Compared by `document_id`, never by text. Copy-forward
   makes identical text common and provenance is what distinguishes the two
   encounters in MRI-005 C2.
2. **The spans overlap, and the overlap covers at least half of the shorter of
   the two.** A model quoting more widely than the reference, and a model
   quoting the key phrase inside it, are both citing the same passage. Half of
   the shorter span is the symmetric form of that, and it rejects a span that
   merely brushes the edge of the reference on its way somewhere else.
3. **The returned span is not more than four times the reference span's length,
   or 300 characters longer, whichever is more permissive.**

**Why the third condition exists.** Without it, a single span covering an
entire document overlaps every reference passage in that document and scores
perfect recall and perfect precision from one citation. The cap is a guard
against that degenerate case and **not a quality bar**, which is why it is
generous. Verbosity is measured, not penalised: mean returned spans per
instance, mean accepted span length, and the superset rate are all reported
alongside the primary metrics and none of them enters precision.

**Comparison is by position, not by string.** A reference quote is a locator
for a passage, not the wording a system must reproduce. Requiring reproduction
would measure how closely a model matches an author's choice of sentence
boundary, which is not a property anyone wants a UM system to have.

**What this does not license.** The acceptance rule was written after seeing a
result, which is the situation this document exists to prevent. Two things make
it defensible and both are checkable. It fixes a rule that was never recorded
rather than changing one that was, and no threshold in Section 1 moved. If a
future rule needs writing after results exist, it is recorded the same way,
with the ordering stated.

### A repeatability floor, measured before the comparison

**Recorded 2026-09-10, before the two runs it describes, and prompted by
observed variance rather than planned.** That ordering is stated because it
matters: this is a response to evidence, not a design decision made in advance,
and the distinction should not be lost later.

**What prompted it.** Two runs of the development split on the same day, under
adjacent prompt versions, differed by 8 points on evidence recall and 11 on
precision. Investigation showed total output tokens moved 0.98x, so the prompt
change was not generating more text. What did move was generation throughput:
MRI-007 produced 11,288 output tokens on one run and 6,893 on another from
identical input, and ran in 151, 238 and 27 seconds across three attempts.

Section 1 adopts Candidate B only if evidence recall improves by at least 10
percentage points. **If a configuration differs from itself by something near
10 points, that threshold cannot be read.** A difference between A and B would
be indistinguishable from A differing from A.

**The measurement.** Baseline A is run twice over the development split under
identical conditions — same prompt version, same criteria version, same model,
same settings, back to back. The difference between those two runs is reported
per metric and becomes the **repeatability floor**.

**How the floor is used.** Any A-versus-B difference smaller than the floor is
not a difference and is reported as one configuration being indistinguishable
from the other on that metric. The floor is reported alongside every
comparison figure, in the same way denominators are, so no reader sees a
difference without seeing what size of difference this corpus can resolve.

**What it does not do.** It does not change the adoption threshold. Section 1
fixes that at 10 points and it was written before any result existed; it is not
adjusted now that results are inconvenient. The floor changes what the
threshold can be **read against**, not what it is.

**If the floor exceeds 10 points on recall, say so plainly.** That outcome is
named here so it cannot be softened later: it would mean the pre-registered
threshold cannot be met by any real effect at this corpus size, and the honest
report is that **the comparison is underpowered**, not that Candidate B failed.
Reporting "B did not meet the threshold" when no effect could have met it would
be a false negative dressed as a finding.

**Two runs give a difference, not a variance.** Two observations bound nothing
and the floor is a single measurement of a quantity that itself varies. It is
better than the zero measurements available before, and it is not a confidence
interval. Reported as what it is.

### The measured floors, from Baseline A against itself

**Measured 2026-09-10 from two Baseline A runs over the development split
under identical conditions — `extraction/1.2.0`, `settings/2`, `parser/2`,
same model, same settings, run back to back. Recorded before Candidate B was
run even once.** That ordering is what makes this a measurement rather than an
adjustment.

| Metric | A1 | A2 | Floor |
|---|---|---|---|
| Evidence recall | 81 of 103 | 82 of 103 | **1.0 pp** |
| Evidence precision | 93 of 130 | 94 of 132 | **0.3 pp** |
| Status agreement | 73 of 85 | 74 of 84 | **2.2 pp** |
| Complete processing | 85 of 87 | 84 of 87 | **1.1 pp** |
| Citation validity | 128 of 130 | 132 of 132 | **1.5 pp** |
| **Critical errors** | **3** | **1** | **±2 instances** |

Output tokens differed by 0.7 percent and wall clock by 1.1 percent, so this is
a stable pair rather than a quiet one. The variance that dominated earlier runs
was extended thinking and is documented in `docs/DATA_CARD.md`.

**The recall floor is 1.0 point against a 10-point threshold.** The comparison
is not underpowered on the primary objective, and the outcome pre-registered
above as the one to state plainly did not occur.

### The critical-error floor, and how it is applied

**This is not a change to the threshold.** Section 1 says Candidate B is
adopted only if the incorrect mismatch count does not increase. That rule is
frozen, was written before any result existed, and does not move. What follows
is measured context for reading the number it produces.

**Baseline A produced 3 critical errors in one run and 1 in the other**, on
identical input:

| Run | Instances |
|---|---|
| A1 | MRI-004 C3, MRI-007 C3, TKA-001 C4 |
| A2 | MRI-007 C3 |

Only `MRI-007 C3` recurs. Two of three appeared in one run and not the other,
so the count moves by **±2 instances on a base of 1 to 3** — a small absolute
number moving by a large relative amount.

**How a result is reported.** An increase in critical errors that falls within
±2 of the comparison baseline is reported as *an increase that cannot be
distinguished from noise at this corpus size*, **naming every affected
instance**. It is not reported as Candidate B failing the criterion, and it is
not reported as passing it. The pre-registered rule is applied as written and
the interpretation states what the number can support.

An increase of 3 or more is outside the measured floor and is reported as an
increase, still with every instance named.

**Why this needs saying.** Taken literally and without context, a B run showing
3 critical errors against an A run showing 1 would block adoption — and
Baseline A already differs from itself by exactly that margin. Reporting that
as B failing would be a false negative produced by noise, which is the same
error as reporting a rate over six instances. This is the specific instance of
what Section 1 already says: zero observed failures in a small test is not
proof of safety, and by the same token a small observed difference is not proof
of harm.

### Candidate B's cost is not six times Baseline A's

Recorded 2026-09-10, **before Candidate B has been run even once**, from the
call structure alone. Section 1 says cost and latency limits are not binding at
prototype scale and that actual figures are recorded for both configurations.
This records the shape of those figures in advance, because it changes what the
adoption threshold is trading against and that trade should not be re-described
after the numbers arrive.

The obvious reading of the two configurations is that B costs what A costs
times the criterion count. **That is true of extraction and false of the run.**

| | Baseline A | Candidate B |
|---|---|---|
| Step 3 extraction calls, development | 15 | 89 |
| Step 3 packet tokens | 1× per case | ~6× per case, the packet resent per criterion |
| Step 5 support-verification calls | one per criterion carrying a verified claim | **the same** |

Step 5 receives a criterion, a proposed status and the verified evidence. It
does not receive the packet and it does not know how the claim was produced, so
its call count depends on **claims produced, not on how they were produced**.
Both configurations assess the same criteria over the same packets, so both
generate approximately the same number of claims and therefore the same Step 5
cost.

Two consequences for how the comparison is read:

**Wall clock.** Support verification is the larger share of a sequential run,
because it is roughly one call per scorable criterion against one or a handful
of extraction calls. B's extraction time rises about sixfold and its
verification time does not move, so end-to-end latency rises by closer to twice
than by six times. Reporting "B is six times slower" from the call count would
be wrong.

**Token cost.** This runs the other way. Extraction carries the packet and
verification does not, so input tokens are dominated by extraction and B does
resend the packet per criterion. B's token cost is close to the naive multiple
even though its wall clock is not. **The two operational measures move by
different factors, and quoting either alone misstates the trade.**

Report both, each with its counts, and state the mechanism. If B is adopted or
rejected partly on operating cost, the record must show which cost.

**This does not change the adoption threshold.** Section 1 fixes it on evidence
recall, with cost explicitly not binding at this scale. Recording the cost
shape early is so that it is not mistaken for a finding when it is arithmetic.

### Neither critical error direction is reportable as a rate

Recorded 2026-09-10, before any scored run exists. Section 1 requires both
critical error directions to be counted; **neither is reported as a rate, and
the harness does not print one.**

This section previously said the first direction could carry a rate over a
held-out denominator of 23. That is no longer true, and the reason is worth
recording rather than quietly editing: enforcing `not_met_bar` correctly during
Task 2.3b withdrew six NOT_MET labels that the bar forbade, taking the corpus
from 12 to 6.

| Direction | Corpus | Held-out | Reportable as |
|---|---|---|---|
| Reference MET or AMBIGUOUS output as NOT_MET | 177 at risk | 51 | **Counts, with every affected case named.** |
| Reference NOT_MET output as MET | 6 at risk | 2 | **Counts, with every affected case named.** |

**Why the first direction is counts and not a rate.** Its denominator is large,
so a rate is computable. It is not printed because the numerator will be near
zero and a near-zero rate over a large denominator reads as a safety claim. It
is not one: Section 1 already says zero observed failures in a small test is not
proof of safety, and a figure like "0.6%" invites exactly the reading that
sentence forbids. Counts with cases named cannot be misread that way.

**Why the second direction is not measurable at all.** Six instances corpus-wide
and two in held-out — `MRI-101 C5` and `TKA-104 C6`. Any rate over two
instances moves in 50-point steps. The direction is unmeasured rather than
underpowered, and the honest statement is that this corpus cannot detect a
regression in it.

`MRI-101 C5` is additionally the weakest surviving NOT_MET in the corpus: its
no-change claim rests substantially on patient report, and it survives because
completeness comes from the prior report being present rather than from that
statement. A denominator of two, one of which is marginal, is not a measurement.

**The bar was not relaxed to enlarge either denominator.** Adding NOT_MET
instances until a rate became computable would require weakening the standard
in Spec Section 4, which is the constraint the prototype exists to demonstrate.
The corpus lost half this class during Task 2.3b precisely because the standard
was applied rather than assumed, and the smaller denominator is the cost of
that. A class inflated by labels the rule forbids would measure worse than a
class too small to measure.

Do not describe zero observed failures in either direction as evidence of
safety. Section 1 already states that zero observed failures in a small test is
not proof of safety; this is the specific instance of that.
