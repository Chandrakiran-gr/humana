# Acceptable evidence sets: sample of ten

Task 2.3b, first ten instances. Drawn from development, weighted toward
COMPOSITE requirements, contradictions, and instances where the acceptable set
looked likely to be contested. Nine of the ten are COMPOSITE, four carry
CONFLICTING_EVIDENCE, three are NOT_MET.

Written to be checked before the remaining 173 are done.

Every quote below resolves to exactly one span via `IngestedPacket.locate`,
verified mechanically. A reference may not cite what the system would be
forbidden from citing.

---

## Schema

The sample required one change to the structure recorded in
`decision_rules.md`.

```jsonc
"acceptable_evidence": {
  "units": [                       // required for recall
    {"unit": 1, "role": "supporting",
     "quotes": ["...", "..."]}     // alternatives: either recovers the same fact
  ],
  "also_acceptable": ["..."],      // correct and relevant, not required
  "ruled_out": [{"quote": "...", "why": "..."}]
}
```

**Units are facts, spans are citations, and they are many-to-many.** A unit is
recovered when any returned span establishes it, and one span can establish
several units at once. MRI-001 C4 needs five categories addressed; a model
citing the review-of-systems block in a single quote recovers four of them in
one span. Recall is units recovered over units required. Efficient citation is
not penalised and incomplete citation is not excused.

**`also_acceptable` was added here and did not exist before.** Without it there
is no home for a passage that is plainly correct and relevant but is not itself
a required unit — the outcome half of a therapy episode cited alongside a
conflict about whether the therapy happened, for instance. Scoring such a span
as a precision miss would be wrong, and promoting it to a required unit would
inflate the recall denominator. It needed a third category.

**`ruled_out` is part of the artifact, not working notes.** An acceptable set
that records only what was included cannot be audited for whether anything was
considered. The entries below are the substance of the exercise.

---

## The ten

### 1. MRI-001 C4 — NOT_MET, red flags — **reference undercounts units**

Five listed categories, and `not_met_bar` with `addresses_rule` requires every
one of them addressed and negative. The reference records **2 units**: the
review of systems, and the neurologic examination. Two units cannot represent
"all five categories addressed" — a model citing only the trauma line would
score 1/2 for recovering one fifth of what NOT_MET actually requires.

**Enumerated: 5 units**, one per category.

| Unit | Category | Quotes |
|---|---|---|
| 1 | cauda equina | `Genitourinary: No urinary retention, no incontinence, no difficulty initiating the stream.` / `Gastrointestinal: No bowel incontinence, no constipation, no perianal or saddle numbness.` / `Perianal sensation intact.` |
| 2 | progressive neurologic deficit | `Motor: 5/5 bilaterally throughout.` / `Sensory: Intact to light touch and pinprick in all lumbosacral dermatomes bilaterally, including L4, L5, and S1.` / `Reflexes: Patellar 2+ and symmetric. Achilles 2+ and symmetric. No clonus.` |
| 3 | malignancy | `Oncologic: No personal history of malignancy. No prior chemotherapy or radiation.` |
| 4 | spinal infection | `Infectious: No recent infection, no intravenous drug use, no indwelling lines, no recent invasive procedure, no immunosuppression.` |
| 5 | significant trauma | `Trauma: No fall, no motor vehicle collision, no lifting injury, no other significant trauma at any point preceding or during this episode.` |

**also_acceptable:** the gait line, the inspection line, the constitutional ROS
line. Each bears on a category without being able to settle it alone.

**Ruled out:**

- `Metal fragment or shrapnel history: No`, from the MRI safety screening.
  Superficially the strongest trauma-adjacent string in the packet and the one
  a keyword approach would reach for. It asks about embedded metal for scanner
  safety, not about injury to the spine. Different question, and a "no" here
  excludes nothing about trauma.
- `Vitals: BP 124/76, HR 68, T 36.8 C, BMI 24.9.` A single afebrile reading
  cannot exclude spinal infection; discitis is frequently afebrile. Fails
  `addresses_rule` test 2 — consistent with absence, not capable of excluding.
- `General: Comfortable, ambulates without aid, no distress.` A routine
  observation recorded because observations are always recorded. Test 2 again.
- PT discharge `Right lower extremity symptoms unchanged in distribution and
  frequency.` Considered for unit 2 on the grounds that "unchanged" speaks to
  trajectory. Ruled out: it reports symptom stability, not the absence of a
  deficit, and the neurologic examination reaches the whole category anyway
  through the base-condition exception.
- Referral letter `Her other issues are stable and should not complicate
  matters.` Addresses nothing on the list.

**Amendment: `evidence_units_required` 2 → 5.**

---

