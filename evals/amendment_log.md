# Reference amendment log

Every change to `corpus/labels.json` made during Task 2.3b enumeration: what was
wrong, how it was found, and what it would have done to a score.

The log exists because the count is itself a finding. If adversarial
enumeration of 183 instances yields on the order of fifty amendments, that says
something about reference data that a clean final artifact would hide entirely.
The distribution matters more than the total: a corpus whose defects are all
transcription slips is a different object from one whose defects are all
misreadings of its own criteria.

**Status: development complete, 15 of 15 cases. Held-out and transfer pending.**

Running totals are maintained in the two checkpoint sections below, which are
the authoritative summaries. Root causes are tracked separately from instance
counts, because twenty-one defects from six causes and twenty-one from
twenty-one causes say very different things about a reference.

| | |
|---|---|
| Defects to date | 21 |
| Distinct root causes | 6 |
| Accounted for by the two systematic causes | 17 |
| Found by re-reading the passage already in mind | 0 |

Defect rate by status, development split:

| Status | Instances | Defects | Rate |
|---|---|---|---|
| NOT_MET | 6 | 3 | 50% |
| MET | 44 | 10 | 23% |
| AMBIGUOUS | 40 | 0 | 0% |

**Defects concentrate where the label makes the strongest claim.** See the
15-case checkpoint for the argument.

---

## A-001 · TKA-004 C4 · analysis not propagated

**Was:** `interpretation: semantic`, described as requiring a nutrition consult
to be read as a weight-reduction modality.

**Wrong because:** physical therapy is an explicitly listed modality and is
documented with a discharge outcome, so the interpretation was never necessary.
`docs/DATA_CARD.md` had recorded this correctly since Task 1.3 and the label was
never updated to match. `validate_labels.py` went on counting three semantic
instances in development.

**Found by:** the first live extraction run on TKA-004, which returned MET
citing physical therapy and the injection. The reading was correct.

**Effect if unfixed:** the Spec §13 item 2 semantic demonstration would have
rested on an instance that does not require interpretation.

**Also:** `validate_labels.py` now requires every `semantic` instance to carry
`no_bypass` naming the other paths through its criterion and stating they were
ruled out. It fired immediately on MRI-005 C3 and MRI-101 C3, both since
verified and annotated.

---

## A-002 · TKA-004 C4 · designated evidence does not satisfy the criterion

**Was:** the correction in A-001 said the packet "supplies more than one valid
pair" and "which two is not fixed".

**Wrong because:** TKA C4 requires each modality to carry a *documented
outcome*. The nutrition consult records counselling and `Follow up in 6 weeks
with the food log`, and no outcome appears anywhere in the packet — no later
weight, no adherence report. It is not a qualifying modality. Physical therapy
plus injection is the only valid pair.

**Found by:** adversarial enumeration, checking each candidate modality against
the criterion's own wording rather than against the reference prose.

**Effect if unfixed:** a model citing the nutrition consult as one of its two
modalities would have been scored correct on a basis the criterion rejects.

**Note:** two wrong claims about one instance in a single day, both authored by
me, hours apart. The first said the interpretation was required; the second
said it was one of several options. It is neither.

---

## A-003 · MRI-001 C4 · unit undercount, 2 → 5

**Was:** `evidence_units_required: 2` — the review of systems, and the
neurologic examination.

**Wrong because:** the criterion lists five red-flag categories and
`addresses_rule` requires every one addressed and negative before a PRESENT
criterion resolves to NOT_MET. Two units cannot represent five categories.

**Found by:** adversarial enumeration, enumerating per category rather than per
passage.

**Effect if unfixed:** a model recovering one fifth of the requirement would
have scored one half. Recall on the highest-consequence status in the corpus,
inflated by 150%.

**Note:** one span covering the review-of-systems block recovers four units at
once, so efficient citation is not penalised. Units are facts; spans are
citations; the mapping is many-to-many.

---

## A-004 · MRI-005 C3 · acceptable set incomplete

**Was:** described as "a list entry rather than a narrative", implying one
acceptable passage.

