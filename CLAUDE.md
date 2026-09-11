# CLAUDE.md

Read `docs/PROTOTYPE_SPEC.md` before starting any task. It is the authoritative specification. This file is orientation.

## What this is

A prototype that helps a utilization management reviewer check a prior authorization request against medical necessity criteria. For each requirement, the system locates relevant passages in the submitted clinical record, cites where they appear, and reports a clinical result.

Prototype scope. Not production software.

## Hard constraints

**No coverage determination.** No approve, deny, recommendation, or aggregate score anywhere in code, output, or interface. If you find yourself writing a field named `recommendation`, `decision`, `approved`, or similar, stop. The output vocabulary is evidence status only.

A licensed physician must be involved before a Medicare Advantage plan denies coverage. Some states require medical necessity determinations to come from a licensed professional rather than software. The architecture reflects that.

**Clinical status and processing status are separate fields.** A parse failure or timeout is `processing_status: FAILED`, never a clinical result. A system failure must never appear as a clinical finding.

**"Not found" is not "not present."** A retrieval failure resolves to AMBIGUOUS with MISSING_EVIDENCE. The system never converts absence of located evidence into NOT_MET.

**NOT_MET has a high bar.** Eight documented weeks against a twelve-week threshold does not automatically establish NOT_MET. The reference label must establish that the evidence is current and relevant, that other notes and exceptions were accounted for, and why it is affirmatively contradictory. Otherwise AMBIGUOUS.

**Evidence is a list.** Duration may need a start and end date in separate passages. A contradiction needs both sides. Never a single quote field.

**No displayed confidence.** May exist as an internal field. Never rendered as a percentage. It is not calibrated.

## Architecture

Six steps. Steps 3 and 5 use the model. Steps 1, 2, 4, 6 do not.

1. Load versioned criteria set by procedure code. Deterministic.
2. Ingest documents. Stable ids, content hashes, canonical span positions. Deterministic.
3. Evidence extraction. Two configurations sharing an identical prompt.
4. Quote verification by string match against canonical source. Deterministic.
5. Support verification. Second model call, evidence only, no packet.
6. Assemble evidence map. Deterministic.

**Baseline A:** one extraction call, all criteria.
**Candidate B:** one extraction call per criterion.

Per-criterion calls are a testable hypothesis, not an established improvement. Do not write comments or documentation asserting they guarantee better attention or independent errors.

## Experiment discipline

Splits are assigned before any tuning: 12 development, 8 held-out test, 5 transfer.

The targeted improvement applies to **both** configurations. Applying it to one would confound call structure with prompt quality.

All ablations and variants stay in their parent case's split.

Execution is sequential. No concurrency in this build.

One model version throughout, extraction and verification alike.

## What not to do

- No approve or deny output in any form
- No converting "not found" into NOT_MET
- No vector database, embeddings, or graph infrastructure
- No automated policy extraction or applicability resolution
- No fine-tuning
- No agent framework
- No OCR
- No second model
- No concurrency
- No clean, tidy synthetic documents. If the corpus is easy the evaluation proves nothing.
- No reproduction of MCG or InterQual criteria. These are licensed products.

## Standards alignment, light only

Evidence references a document identifier and version rather than a filename. Criteria sets carry a version. Results are QuestionnaireResponse-shaped in structure.

No conformance to FHIR R4 or Da Vinci implementation guides is claimed. Do not implement resource classes, `Claim/$submit`, CQL, or X12 transport.

## Interface

Streamlit. Internal tool aesthetic is appropriate. Visual polish is explicitly not the priority.

Must state on screen that criteria and cases are synthetic and are not Humana coverage policies.

AMBIGUOUS renders distinctly from NOT_MET with reason codes visible.

No decision control anywhere.

## Logging

Every run records case and split, parent case where applicable, document hashes, criteria version, prompt and model versions, settings, parser version, stage outcomes, tokens, timing, retry count, final output.

Raw extraction output is retained separately from final verified output. Rejected results are preserved in the run log.

API keys server-side, outside source files and saved artifacts.