### 2. MRI-004 C2 — AMBIGUOUS / CONFLICTING — **resolves cleanly, superset confirmed**

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Ms. Delacroix returns with an 8-week history of low back pain.` |
| 2 | contradicting | `Started bothering me about 3 weeks ago.` / `[X] 1 to 4 weeks` |

The live run returned three spans against a 2-unit reference. Both intake
passages assert the same fact from the same source on the same form, so they
are **alternatives within unit 2, not a third unit**. All three spans are
accepted; recall is 2/2. This is the superset rule working as intended.

**Ruled out:** nothing else in the packet states a duration. Checked every
document for week/month/onset language; the physiotherapy note and the
authorization coversheet carry dates but assert no symptom duration.

---

### 3. MRI-004 C3 — AMBIGUOUS / CONFLICTING — **`also_acceptable` earns its place**

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `6 sessions completed to date.` |
| 2 | contradicting | `She has not yet started physical therapy and is going to look into scheduling once her rota settles down.` |

**also_acceptable:** `Pain report is essentially where it started.`

The live run cited that outcome line as a third span. The criterion requires
both an attempt and a failed outcome, so it is unambiguously relevant. But the
claim being made is CONFLICTING_EVIDENCE, and what conflicts is *whether the
therapy happened at all* — the outcome is not needed to establish that. Making
it a required unit would raise the recall denominator for a fact the status
does not rest on. This is the case that forced the third category.

---

### 4. MRI-005 C2 — MET, derived

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Date of Visit:  06/15/2026` |
| 2 | supporting | `Date of Visit:  08/17/2026` |

**also_acceptable:** `Same right low back pain across the belt line that she
brought up at her last visit.`

**Ruled out:** the June note's own back-pain paragraph, and its verbatim
copy-forward in the August note. Both document the symptom, but the derivation
runs on the **header dates**; a model citing only the two symptom paragraphs
has not recovered the span. Note the copy-forward block appears in both
documents, so a citation of it must carry a document id to mean anything —
which is why the packet-level lookup returns both occurrences rather than one.

---

### 5. MRI-005 C3 — MET, semantic — **two alternatives, one interpretation**

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Meloxicam 15 mg              oral   daily               trial completed, no relief` / `Meloxicam bottle empty, she reports finishing it as directed and says it made no difference to the back.` |

The narrative note was initially assigned to `also_acceptable` and then moved
into the unit. Both passages record the same fact — a completed meloxicam trial
without benefit — so either recovers it. Both also require knowing meloxicam is
an NSAID, so the semantic step is intact on either path and the `no_bypass`
claim added on 2026-09-10 still holds. The instance has two acceptable
passages, not one; the reference's prose said "a list entry rather than a
narrative", which is true of the passage it had in mind and not of the packet.

**Ruled out:** `Cyclobenzaprine 5 mg ... not started, patient declined`. A
muscle relaxant is not among the three listed modalities, and it was declined
rather than attempted. Two reasons, either sufficient.

---

### 6. TKA-001 C3 — AMBIGUOUS / INSUFFICIENT_CONTEXT

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Start of care:      04/06/2026` / `Date of discharge:  05/18/2026` |
| 2 | contradicting | `None. No conservative treatment was undertaken prior to this referral.` |

Unit 1 groups the two dates as alternatives because the fact being recovered is
*the documented course and its extent*, and either header locates it. Grouping
them is arguable — see the note under TKA-006 C3 on the same question, which is
where it becomes load-bearing.

**Ruled out:** the preoperative clearance note's `Naproxen to be withheld from
seven days before any surgical date.` A medication-hold instruction is not
documentation of a conservative trial.

---

### 7. TKA-001 C4 — AMBIGUOUS / INSUFFICIENT_CONTEXT

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Start of care:      04/06/2026` |
| 2 | contradicting | `Naproxen 500 mg              oral    twice daily prn` |

**also_acceptable:** `Unable to give start dates for any of the above.`

The second unit is unusual: the medication entry is cited *because it fails* to
establish a second modality. The criterion needs two modalities each with a
documented outcome, and a prn line with no trial period and no result does not
supply one. A reviewer cannot see why the count falls short without seeing the
entry that does not count.

---

### 8. TKA-003 C3 — AMBIGUOUS / CONFLICTING

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `has now had 18 months of failed conservative care.` |
| 2 | contradicting | `with me on 14 July of this year.` |

**Ruled out:** `That was the first occasion the knee appears in` — the
continuation of the same sentence, which is the more explicit statement of the
contradiction. Excluded as a separate unit because it is the same clause; kept
as an alternative on unit 2 in the final set. Also ruled out: the injection
procedure note of 2026-08-06, which documents a modality but says nothing about
the duration of the course, and so bears on C4 rather than C3.

---

### 9. TKA-004 C4 — MET — **the reference evidence does not satisfy the criterion**