**Wrong because:** the medication reconciliation note also records `Meloxicam
bottle empty, she reports finishing it as directed and says it made no
difference to the back.` Both record a completed meloxicam trial without
benefit; either recovers the fact.

**Found by:** adversarial enumeration.

**Effect if unfixed:** a model citing the narrative rather than the table row
would have scored a precision miss for a correct citation.

**Note:** both passages require knowing meloxicam is an NSAID, so the semantic
step and the `no_bypass` claim are intact.

---

## A-005 · TKA-006 C3 · completeness misrouted, and units 2 → 4

**Was:** `record_complete` justified as "Route A, twice over", treating the
regional health information exchange extract as a primary document.

**Wrong because:** the extract is not a primary document about this patient's
care. It is a search result. It was also not a clinician's assertion of
completeness, which `not_met_bar` forbids — so it fitted no existing route and
was forced into the nearest one.

**Fixed by:** adding **Route D, bounded systematic search** to `not_met_bar` in
criteria version **1.2.0**, rather than by re-describing the document. Route D
requires the search result *and* its stated limits both to be cited, which made
the limits paragraph required evidence and took units from 2 to 4.

**Found by:** adversarial enumeration; recorded in
`evals/acceptable_evidence_sample.md` as the one instance of ten that could not
be settled.

**Effect if unfixed:** the completeness rule would have carried an unexamined
reading, invisibly, on a NOT_MET instance.

---

## A-006 · LF-201 C1 · NOT_MET → AMBIGUOUS / INSUFFICIENT_CONTEXT

**Clinical status change, in a locked split.**

**Was:** NOT_MET, with completeness justified partly by `She has had no previous
spinal surgery of any kind.`

**Wrong because:** that is a categorical statement taken as history from the
patient at a single encounter, which `not_met_bar` has listed as insufficient
for completeness **since version 1.0.0**. The label violated a rule that
already existed. Nothing corroborates the line; neither imaging report mentions
instrumentation either way, and silence repairs nothing.

The other three limbs are sound — the flexion-extension series is in the packet
with measured translation and angulation against a stated departmental
threshold. The category *is* addressed, so this is not MISSING_EVIDENCE. It is
addressed without being settled, which is INSUFFICIENT_CONTEXT.

**Found by:** adversarial enumeration for the acceptable-evidence sample, where
it was the one instance of ten that could not be settled.

**Fixed by amending the label, not the rule.** Widening a route to rescue a
label would have inverted the exercise. Criteria **1.2.1** states the failure
mode explicitly — a clarification that restricts nothing, added because the
clause was missed and the reason it was missed is worth naming.

**Relock:** transfer and held-out relocked the same day, reason recorded in
`corpus/SPLIT_LOCK.json`. **No model run has touched transfer or held-out.**
The correction is only legitimate because it precedes any output on that split;
the same change made after seeing a model disagree would be indistinguishable
from fitting the reference to the result.

**Effect on the corpus:** NOT_MET falls from 12 to 11, transfer from 2 to 1.
AMBIGUOUS rises to 83, INSUFFICIENT_CONTEXT to 21. `distribution_at_authoring`
recomputed. The smallest status class got smaller, which is a real cost and the
right one to pay.

---

## The sweep: two more instances match, not amended

`not_met_bar` 1.2.1 was applied to all eleven remaining NOT_MET instances.
Reported rather than amended, per instruction.

**Clear (8).** MRI-006 C5 and MRI-101 C5 rest on a prior report present in the
packet plus a clinician's own interval comparison. TKA-003 C6 and TKA-104 C6 are
positive findings from the author's own assessment. TKA-103 C4, TKA-103V C4 and
LF-202 C4 rest on modalities offered at the author's own encounter with the
patient's response witnessed, and the earlier encounter is separately in the
packet. TKA-006 C3 is Route D.

**Matches the pattern (2).**

### S-001 · MRI-001 C4

