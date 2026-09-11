# Prototype Specification, Revision 3

Clinical evidence mapping for utilization management review.

Incorporates first-review items R1 through R8 and second-review edits. Scope frozen.

---

## 1. What the system does

**Input:** a set of clinical documents submitted with a prior authorization request, and the procedure code for the requested service.

**Output:** an evidence map. One row per medical necessity requirement, showing the requirement, a clinical result, a processing state, the passages from the record relevant to that requirement, and a link to each passage in its source document.

**User:** a utilization management reviewer.

The system produces no coverage determination, recommendation, or aggregate score. The reviewer inspects the evidence and continues the organization's established review or escalation workflow.

---

## 2. Demonstration scope

All criteria are **synthetic demonstration criteria**, not Humana coverage policies. All clinical records are synthetic. No real or de-identified patient data is used.

The interface must state this on screen. Listed procedure codes identify supported demonstration scenarios, not validated production applicability.

Each criteria set carries an identifier and a version. The version in effect is recorded in every run.

---

## 3. Output contract

Each requirement produces one result object.

| Field | Meaning |
|---|---|
| `criterion_id` | Stable identifier from the selected criteria set version |
| `clinical_status` | MET, NOT_MET, AMBIGUOUS, or NOT_APPLICABLE. Null when no valid clinical result was produced. |
| `processing_status` | COMPLETE, PARTIAL, or FAILED. Never inferred from `clinical_status`. |
| `evidence[]` | Zero or more spans. Each carries document id, document hash, canonical source span, exact quote, and role (supporting or contradicting). |
| `reason_codes[]` | Zero or more. Empty for a clean MET or NOT_MET result. Values: MISSING_EVIDENCE, CONFLICTING_EVIDENCE, VAGUE_DURATION, UNVERIFIABLE_QUOTE, UNSUPPORTED_CONCLUSION, INSUFFICIENT_CONTEXT, PROCESSING_ERROR |
| `explanation` | Brief justification grounded in the cited evidence, including unresolved conditions |
| `verification` | Quote-check and support-check outcomes, including inconclusive checks |

**Clinical status and processing status are independent.** A parsing failure or model timeout is a processing failure, not a clinical finding. A system failure must never appear as a clinical determination.

**"Unresolved" means `clinical_status: AMBIGUOUS` where analysis completed.** `clinical_status: null` is used only where processing produced no valid clinical result at all. The two are not interchangeable.

**Evidence is a list, not a single quote.** A duration calculation may require a start and end date in separate passages. A contradiction requires both sides. A single quote field cannot represent these.

**Model confidence is not displayed.** It may be retained as an internal experimental field. It is not a calibrated probability and must not be presented as one. Source evidence and explicit reason codes are sufficient for the interface.

Rejected raw results are preserved in the run log.

### Required handling by situation

| Situation | Behavior |
|---|---|
| Packet processed, facts absent | AMBIGUOUS with MISSING_EVIDENCE |
| Relevant notes conflict | AMBIGUOUS with CONFLICTING_EVIDENCE, both passages shown |
| Document unreadable or model call fails | Processing incomplete. The case is not presented as a completed evidence review. |
| Returned quote does not verify | Reject that span, preserve the reason, retain any independently valid spans. If the conclusion loses its support, downgrade to unresolved. |
| No valid criteria match, or unsupported input | Stop with an explicit unsupported-case message. Do not guess. |

---

## 4. Status definitions

| Internal label | Display wording | Meaning |
|---|---|---|
| MET | Supporting evidence identified | Submitted evidence supports the synthetic requirement. Reviewer verification remains necessary. |
| NOT_MET | Potential mismatch requiring review | Affirmative evidence conflicts with the requirement, after relevant context and applicable exceptions are considered. |
| AMBIGUOUS | Insufficient or conflicting evidence | Unresolved. The reason code must be visible. |
| NOT_APPLICABLE | Not required, waived by exception | The criterion is waived by an exception pathway whose trigger is MET, and is out of scope for this request. Not failed and not unresolved: it was not asked. |