The criterion needs two modalities, **each with a documented outcome**. The
packet contains three candidate modalities and only two qualify.

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Pt made measurable gains in strength and modest gains in range of motion.` / `He has plateaued across the last several visits with no further objective gain recorded.` |
| 2 | supporting | `PROCEDURE: Intra-articular injection, right knee.` / `Patient reported diminished pain within ten minutes, consistent with the local anesthetic rather` |

**Ruled out — and this is a correction to an edit made earlier the same day:**
the nutrition consult. `Counselled on caloric restriction to a target of 1,800
kcal daily` records an intervention and a plan, with `Follow up in 6 weeks with
the food log`. **No outcome is documented anywhere in the packet** — no later
weight, no adherence report, nothing. Under the criterion's own wording it is
not a qualifying modality.

Earlier today this instance was rewritten to say the packet "supplies more than
one valid pair" and that "which two is not fixed". That is false. There is
exactly one valid pair, and the pair is forced. The rewrite was made while
downgrading the instance from `semantic`, and it substituted one wrong claim
for another: first that the nutrition reading was required, then that it was
one of several options. It is neither — it does not satisfy the criterion at
all.

**Amendment: `evidence_note` corrected.** The live run's answer, physical
therapy plus injection, was not merely *a* valid pair. It was the only one.

---

### 10. TKA-006 C3 — NOT_MET — **not settled**

This one does not resolve, and the reason is structural rather than a matter of
reading more carefully.

The dated span is 05/18/2026 to 07/06/2026, seven weeks against a three-month
threshold. NOT_MET requires the contradiction, a complete record, and no
exception. The contradiction is straightforward. Completeness is not.

The questionnaire answers `NONE` to conservative management received elsewhere,
and sources that answer to the attached health information exchange extract.
The extract states that no musculoskeletal encounter exists before 05/18/2026
across ninety-one participating organisations — and states its own limits:
care outside the region, non-participating providers, and up to seventy-two
hours of upload latency.

Provisional units:

| Unit | Role | Quotes |
|---|---|---|
| 1 | supporting | `Date conservative management commenced ... 05/18/2026` |
| 2 | supporting | `Date conservative management concluded ... 07/06/2026` |

with the HIE line in `also_acceptable`. **I do not think that is right, and I
cannot settle it.** Four questions have to be answered together:

1. **Are the two dates one unit or two?** They are a start and an end, which
   `decision_rules.md` cites as the paradigm case of a COMPOSITE pair. But they
   sit on adjacent lines of one form and a single span could cover both. Two
   units means a model quoting the block once still scores 2/2, which is
   correct — so this is probably fine, but it makes the count cosmetic.

2. **Is `elsewhere: NONE` a required unit?** The reference implies yes. The
   seven-week span alone does not establish NOT_MET, because a course elsewhere
   would change the answer. So completeness is load-bearing and the field that
   asserts it should be required, not merely acceptable.

3. **Must the HIE extract itself be cited?** `not_met_bar` forbids
   establishing completeness by a clinician's assertion that the record is
   complete. `elsewhere: NONE` on a form the practice filled in is exactly such
   an assertion *unless* the extract behind it is in the packet — which it is.
   That argues the extract is required. But then:

4. **Must the extract's stated limits be cited?** A reviewer told "no care
   elsewhere" without being told the claim excludes out-of-region and
   non-participating providers has been given an unqualified version of a
   qualified fact. If the limits paragraph is required evidence, then the
   correct answer may not be NOT_MET at all, because the record is complete
   only within a boundary the record itself declares.

That last question is not about enumeration. **It asks whether TKA-006 C3's
label is right**, and answering it means re-reading `not_met_bar` against a
completeness claim that is explicitly bounded — a case the rule does not
currently address. Route A is the primary document, Route B is first-hand
observation, Route C is independent corroboration. A regional exchange extract
with declared coverage gaps is a fourth thing.

**Left unenumerated pending a decision on `not_met_bar`.** Guessing here would
bake an unexamined reading of the completeness rule into the scoring data,
where it would be invisible and would silently determine whether the system is
scored right or wrong on the highest-consequence status in the corpus.

---

## What the sample found

| | |
|---|---|
| Instances enumerated | 9 of 10 |
| Left unsettled | 1 (TKA-006 C3) |
| Quotes validated | 37/37 resolve to exactly one span |
| **Reference defects found** | **3 of 10** |

The defects:

- **MRI-001 C4** — units undercounted 2 against 5. Would have scored a model
  recovering one fifth of a five-category requirement as recovering half.
- **TKA-004 C4** — designated evidence does not satisfy the criterion. Would
  have scored the only correct answer as a precision miss.
- **MRI-005 C3** — a second acceptable passage the prose denied existed.

None of these is a typo. Each is a reading of the packet that was wrong in a
way that would have moved a number, and each was found by asking "what else
would satisfy this" rather than "where is the passage I meant".

**Enumeration is an audit of the reference, not a transcription of it.** At
three defects in ten, the remaining 173 instances should be expected to yield
on the order of fifty amendments. That figure is the argument for doing this
before the harness exists rather than after: every one of these would have
surfaced as an unexplained model error, and the natural response to an
unexplained model error is to adjust the model.