Five categories. **Progressive neurologic deficit is solid** — a documented
neurologic examination, Route B. The other four rest on the structured review
of systems, which is patient report at a single encounter: `Trauma: No fall, no
motor vehicle collision...`, `Oncologic: No personal history of malignancy...`,
`Infectious: No recent infection...`, and the genitourinary and gastrointestinal
lines. Only the cauda equina category has an examination component, `Perianal
sensation intact.` Nothing in the referral letter or the therapy discharge
corroborates any of it.

### S-002 · MRI-007 C4

Same shape, in tabulated form. The red flag proforma's category 2 is explicitly
`on examination` and is corroborated by the consultation — solid. Categories 1,
3, 4 and 5 are entirely patient-reported negatives on a single-encounter
instrument, and the earlier GP note says nothing about any red flag.

### Why this is not a mechanical fix

Under 1.2.1 both should become AMBIGUOUS / INSUFFICIENT_CONTEXT, and that
removes two of the six development NOT_MET instances, taking the corpus to 9.

The two rules do not conflict, and the resolution is worth stating because it
looks like they might. `addresses_rule` decides MISSING_EVIDENCE against
INSUFFICIENT_CONTEXT against resolution: a targeted question asked and answered
**does address** the category. `not_met_bar` decides separately whether a
resolution to NOT_MET is permitted, and uncorroborated patient report is not.
A category can be addressed without completeness being established. That
combination is exactly INSUFFICIENT_CONTEXT.

**But the sweep exposed a prior question about Route C.** MRI-007 C1 passes only
because the same patient reported the same negative at two encounters — the GP
note and the spine clinic note. Route C as written asks for "two records, each
present in the packet in its own right and made on separate occasions", which
that satisfies. Whether it *should* depends on whether independence means
independent **occasions** or independent **sources**. Repeating a patient's own
report does not make it checkable.

If Route C requires source independence, MRI-007 C1 is caught as well, and the
obvious repair for MRI-001 C4 and MRI-007 C4 — add a second encounter asking
the same questions — does not work either. That would leave red-flag exclusion
achievable only through examination and records, which is defensible but is a
substantial narrowing.

**Not amended pending that decision.** Amending two labels under one reading of
Route C and then discovering the other reading is intended would mean amending
them twice.

---

## A-007 through A-011 · the Route C sweep · five NOT_MET labels withdrawn

Criteria **1.3.0** narrowed Route C: corroboration requires independent
**sources**, not merely separate **occasions**. Both readings were live in the
text and the corpus had labels resting on each. Applied to all eleven remaining
NOT_MET instances by reading the packets, not the labels.

| | Instance | Split | Why |
|---|---|---|---|
| A-007 | MRI-001 C4 | dev | 4 of 5 red flag categories on uncorroborated review of systems |
| A-008 | MRI-007 C1 | dev | same patient reporting no back pain at two encounters |
| A-009 | MRI-007 C4 | dev | 4 of 5 categories on a single-encounter screening proforma |
| A-010 | TKA-103 C4 | held-out | activity modification not attempted, on patient report alone |
| A-011 | TKA-103V C4 | held-out | follows its parent |

All five become **AMBIGUOUS / INSUFFICIENT_CONTEXT**. Each category is
*addressed* — so none is MISSING_EVIDENCE — and none is *established*.

**MRI-007 C1 is the instance that forced the decision.** Its justification read
"the same absence is recorded independently at the earlier encounter", which is
true of the occasion and false of the source.

### Survived, and why the distinction is not cosmetic

| Instance | Basis |
|---|---|
| MRI-006 C5, MRI-101 C5 | prior report present in the packet; completeness is Route A, a property of the document set rather than of anyone's history |
| TKA-003 C6, TKA-104 C6 | positive findings from the author's own assessment, one with a culture result |
| TKA-006 C3 | Route D |
| LF-202 C4 | physiotherapy offered and declined at two separate encounters, each witnessed by a different clinician |

**LF-202 C4 and TKA-103 C4 look like the same shape and are not.** Both turn on
a declined modality. In LF-202 two clinicians each *offered* physiotherapy and
each *witnessed* a refusal — two events, two observers, and either could have
gone differently. In TKA-103 the declined modalities survive for exactly that
reason, and the instance falls on activity modification, where nobody observed
anything and the patient is the only source.