**A waived criterion is NOT_APPLICABLE, never NOT_MET.** Where an exception pathway is triggered, the criteria it waives are out of scope for the request. They carry no reason code and no required evidence, and they are excluded from evidence recall, evidence precision, and status performance denominators. What the documents would have supported absent the waiver is recorded for diagnostics and is not scored. NOT_APPLICABLE and null are not interchangeable: NOT_APPLICABLE is a clinical result, null is the absence of one.

**NOT_MET carries a high bar.** Eight documented weeks against a twelve-week threshold does not automatically establish NOT_MET. The reference label must establish that the evidence is current and relevant, that other notes and applicable exceptions were accounted for, and why the evidence is affirmatively contradictory. Otherwise the correct label is AMBIGUOUS.

Missing evidence is never automatically NOT_MET.

---

## 5. Pipeline

### Step 1: Load criteria
Deterministic lookup by procedure code. Returns a versioned criteria set.

Criteria explicitly represent exceptions, alternative evidence paths, time windows, and AND/OR logic used in the synthetic cases.

No automated policy extraction. No real policy applicability resolution.

### Step 2: Ingest documents
Parse each document. Assign a stable document identifier, record a content hash, and track canonical span positions.

Supported: text files and text-based PDFs. Scanned or empty documents are detected and reported explicitly. OCR is out of scope.

Token count is computed before any model call. If input exceeds limits, return an explicit input-limit result. Never truncate silently.

Documents are kept structurally separate from model instructions.

### Step 3: Evidence extraction, two configurations

Both configurations use the same model version, the same inputs, the same output contract, and the same downstream verification.

**Baseline A.** One extraction call receives the complete packet and all criteria, returning one structured result per criterion.

**Candidate B.** One extraction call per criterion, each receiving the complete packet and one criterion.

Per-criterion calls are a **testable hypothesis**, not an established improvement. Both configurations permit per-criterion scoring. No claim is made that separate calls guarantee independent errors or improved attention.

Full context is the starting approach for these packet sizes. The evaluation measures quality, evidence position effects, and repeated-context cost rather than treating context-window fit as settling the question.

Output is schema-validated. Malformed responses fail explicitly.

Raw extraction output is retained separately from final verified output.

### Step 4: Quote verification
Each returned quote is checked against a stable canonical representation of the identified source document.

A match confirms the text exists in the extracted source. **A mismatch means the quote is unverifiable.** It does not by itself establish fabrication. Differences can arise from text extraction, whitespace, line wrapping, or normalization.

Where normalization is applied, a mapping back to the original source is retained. Clinical wording and numbers are never silently altered. Repeated quotes are disambiguated by document identity and span.

Raw quote validity and rejected-evidence rate are both reported.

### Step 5: Support verification
The verifier receives the exact criterion, applicable exceptions, the proposed status, all relevant evidence spans, and necessary surrounding context.

Returns SUPPORTED, UNSUPPORTED, or INSUFFICIENT_CONTEXT with a short justification.

This tests whether the supplied evidence supports the conclusion. **It does not establish that the complete packet contains no contradictory evidence.** Contradiction detection remains the responsibility of full-packet extraction.

**A SUPPORTED verdict is not a safety guarantee, and cannot be read as one.** The verifier is shown the criterion, the proposed status, and the cited evidence. It is not shown the record. Two consequences follow from that design and neither is a defect:

- **It cannot detect a completeness failure.** NOT_MET requires the record to be complete on the point, established by one of the routes in `not_met_bar`. Completeness is a property of the whole record, so a NOT_MET resting on evidence that is genuinely insufficient under the bar — an uncorroborated patient-reported negative, a search whose stated limits cover the fact — will be returned SUPPORTED, correctly, because the cited passages do support the claim as stated. Observed: in the first scored development run, all three critical errors returned SUPPORTED.
- **It cannot detect evidence that was never cited.** A conclusion drawn from two passages while a third contradicts them is supported on what it was shown.

