# Claim-verification set: how it avoids being authored

Task 2.5. Written **before any bundle exists**, because the failure mode it
addresses is one this project has now hit six times and would hit again.

## The problem, stated plainly

Spec Section 8 asks for twelve to eighteen evidence bundles, separately
annotated, covering supported claims, real but irrelevant quotes, incorrect
dates, negation errors, incomplete evidence, and contradictions.

The obvious way to build that is to write bundles I believe are supported and
bundles I believe are unsupported, and check the verifier agrees. **That
constructs the inputs**, and it is the same defect as every checker failure
recorded in `docs/DATA_CARD.md`:

| Check | What it inherited from its author |
|---|---|
| Four Stage 1 checkers | A misreading of the corpus they were checking |
| `check_unit_counts.py` | An assumption about how a rule would be phrased |
| `um_evidence/score.py` | An assumption about the *shape* of a citation |

The scorer is the closest analogue and the most instructive. Its tests built
citations by reading quotes out of the reference and handing them back, so
they exercised the one input exact matching handled correctly. Ten tests
passed on a scorer that could not score.

A hand-written claim-verification set does the same thing. An unsupported
bundle I author is unsupported *in a way I thought of*, and the verifier's real
failures are the ways I did not.

**This component is the worst place for that.** Step 5 is the last check before
a result reaches a reviewer. A verifier that wrongly accepts an unsupported
claim produces a row that looks verified, cites real passages, and is wrong —
with nothing downstream to catch it. Its errors are the hardest in the pipeline
to detect from the output.

## The rule

**Every bundle originates from material this project did not author for the
purpose of testing the verifier.**

Four sources, in descending order of preference.

### 1. Real extraction output, including the errors it already made

The development run produced 114 citations across 87 instances under Baseline
A. Those are model outputs, not my constructions, and they already contain
failures I did not design:

- **A genuine paraphrase.** TKA-003 C3 returned `she has now had 18 months of
  failed conservative care.` where the letter says `...and has now had 18
  months...`. A true statement about the record presented as a quotation.
- **Two citations differing from the source by one letter's case.**
- **A contract rejection**, TKA-005V C7.
- **Four MET and six AMBIGUOUS instances that produced no answer**, mostly from
  output truncation.

Bundles built from these carry an annotation I did not choose, because the
model chose it and Step 4 already adjudicated it.

### 2. Real output recombined against the reference

Take a returned bundle and pair it with a *different* criterion from the same
packet. The quotes are real, the passages are real, the packet is real, and the
claim is unsupported — but the unsupportedness comes from the recombination
rather than from my writing an unsupported thing. This is the cheapest source
of "real but irrelevant quote" cases, and irrelevance is defined by the
criterion rather than by my judgement of it.

### 3. The reference's own `ruled_out` entries

Task 2.3b enumeration recorded, per instance, passages considered and rejected
**with the reason**. `Metal fragment or shrapnel history: No` excluded as
scanner safety rather than trauma. `Dexamethasone 8 mg` as not a bone density
scan. LF-205's `NOT HELD` fields as recording what a clinic holds rather than
what a patient has.

Each is a passage that is real, relevant-looking, and does not support the
criterion — with an adjudication written down before Step 5 existed and without
reference to what a verifier might do with it. These are the highest-quality
unsupported bundles available and they were not written to be bundles.

### 4. Authored, and only where the taxonomy demands it

Spec Section 8 names six categories. **Incorrect dates** and **negation
errors** may not occur in the run output at all, because they are failure modes
the extractor might simply not exhibit. Where a category cannot be sourced from
1 to 3, a bundle is authored — and marked `authored: true` in the set, so any
result can be reported split by origin.

If the verifier performs differently on authored bundles than on sourced ones,
that difference is itself the finding, and it is only visible because the
origin was recorded.

## Annotation, and who does it

**The annotation is written before the verifier sees the bundle**, and it
records the same three things the amendment log does: what the bundle contains,
what the correct verdict is, and *why* — with the reason traceable to a rule in
`criteria_sets.json` or `decision_rules.md` rather than to my impression.

Where a bundle's correct verdict is not clearly derivable from a written rule,
it does not go in the set. It goes in an open-questions list, as TKA-006 C3 did
during enumeration. A verifier test whose right answer is a matter of taste
measures taste.

## What this set is not

Spec Section 8 is explicit and it is repeated here because the two are easy to
conflate: **these bundles validate the support verifier. They are not the
criterion-status labels and cannot be substituted for them.** A verifier
scoring well here says nothing about evidence recall, and the sets must never
be pooled.

## The check on this document