**MRI-006 C5 and MRI-101 C5 have near-identical labels and different packets.**
MRI-006 records an examination. MRI-101 records vitals, "Comfortable. Moves
easily on and off the couch", and a clinician's statement that nothing has
changed, which "she confirmed as much when asked directly". MRI-101 C5 survives
because its completeness rests on the prior report being in the packet rather
than on that statement — but it is the weakest surviving NOT_MET in the corpus
and is recorded here as such. Reading the labels alone would have treated the
two as one case.

### Corpus effect

| | before | after |
|---|---|---|
| development NOT_MET | 6 | **3** |
| held-out NOT_MET | 4 | **2** |
| transfer NOT_MET | 2 | **1** |
| **corpus NOT_MET** | **12** | **6** |
| AMBIGUOUS | 82 | 88 |
| INSUFFICIENT_CONTEXT | 20 | 26 |

Development drops to three, not the four that was anticipated. **Half the
NOT_MET class in this corpus was labelled in violation of its own bar.**

Every amendment removes a label the rule forbids; none adds one. No packet
changed. All made before any model run touched held-out or transfer.

### Does source independence reach MET or AMBIGUOUS?

Checked, and no. Corroboration is a completeness concept and `not_met_bar`
governs completeness only. MET asserts that located evidence supports the
requirement, not that the record is complete: MRI-008 C2 is MET on a patient's
own statement of a two-year duration, and that is correct, because the
criterion asks whether a duration is documented and a documented report is
documentation.

Two non-NOT_MET labels use corroboration language and neither is affected.
TKA-104 C4 is worth noting for the opposite reason: it turns on a pharmacy
dispensing history whose own disclaimer records that counter sales are not
captured. That is Route D reasoning, reached before Route D existed, and it
lands where Route D says it should — the stated limits plausibly cover the fact
at issue, so the criterion is unresolved rather than excluded.

### Flagged, not resolved

**TKA-103 packet inconsistency.** The orthopedic note records `She has cut her
hours twice.` and, fourteen lines later, `Activity modification: not attempted`.
Cutting hours is not a documented modality trial with an outcome, so the
criterion reading holds, but the two statements sit badly together. A packet
defect rather than a completeness question, in a locked split, left for a
decision.

---

# Development enumeration

Fifteen cases, 87 scorable instances. Checkpoints at 5 cases and 15.

## Checkpoint: 5 cases (MRI-001 to MRI-005)

**23 scorable instances. 4 defects. 17%.**

Prior amendments already applied to these cases (A-003, A-004, A-007) are not
counted again.

### By status — the hypothesis does not survive

| Status | Instances | Defects | Rate |
|---|---|---|---|
| MET | 13 | **4** | **31%** |
| AMBIGUOUS | 10 | 0 | 0% |
| NOT_MET | 0 | — | — |

The closing observation from the previous session was that NOT_MET completeness
might be uniquely hard, with seven of eleven amendments concentrated there. At
five cases **that concentration looks like an artifact of where the sweeps
went.** MET has a defect class of its own, and in this sample it is the only
status with defects at all.

There is no NOT_MET left in these five cases to compare against: MRI-001 C4 was
the only one and it was withdrawn earlier today.

### D-001 · MRI-001 C3 · unit undercount 1 → 2 · MET

`lumbar_mri` C3 states that **both the attempt and the failed outcome are
required**. That is two facts. The reference counted one.

**High impact.** The two facts sit in different sections of the physical
therapy discharge summary: `Patient completed 8 physical therapy sessions.`
under COURSE, and `No meaningful improvement.` under OUTCOME. A model citing
the session count alone establishes the attempt and not the outcome, and would
have scored **1 of 1 for half the requirement**.

One passage does carry both — `Skilled therapy has not produced functional gain
and continued skilled intervention is not indicated at this time.` — and a
model citing it recovers both units in one span.