Both limits are the price of withholding the packet, which is what stops the verifier re-deriving the answer and agreeing with itself. Withholding it is the point of the step. The limits are recorded here so that a reader of a SUPPORTED verdict knows what it certifies: that the cited evidence bears the stated weight, and nothing about the rest of the record.

Where verification is unsupported or inconclusive, the original status does not survive unchanged. The original result is recorded and the final output becomes unresolved unless other validated evidence is sufficient.

Support calls are skipped for missing-evidence outputs that make no affirmative evidentiary claim. Absence cannot be proven from an empty quote.

### Step 6: Assemble
Build the evidence map. Processing state and clinical result are both visible. AMBIGUOUS renders distinctly from NOT_MET, with its reason code shown.

No approve control, no deny control, no aggregate score.

---

## 6. Data and splits

Splits are assigned **before any tuning**.

| Split | Size | Criterion instances | Scorable | Permitted use |
|---|---|---|---|---|
| Development | 15 MRI and knee cases | 89 | 87 | Inspect failures, edit prompts, choose the candidate |
| Held-out test | 9 MRI and knee cases | 55 | 53 | After freezing the candidate, compare against frozen baseline |
| Transfer challenge | 5 fusion cases | 45 | 44 | Exploratory performance on a procedure unused during development |

Scorable excludes criterion instances resolving to NOT_APPLICABLE, which are waived by an exception pathway and are out of scope for the request. Metrics divide by the scorable count.

This allocation is a practical starting point. It is too small to establish clinical validity or broad generalization. The number of cases and criterion instances behind every result is reported.

### Why the allocation changed

The original allocation was 12 development, 8 held-out, 5 transfer, and held-out was exactly 48 criterion instances. Four cases were added on 2026-09-09, taking development to 15 and held-out to 9.

The reason was measurement rather than scenario coverage. A per-criterion audit found that six of twelve requirements had a majority-class baseline at or above 70 percent, meaning a system could score well on them by answering the same thing every time without reading, and that `lumbar_mri` C1 was satisfied in every single case and therefore measured nothing. Four statuses occurred in exactly one case each, which made every unique feature of that case a perfect predictor of that status. Cases were added to lower those baselines and to give each singleton status a second instance by a different mechanism.

The 12/8/5 figures were a starting allocation, not a property worth preserving at the cost of the experiment's power.

**Section 9's adoption threshold is stated over "approximately 48 criterion instances across 8 cases" and has deliberately not been edited.** Those numbers were frozen before any run precisely so they could not be adjusted once results were in view, and rewriting them now would defeat that, even in a direction that looks harmless. The threshold itself is unaffected: the split grew rather than shrank, so a 10 percentage point margin over 53 scorable instances is if anything a slightly more conservative bar than over 46. `evals/decision_rules.md` carries the current denominator alongside the frozen text and instructs that 53 be reported.

**Reference labels are written before records are drafted**, then the completed records are manually checked against them. A label describes what the submitted documents support under the synthetic criterion. Contradictory or incomplete references are resolved before the test split is locked.

**All copies, ablations, and paraphrases derived from a case remain in its parent split.**

After deleting evidence for an ablation, verify that no equivalent evidence survives elsewhere in the packet. Ablation labels are not automatically correct.

Silver-set scores are reported separately. Related variants derived from one case do not constitute independent cases. Large silver expansion is optional.

### Dataset manifest
Records case id, parent case id, procedure, split, scenario tags, and reference version.

### Scenario coverage
Evidence in an unrelated section. Duration described without dates. Contradictory statements across documents. Near-threshold documentation. Requirements never addressed. Concise and verbose versions of the same facts. Cases where facts are genuinely absent.