The test of whether this worked is not that the verifier scores well. It is
whether the set contains at least one bundle whose correct verdict I got wrong
when I first looked at it. **If every bundle behaves as I expected, the set was
authored after all**, whatever its stated provenance, and that should be
reported rather than taken as success.

---

## What would count as the construction having worked

Written **before any bundle has been run**, and before the set is built.

The set has sixteen bundles from three origins. Six come from `ruled_out`
entries selected by a fixed rule — development split, corpus order, one per
case, first entry whose quote resolves to a single span. **I have no choice in
those six.** Ten come from real run output and from recombinations I chose.

The comparison between them is the check on whether the design worked, and the
outcomes are named here so they cannot be named afterwards.

| Outcome | Reading |
|---|---|
| The six perform **worse** than the ten | **Worked.** Material outside my selection is harder than material inside it, which is what the origin was chosen for. |
| The six perform **the same** | **Ambiguous, and reported as such.** It is consistent with the selection having added no bias, and equally consistent with the set being too small or too easy to separate them. Not reassuring. |
| The six perform **better** | **Failed, in one of two ways.** Either the selection rule found easy cases, or single-passage mismatches are intrinsically easier than real model errors regardless of who picked them. Those are different diagnoses and the entries themselves distinguish them. |
| **Both** perform badly | **The question is unanswerable.** A verifier near chance cannot discriminate between origins, and the finding is about the verifier rather than about the set. Report it that way and do not read the origin comparison at all. |

### Two additions to that framing

**The comparison must be within-verdict, or it is confounded.**

The origins do not have the same mix of correct answers. Every origin-3 bundle
is a real passage paired with a criterion it does not support, so its correct
verdict is UNSUPPORTED in all six. Origin 1 is mixed: supported claims drawn
from verified results, and errors drawn from real failures.

A verifier biased toward SUPPORTED would therefore score badly on origin 3 and
well on origin 1 **for reasons having nothing to do with difficulty**. The
headline comparison would show exactly the pattern that means "worked", caused
entirely by class balance.

So the comparison that decides it is: **among bundles whose correct verdict is
UNSUPPORTED, does the verifier do worse on origin 3 than on origins 1 and 2?**
The all-bundle figure is reported too, and where the two disagree the
within-verdict one governs.

**Six against ten does not support a rate, and none is printed.**

One bundle is 17 percentage points on origin 3 and 10 on the rest. Reported as
counts with every disagreement named, on the same reasoning as the critical
error directions in `decision_rules.md`: a rate over six items invites a
reading the sample cannot carry.

That means "worse" is not a threshold but a description. Two disagreements
against zero is a difference worth stating. Four against three is not, and
will be reported as no difference detected at this size.

### The prior admission

I do not expect the six to look dramatically harder, and I am recording that
now so it cannot be claimed afterwards either way. They are single-passage
mismatches with clean adjudications, and a verifier shown one passage and one
criterion may well find them straightforward. If that happens, the honest
conclusion is the third row of the table and not a rescue of the design.

The thing origin 3 protects against is narrower than difficulty: it protects
against a set whose every bundle was constructed with the verifier's behaviour
in view. That protection holds whatever the agreement rate turns out to be. The
comparison tests something else — whether my selection introduced ease — and it
can come back negative while the provenance argument still stands.

---

## The comparison narrowed, and why

Recorded 2026-09-10, **after the pre-registration above and before origin 1 was
built.** The comparison it describes is thinner than it was when written, and
the reason is on record here rather than discovered later.

The pre-registration assumed six unchosen bundles against ten chosen. Making
all seven origin-1 bundles SUPPORTED — required so a refuse-everything verifier
does not score 75% — leaves **six against three** in the within-verdict
comparison that governs.

**Origin 1 could in principle supply unsupported material.** The first scored
run produced four UNSUPPORTED and one INCONCLUSIVE Step 5 verdict, so it is not
structurally impossible, and an earlier draft of this note said it was.

**It cannot be annotated.** Two routes and both fail:

- *Take the verifier's verdict as the annotation.* Circular. It scores the
  verifier against itself and would mark every verifier error as correct.
- *Adjudicate independently.* That is my judgement, which is the thing origin 3
  exists to exclude. A bundle I decided was unsupported is unsupported in a way
  I thought of.

The candidates are also contested rather than clean. On MRI-001 C4 the verifier
returned UNSUPPORTED because "the cited passages actually address all five
red-flag categories with negative findings" — arguing for NOT_MET against a
completeness rule Step 5 structurally cannot see. That is a verifier error, and
annotating it as an unsupported bundle would write the error into the
reference.

**Six against three is what the material allows, not what was chosen.** The
comparison is weaker for it, and the pre-registered readings still apply, but
the resolution is lower than the table above implies. Three bundles cannot
distinguish much.