**Found by:** enumerating against the criterion's `satisfied_by` rather than
against the reference's prose.

### D-002 · MRI-002 C3 · unit undercount 1 → 2 · MET

Same root cause. **Low impact**: one sentence carries both facts, so a model
citing it now scores 2 of 2 exactly as it previously scored 1 of 1. The count
matters only for a model citing the bare statement that ibuprofen was taken.

### D-003 · MRI-005 C3 · unit undercount 1 → 2 · MET

Same root cause, same low impact. Both the medication reconciliation line and
the narrative note carry attempt and outcome together.

### D-004 · MRI-005 C1 · false claim in the reference · MET

**Was:** "Symptom documented **only** in the imaging order indication field, not
in any assessment or plan."

**Wrong because:** both office notes document low back pain in their subjective
sections. The true observation is narrower — it never reaches an assessment or
plan, because both assessments cover diabetes and obesity instead. The burial is
positional within the notes, not exclusivity to the order.

**Found by:** enumerating alternatives. The first live run had already cited the
two office notes for this criterion and was right to; the reference said the
passages it cited did not exist.

### One root cause, three instances

D-001 to D-003 are the same defect: **the reference counted the passage the
author had in mind, not the facts the criterion enumerates.** Only D-001 moves a
score, but the class is systematic and will recur wherever a criterion says
"both X and Y are required".

This has a corollary worth stating. Units are facts and spans are citations, so
a criterion demanding two facts has two units even where one sentence supplies
both. That costs nothing when the passage is unitary and is essential when it
is not.

### The 55 zero-unit instances

Ten fall in these five cases. **All ten verified, none defective.** Verifying
"nothing addresses this" is the same adversarial reading as enumeration and it
is the claim most easily made by not looking, so each was checked against every
document rather than against the note.

Two near-misses worth recording, both of which a term-matching check would
flag and neither of which addresses anything:

- **MRI-005 C4** (red flags, zero units). The June office note contains
  `fall when she is back from her sister's` — the season, not an injury.
- **MRI-002 C4**. `he does not connect it to any particular event` reads as a
  trauma negative. It is an attribution of cause, and under `addresses_rule`
  test 2 a patient not connecting pain to an event cannot exclude a fall.
  Likewise `He denies any change in the pattern recently` looks like it bears
  on progression, but the category is *progressive neurologic deficit* and no
  deficit is documented anywhere; test 1 fails on naming.

Also ruled out: **MRI-004 C5**, where the authorization coversheet says
`Please direct any request for additional records to the number above` — a
records reference that addresses nothing about prior imaging.

### Discovery method, cumulative

| Method | Count |
|---|---|
| Adversarial enumeration | 9 |
| Sweeping one rule across every instance it governs | 5 |
| Live model run producing a correct answer the reference called wrong | 1 |
| A checker written after the fact, firing immediately | 1 |
| **Re-reading the passage already in mind** | **0** |

Fifteen defects, still none from the confirmatory read. D-004 is the sharpest
case: the live run had already produced the evidence that the reference was
wrong, and it took an adversarial pass to notice.

---

## Checkpoint: 15 cases — development complete

**87 scorable instances. 10 defects found by enumeration. 11.5%.**

### By status — both predictions held

| Status | Instances | Defects | Rate |
|---|---|---|---|
| **NOT_MET** | 6 (before sweeps) | **3** | **50%** |
| **MET** | 44 | **10** | **23%** |
| **AMBIGUOUS** | 40 | **0** | **0%** |

The NOT_MET figure counts the three development instances withdrawn by the
`not_met_bar` sweeps earlier the same day, against the six that existed before
them. Those were found by sweeping a rule rather than by enumeration, and are
listed separately for that reason. Enumeration itself found ten, all in MET.

**Prediction 1 held.** The attempt-plus-outcome undercount recurred in
`total_knee_arthroplasty` C4, in all five satisfied instances in development
and one more in held-out. The root cause is systematic, not local to
`lumbar_mri`.

**Prediction 2 held.** AMBIGUOUS came back at exactly zero across forty
instances, including all twenty zero-unit instances.