Document-density testing compares concise and verbose versions containing the same facts, plus separate cases where facts are missing. **This is robustness testing with equity implications. It is not evidence of demographic fairness.**

---

## 7. Experiment design

1. Assign splits, write and check reference labels, lock the test split
2. Record acceptance conditions and decision rules, with actual numeric limits, before running
3. Build A and B sharing an identical prompt. The only difference is call structure.
4. Run both on development
5. Inspect development failures and identify one targeted change
6. **Apply that change to both A and B.** Re-run both on development.
7. Freeze both configurations
8. Run both frozen configurations on the held-out test
9. Run the transfer challenge separately

**The targeted change applies to both configurations.** If it were applied only to the candidate, call structure and prompt quality would vary together and neither could be credited for any difference.

This produces two independent findings:
- **A versus B on the held-out test**, isolating call structure
- **The improvement round on development**, isolating the prompt change, reported for both configurations

Sequential execution is used for both configurations throughout the experiment. Concurrency is not implemented. Latency results reflect sequential calls, so Candidate B's latency scales with criterion count.

Compare **extraction quality first, then end-to-end quality**, to distinguish a better extractor from a verifier that suppresses more answers.

One primary factor changes at a time. Model settings, prompt versions, concurrency, and verification behavior are recorded for every run.

If test findings prompt a further change, disclose that the test has been used for development and reserve fresh cases for confirmation.

---

## 8. Claim-verification annotation set

MET, NOT_MET, and AMBIGUOUS are **criterion-status labels**. They are not the same as whether a given evidence bundle supports a proposed claim. The verifier cannot be validated against criterion-status labels.

A small, separately annotated claim-verification set is required. **Twelve to eighteen deliberately varied evidence bundles.** It includes supported claims, real but irrelevant quotes, incorrect dates, negation errors, incomplete evidence, and contradictions.

Counts and limitations are reported alongside results.

Support verdicts are annotated manually from the presented evidence. These are prototype reference judgments from a single labeler, not expert clinical certification.

Report the confusion matrix and the false-acceptance rate on unsupported claims. Overall agreement alone does not authorize scaled scoring.

**Runtime verification and offline grading are distinct functions.** The verifier does not certify its own quality. If later used to score silver cases, those scores are labeled model-judged estimates, its measured limitations are preserved, and it is not the sole release criterion.

---

## 9. Metrics

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

## 10. Reviewer interaction

The reviewer opens a synthetic case, confirms the criteria version, runs analysis, and sees both processing completeness and clinical results.

Clicking a citation opens the corresponding source at the cited span.

The reviewer can record a correction, add a missing document, rerun analysis, and save an evidence-review summary.

Reviewer corrections are kept separate from model outputs and reference labels. The original result and the correction reason are preserved. A new document creates a new run and does not overwrite prior evidence history or leave stale statuses appearing current.

Saving a summary does not submit a coverage decision.

Corrections are visible as reviewer actions and do not contaminate held-out evaluation references.

---

## 11. Execution requirements

Finite timeouts and a small retry limit. Attempts and cost logged, including failures.

**Execution is sequential.** Concurrency is not implemented in this build. This policy is fixed for the duration of the experiment and stated in the results, because latency conclusions depend on it.

API keys held server-side, outside source files and saved run artifacts. No secrets or real patient information in the demonstration.

A small document prompt-injection challenge set is included. Structural separation of documents from instructions reduces confusion but is not a guarantee of resistance.

Each run records case and split, parent case where applicable, document hashes, criteria version, prompt and model versions, settings, parser version, stage outcomes, tokens, timing, retry count, and final output.

Recorded runs support inspection. Rerunning a model is not guaranteed to reproduce identical text.

One model version is used throughout, for evaluation and demonstration alike.

---

## 12. Standards alignment, light

Naming and structure align to FHIR concepts without implementing the resource layer.