### The result

**Defects concentrate where the label makes the strongest claim.**

- **NOT_MET** asserts the record affirmatively contradicts the criterion *and*
  is complete on the point. Two claims, the second about everything the record
  does not say. 50%.
- **MET** asserts located evidence establishes the requirement. One claim,
  about what is present. 23%.
- **AMBIGUOUS** asserts the question is not settled. It is the weakest claim
  available and the hardest to be wrong about. 0%.

NOT_MET was never special. It sits at the top of a gradient, and it looked
unique only because the sweeps that preceded enumeration followed
`not_met_bar`, which governs nothing else.

### Root causes against instances

Eleven defects from one misreading and eleven from eleven misreadings say
different things about a reference. Tracked separately from here.

| Root cause | Instances | Splits |
|---|---|---|
| **R1** · unit count reflects the passage the author had in mind, not the facts the criterion enumerates | **11** | dev 9, held-out 2 |
| **R2** · a positive claim about where evidence appears that the packet contradicts | 1 | dev 1 |
| **R3** · completeness established by evidence `not_met_bar` forbids | 6 | dev 3, held-out 2, transfer 1 |
| **R4** · analysis recorded in one document and never propagated to the data | 1 | dev 1 |
| **R5** · designated evidence fails the criterion's own test | 1 | dev 1 |
| **R6** · acceptable set denies a passage that exists | 1 | dev 1 |

**Twenty-one defects from six root causes, and two causes account for
seventeen.** That is the more reassuring shape: the reference is not unreliable
in twenty-one independent ways, it is unreliable in two systematic ways and
four one-off ways. A systematic cause can be swept mechanically once it is
named, which is what `scripts/check_unit_counts.py` now does for R1 and what
the `not_met_bar` sweep did for R3.

### R1 in full

`lumbar_mri` C3 — "Both the attempt and the failed outcome are required":
MRI-001 C3, MRI-002 C3, MRI-005 C3, MRI-006 C3, MRI-101 C3. Corrected 1 to 2.

`total_knee_arthroplasty` C4 — "each documented as actually attempted and each
with a documented outcome" across two modalities, which is four facts:
TKA-003 C4, TKA-004 C4, TKA-005 C4, TKA-005V C4, TKA-006 C4, TKA-102 C4.
Corrected 2 to 4.

Impact is uneven and worth separating, because only some of these move a score:

| Impact | Instances | Why |
|---|---|---|
| High | TKA-003 C4, TKA-006 C4, MRI-001 C3, TKA-004 C4 | facts in separate passages or documents, so partial recovery was scored as complete |
| Medium | MRI-006 C3 | adjacent sentences, the outcome naming no modality |
| Low | MRI-002 C3, MRI-005 C3, TKA-005 C4, TKA-005V C4, MRI-101 C3, TKA-102 C4 | one passage carries every fact, so recall is unchanged |

**TKA-006 C4 is the sharpest.** The prior authorization questionnaire puts
`Undertaken` and `Outcome` on separate lines for each modality. A model citing
only the Undertaken fields recovers half the requirement and would have scored
2 of 2.

### The 20 zero-unit instances in development

**All twenty verified against every document in their packet. None defective.**

Near-misses recorded, each a passage a term-matching check would flag and none
of which addresses its criterion:

- **TKA-002 C5**, functional limitation on physical examination. The radiology
  report header reads `EXAM: BILATERAL KNEES, WEIGHTBEARING AP AND LATERAL`.
  An imaging study is not a physical examination, and `No effusion` is a
  radiographic finding rather than a functional one.
- **MRI-005 C4**, red flags. `fall when she is back from her sister's` — the
  season.
- **MRI-002 C4**. `he does not connect it to any particular event` is an
  attribution of cause and cannot exclude a fall; `He denies any change in the
  pattern recently` looks like progression but no deficit is documented at all,
  so `addresses_rule` test 1 fails on naming.