- Evidence references a document identifier and version rather than a filename, corresponding to DocumentReference
- Criteria sets carry a version identifier, corresponding to Questionnaire
- Results correspond to QuestionnaireResponse in shape

No conformance to FHIR R4, Da Vinci PAS, DTR, or CRD implementation guides is claimed. No `Claim/$submit` operation, CQL execution, or X12 278 transport is implemented.

---

## 13. Demonstration requirements

The demonstration must show, live:

1. **A case run end to end**, selected live from the supported synthetic case list, not a recording
2. **Evidence requiring semantic interpretation**, located and cited with click-through to source. Where a contrast is shown, a documented keyword query is run alongside and its result displayed. No claim is made about what keyword search could or could not surface in general.
3. **A correct abstention**, where the system declines rather than guessing, with its reason codes visible
4. **A rejected citation**, produced by a clearly labeled deterministic fault-injection control
5. **A processing failure surfaced**, produced by a clearly labeled deterministic fault-injection control, showing a visible incomplete state rather than a clinical result
6. **The measured comparison**, presented as a product decision: which failure mattered, what changed, how quality and operating cost moved, which configuration was retained

**Fault injection is labeled as such.** Items 4 and 5 demonstrate that failure handling works. They are not observed model-error rates and are not presented as such.

Model tier and infrastructure choices are not narrated. Production optimizations, including prompt caching of the repeated packet, parallel per-criterion calls, and batch evaluation runs, are described as the production path rather than implemented.

**If the comparison shows no clear benefit**, the reported finding is: this small held-out evaluation did not provide sufficient evidence to justify the candidate's additional operating cost, and the baseline was retained for the prototype. No claim of equivalence is made, and no claim that the candidate never helps.

---

## 14. Excluded scope

Coverage determination output in any form. Vector retrieval or graph infrastructure. Automated policy extraction or applicability resolution. Fine-tuning. Autonomous agents. OCR. A second model. Calibrated confidence. Protected health information handling. Production access control. System integration. Elaborate dashboards.

Fine-tuning is deferred because the dataset is small and incremental value is unproven. Criteria remain external.

---

## 15. Known limitations

The corpus is authored. It contains conditions the author anticipated. Real submissions will present failure modes not represented.

Reference labels were authored by a single labeler. A blind adjudication of the twelve development packets was performed on 2026-09-09 by an independent reader with access only to the packets and the criteria, and no access to the labels. Measured agreement at status level was 95.8 percent, 69 of 72 criterion instances, Cohen's kappa 0.924. Including reason codes, agreement was 93.1 percent, 67 of 72.

All three status-level disagreements ran in the same direction: the independent reader resolved instances the reference holds open, twice to NOT_MET and once to MET. None ran the other way. The reference is therefore more conservative than an independent careful reader, which is the safer direction for this system but means the labels may hold open some instances a reviewer would consider settled.

**Reproducibility is not correctness.** A high kappa shows two readers applying the same criteria to the same documents reach the same answer. It does not show the answer is clinically right, and it cannot: both readers worked from the same synthetic criteria, and neither is a practising utilization management clinician. No expert clinical certification of these labels exists.

The measurement covers development only, n=72, one independent reader, one session. Held-out and transfer labels have not been independently adjudicated.

Three procedure types. Criteria structure varies substantially across procedure categories.

The transfer challenge is five fusion cases. It is a small exploratory result, not proof of generalization.

Measured verifier agreement does not by itself permit scaled trust. Error types, particularly false acceptance, require inspection, and single-labeler validation has limits.

**Reviewer time savings have not been measured for this prototype.**

Evidence must be present in the submitted record to be located.

Miss risk scales with reviewer trust. An unflagged retrieval failure carries greater consequence as adoption increases. AMBIGUOUS is rendered distinctly for this reason.

Demonstrated technical results on synthetic cases are distinct from nursing productivity and clinical outcomes, neither of which is measured here.