- **MRI-004 C5**. The coversheet's `Please direct any request for additional
  records to the number above` is a records reference that addresses nothing
  about prior imaging.
- **TKA-005V C6 and C7**. The verbose variant's added clutter creates no
  appearance of infection or candidacy content, which is what the label
  required of it.

### The fifth checker to fail on first run

`scripts/check_unit_counts.py` was written to sweep R1 mechanically. Its first
run was wrong **in both directions**:

- **Seven false positives.** It flagged every instance of an explicit duration
  statement, because `lumbar_mri` C2 and `total_knee_arthroplasty` C3 offer two
  branches — one passage or two — and it matched the two-passage branch without
  noticing the one-passage branch beside it.
- **Six false negatives.** It missed every `total_knee_arthroplasty` C4
  instance, the largest group of the defect it was written for, because it
  scored "each attempted and each with an outcome" as two facts rather than two
  per modality.

Four of four Stage 1 checkers failed on first run. This is five of five. The
rule holds: no check is trusted until it has been shown to fail on a real
instance of the defect it targets, and shown to pass on things that are not.

### Discovery method, cumulative

| Method | Count |
|---|---|
| Adversarial enumeration | 10 |
| Sweeping one rule across every instance it governs | 5 |
| Mechanical sweep once a root cause was named | 4 |
| Live model run producing a correct answer the reference called wrong | 1 |
| A checker written after the fact, firing immediately | 1 |
| **Re-reading the passage already in mind** | **0** |

Twenty-one defects, still none from the confirmatory read.

---

## Held-out and transfer: enumeration complete

**96 scorable instances. 5 defects. 5.2%.**

### Against the prediction

The prediction was that held-out would land nearer 5% than development's 11.5%,
because the two systematic causes R1 and R3 had already been swept
mechanically, leaving only the one-off classes and zero-unit verification.

| Split | Instances | Defects | Rate |
|---|---|---|---|
| Development | 87 | 10 | 11.5% |
| Held-out | 53 | 2 | **3.8%** |
| Transfer | 43 | 3 | **7.0%** |
| Held-out + transfer | 96 | 5 | **5.2%** |

**The prediction held.** Held-out came in below the estimate and transfer
slightly above it, and the combined figure is 5.2% against a predicted ~5%.

The reason is mechanical rather than a difference in authoring quality, which
is what the prediction claimed: development was enumerated first and therefore
absorbed the discovery of both systematic causes, and by the time the other two
splits were reached those causes had already been swept.

### By status

| Status | Instances | Defects | Rate |
|---|---|---|---|
| **MET** | 45 | **4** | **8.9%** |
| **AMBIGUOUS** | 48 | **1** | **2.1%** |
| **NOT_MET** | 3 | 0 | 0% |

The gradient holds in the same order, at lower magnitude. **The single
AMBIGUOUS defect is the first in the corpus**, and it moves no number: LF-205
C2's prose claimed the packet contains two documents when it contains three.
The status, reason code and unit count were all correct.

That is worth stating precisely rather than folding into a rate. Across 128
AMBIGUOUS instances in the whole corpus, **zero carry a defect that would
change a score.** The one defect found is a false sentence in a note a human
reader would rely on, which matters for a different reason.

### D-011, D-012 · LF-201 C4 and LF-204 C4 · units 2 → 4 · MET

`lumbar_fusion` C4 requires physical therapy with an outcome **plus** one
further modality with an outcome. Four facts, the same shape as
`total_knee_arthroplasty` C4. Both instances carried two.

High impact in both: the four facts are spread across two documents, and in
LF-204 the closure note records an outcome against each element separately.

### D-013 · LF-205 C2 · false claim about the packet · AMBIGUOUS

**Was:** "The packet contains the imaging report and an administrative request
form only."

**Wrong because:** the packet holds three documents. The third is a records
transmittal, and it is the one that records the outside practice's notes as
requested twice and not received — the most consequential fact in the packet
about why nothing is citable.

No scoring field changed. Root cause R2, the same class as MRI-005 C1.

### The third failure of `check_unit_counts.py`

The script missed both LF C4 instances. Its second version had been fixed to
handle per-modality multiplication, but it did so by matching
`total_knee_arthroplasty` C4's **exact wording**. `lumbar_fusion` C4 says the
same thing differently — physical therapy "with an outcome", plus one more
modality "also documented as attempted with an outcome" — and was scored at a
floor of two.

Three failures, three distinct mistakes, all in one script:

| Version | Failure |
|---|---|
| v1 | Seven false positives on explicit-duration branches; six false negatives on TKA C4 |
| v2 | Fixed TKA C4 by matching its literal phrasing; missed LF C4 entirely |
| v3 | Matches the *requirement* — an outcome required per modality, times the modalities counted — rather than any wording |

Matching wording was the mistake both times. The lesson is narrower than "write
better checks": **a check keyed to how a rule is phrased will miss every
instance phrased differently**, and criteria sets are written by people who
vary their phrasing.

### Zero-unit instances

**Thirty verified across the two splits, fifteen each. None defective.**

The false positives thrown up by term-matching were the most instructive part:

- **LF-201 C9**, infection and osteoporosis. `Dexamethasone 8 mg` matched a
  search for `DEXA`. A steroid in an injectate, read as a bone density scan.
- **MRI-104 C4**, red flags. `Attendance number: 214` matched a search for
  `numb`.
- **MRI-101 C4**. `No numbness.` genuinely names a sensory symptom, and still
  does not address *progressive neurologic deficit*: one symptom at one
  timepoint fails `addresses_rule` test 3, which requires a passage to reach a
  compound category whole. `She was clear when I pressed her` refers to symptom
  stability, not to red flags.
- **LF-203 C9**. `Issued for a chest infection. Course finished, no further
  issue.` A resolved infection elsewhere, in a medication printout. It speaks
  to neither current status nor the operative site.

### LF-205 and the NOT HELD fields

The most interesting boundary in the two splits, and the reference is right.

LF-205's funding request form marks eight fields `NOT HELD` — neurological
examination, smoking status, psychological assessment, infection screening and
others — each naming a criterion category explicitly. A model reading the
packet will find them.

They do not address their criteria, and the form says so itself: *"fields
marked NOT HELD indicate the absence of a record at this clinic. They do not
indicate the absence of the underlying care, treatment, or finding."* Under
`addresses_rule` test 2 a passage must be capable of excluding the category,
and a statement about what a clinic holds cannot exclude anything about a
patient. MISSING_EVIDENCE with zero units is correct.

They are recorded as `ruled_out` rather than `also_acceptable`, and the
distinction matters. A model citing a NOT HELD line **alongside**
MISSING_EVIDENCE would be rejected by the output contract, which requires that
code to carry an empty evidence list. Extraction prompt 1.1.0 already directs
this correctly: a passage that does not address the requirement goes in the
explanation, not the evidence list. The reviewer still learns that the
information was sought and is unavailable, which is what MISSING_EVIDENCE
means here.

---

## Superseded

### O-001 · LF-201 C1 · completeness not established for one limb

Superseded by **A-006**, which amended it. Retained below as the original
finding.

The criterion names four qualifying diagnoses and NOT_MET requires all four
excluded. Three are: the flexion-extension series is in the packet with measured
values against a stated departmental threshold, which is Route A and sound.

The fourth, pseudarthrosis from prior fusion, is excluded only by one line in a
summary letter: `She has had no previous spinal surgery of any kind.` That is
history rather than observation, so `not_met_bar` requires Route C, and no
second record corroborates it. Neither imaging report mentions instrumentation
either way, and silence establishes nothing. **Route D does not apply**: the
letter declares no scope and no limits, and a search whose scope is not stated
is an assertion.

Under `not_met_bar` as written this should be **AMBIGUOUS with
INSUFFICIENT_CONTEXT**.

**Not amended.** Changing a clinical status in a locked split is not a change to
make silently, and the alternative repairs — adding a corroborating record to
the packet, or widening a route to rescue a label — are both worse. Flagged in
the label as `open_question`. No model run has touched transfer.
