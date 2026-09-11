"""Steps 4 and 5: quote verification, then support verification.

Step 4 is deterministic. Every returned quote is matched against the canonical
text of the document it names. A quote that does not match is *unverifiable*,
which is a statement about this check and not an accusation: a model can
paraphrase a real passage, and a paraphrase of something true is still not a
citation. The span is rejected either way, because a citation that cannot be
resolved to a location is not verifiable, and verifiability is the product.

Step 5 uses the model a second time. It receives the criterion, the exception
rules, the proposed status and the verified evidence, and **not the packet**.
Withholding the packet is the point of the step: a verifier that can see the
record can re-derive the answer and agree with itself. Seeing only what was
cited, it can answer the narrower question of whether the cited passages
actually support the conclusion drawn from them.

What Step 4 does to a conclusion
--------------------------------
Spec Section 3: reject the span, preserve the reason, retain any independently
valid spans, and where the conclusion loses its support, downgrade to
unresolved. Downgrading is the part that is easy to get wrong, because whether
a conclusion still stands depends on the instance's evidence requirement:

- ALTERNATIVE — one surviving span is enough. The conclusion stands.
- COMPOSITE — every unit is load-bearing. Losing one collapses the conclusion.

The extraction output does not say which shape applies; that lives in the
reference and is not available at runtime. So the rule applied here is the
conservative one: a determinate conclusion that has lost *any* of its cited
support is downgraded to AMBIGUOUS. A conclusion resting on nothing at all is
always downgraded.

Step 5 is skipped where there is nothing to check
-------------------------------------------------
Spec Section 5 says to skip support verification for missing-evidence outputs
making no affirmative claim. An AMBIGUOUS/MISSING_EVIDENCE result asserts that
nothing was found, cites nothing, and cannot be supported or contradicted by
evidence it does not have. Sending it would spend a call to be told what the
absence of evidence already says.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from .criteria import Criterion, CriteriaSet
from .extract import (
    Attempt, CriterionExtraction, ExtractionRun, ModelClient, _call_once,
    DEFAULT_MAX_TOKENS, DEFAULT_MODEL, DEFAULT_TEMPERATURE,
    DEFAULT_TIMEOUT_SECONDS, MAX_ATTEMPTS, scrub_secrets,
)
from .ingest import IngestedPacket
from .prompts import ExtractionPrompt
from .results import (
    ClinicalStatus, FailureKind, ProcessingStatus, ReasonCode, Span,
)

# 1.0.0  First live prompt. On MRI-004 C3 it returned UNSUPPORTED against a
#        correct AMBIGUOUS/CONFLICTING_EVIDENCE result, reasoning that the
#        criterion "requires a clear determination, not an unresolved conflict
#        flag". That is a misreading of the task: the question is whether the
#        passages support the claim, not whether abstention is a satisfying
#        answer. It caused no harm only because downgrading is guarded to
#        determinate statuses; on a MET result the same error would have
#        overturned a correct answer.
# 1.1.0  States that an unresolved status is a claim like any other, and what
#        supporting one looks like for each AMBIGUOUS reason code.
SUPPORT_PROMPT_VERSION = "support/1.1.0"

DETERMINATE = (ClinicalStatus.MET, ClinicalStatus.NOT_MET)


# ==========================================================================
# Step 4: quote verification. Deterministic, no model.
# ==========================================================================

@dataclass
class VerifiedEvidence:
    """One cited passage after matching against its source."""

    document_id: str
    quote: str
    role: str
    span: Span | None = None
    verified: bool = False
    detail: str = ""
    ambiguous_locations: int = 0

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "quote": self.quote,
            "role": self.role,
            "verified": self.verified,
            "span": self.span.as_dict() if self.span else None,
            "detail": self.detail,
            "ambiguous_locations": self.ambiguous_locations,
        }


@dataclass
class VerifiedCriterion:
    """One criterion after Step 4, and after Step 5 where it ran."""

    criterion_id: str
    clinical_status: ClinicalStatus | None
    processing_status: ProcessingStatus
    reason_codes: list[ReasonCode] = field(default_factory=list)
    evidence: list[VerifiedEvidence] = field(default_factory=list)
    explanation: str = ""
    detail: str = ""
    failure_kind: FailureKind = FailureKind.NONE
    extracted_status: ClinicalStatus | None = None
    downgraded: bool = False
    downgrade_reason: str = ""
    support_checked: bool = False
    support_outcome: str = ""
    support_detail: str = ""

    @property
    def verified_evidence(self) -> list[VerifiedEvidence]:
        return [e for e in self.evidence if e.verified]

    @property
    def rejected_evidence(self) -> list[VerifiedEvidence]:
        return [e for e in self.evidence if not e.verified]

    def as_dict(self) -> dict:
        return {
            "criterion_id": self.criterion_id,
            "clinical_status": self.clinical_status.value if self.clinical_status else None,
            "processing_status": self.processing_status.value,
            "reason_codes": [r.value for r in self.reason_codes],
            "evidence": [e.as_dict() for e in self.evidence],
            "explanation": self.explanation,
            "detail": self.detail,
            "failure_kind": self.failure_kind.value,
            "extracted_status": (self.extracted_status.value
                                 if self.extracted_status else None),
            "downgraded": self.downgraded,
            "downgrade_reason": self.downgrade_reason,
            "verification": {
                "quote_check": {
                    "returned": len(self.evidence),
                    "verified": len(self.verified_evidence),
                    "rejected": len(self.rejected_evidence),
                },
                "support_check": {
                    "ran": self.support_checked,
                    "outcome": self.support_outcome,
                    "detail": self.support_detail,
                },
            },
        }


def verify_quotes(result: CriterionExtraction,
                  packet: IngestedPacket) -> VerifiedCriterion:
    """Step 4 for one criterion. Deterministic.

    A quote is verified when it resolves to exactly one span in the document it
    names. Resolving to several is not a failure of the quote but a failure of
    the citation to identify a location, and Spec Section 3 requires evidence
    to carry a source span. Copy-forward makes this real rather than
    hypothetical: MRI-005 repeats a 299-character block across two notes nine
    weeks apart, and which encounter a passage came from is exactly what its
    duration criterion turns on.
    """
    out = VerifiedCriterion(
        criterion_id=result.criterion_id,
        clinical_status=result.clinical_status,
        processing_status=result.processing_status,
        reason_codes=list(result.reason_codes),
        explanation=result.explanation,
        detail=result.detail,
        failure_kind=result.failure_kind,
        extracted_status=result.clinical_status,
    )

    for item in result.evidence:
        checked = VerifiedEvidence(document_id=item.document_id,
                                   quote=item.quote, role=item.role)
        try:
            document = packet.by_id(item.document_id)
        except KeyError:
            checked.detail = (f"no document {item.document_id} in this packet; "
                              f"the citation names a source that was not read")
            out.evidence.append(checked)
            continue

        if not document.outcome.is_usable:
            checked.detail = (f"{document.filename} is {document.outcome.value} "
                              f"and has no citable text")
            out.evidence.append(checked)
            continue

        spans = document.locate(item.quote)
        if not spans:
            checked.detail = ("quote does not appear in the cited document. It "
                              "may still be a true statement about the record; "
                              "it is not a citation.")
        elif len(spans) > 1:
            checked.ambiguous_locations = len(spans)
            checked.detail = (f"quote appears {len(spans)} times in "
                              f"{document.filename}; the citation does not "
                              f"identify which occurrence is meant")
        else:
            checked.span = spans[0]
            checked.verified = True
        out.evidence.append(checked)

    _apply_rejections(out)
    return out


def _apply_rejections(out: VerifiedCriterion) -> None:
    """Downgrade a conclusion that lost its support. Spec Section 3."""
    if out.clinical_status is None or not out.rejected_evidence:
        return

    out.reason_codes = _with_code(out.reason_codes, ReasonCode.UNVERIFIABLE_QUOTE)

    if out.clinical_status not in DETERMINATE:
        # LOAD-BEARING. Do not remove as redundant.
        #
        # This reads like a no-op guard: an AMBIGUOUS result has nothing to be
        # downgraded to. That was the reason it was written. It is not the
        # reason it matters now.
        #
        # The Step 5 verifier still returns UNSUPPORTED on correct
        # AMBIGUOUS/CONFLICTING_EVIDENCE results, treating an unresolved status
        # as though it were not a claim. support/1.1.0 was written to fix that
        # and both contradiction bundles in the claim-verification set failed,
        # which is the whole population of such bundles. This branch is the
        # only reason that defect produced no harm in any scored run.
        #
        # Removing it surfaces the defect immediately, as a correct unresolved
        # result rewritten by a verifier error. Fix the verifier first. See
        # docs/DATA_CARD.md, "Three limitations found on the last day".
        return

    if not out.verified_evidence:
        out.downgrade_reason = (
            f"{out.clinical_status.value} rested entirely on "
            f"{len(out.rejected_evidence)} quote(s), none of which verified")
    else:
        # Conservative: the runtime cannot tell ALTERNATIVE from COMPOSITE, so
        # it cannot know whether the lost unit was load-bearing. Standing on a
        # determinate status while part of its stated basis has been withdrawn
        # would present a reviewer with a conclusion the system can no longer
        # fully evidence.
        out.downgrade_reason = (
            f"{len(out.rejected_evidence)} of {len(out.evidence)} cited quote(s) "
            f"did not verify; whether the remainder is sufficient depends on the "
            f"criterion's evidence shape, which is not available at runtime")

    out.downgraded = True
    out.clinical_status = ClinicalStatus.AMBIGUOUS
    out.reason_codes = _with_code(out.reason_codes, ReasonCode.INSUFFICIENT_CONTEXT)


def _with_code(codes: list[ReasonCode], code: ReasonCode) -> list[ReasonCode]:
    return codes if code in codes else [*codes, code]


# ==========================================================================
# Step 5: support verification. Second model call, evidence only.
# ==========================================================================

SUPPORT_SYSTEM = """\
You are checking one claim against the evidence offered for it.

You are given a requirement, a proposed status, and the passages that were \
cited in support of that status. You are deliberately not given the patient's \
record. Do not ask for it and do not reason about what it might contain. The \
question is narrow and it is not whether the status is clinically right:

  Do the passages shown actually support the status claimed for them?

An unresolved status is a claim like any other, and it is a legitimate one. \
Where the proposed status is AMBIGUOUS, you are not being asked whether a \
determinate answer was possible, or whether unresolved is a satisfying \
outcome. You are being asked whether the passages support *that* claim:

  AMBIGUOUS with CONFLICTING_EVIDENCE   Do the passages actually conflict, and
                                        is more than one side shown?
  AMBIGUOUS with INSUFFICIENT_CONTEXT   Do the passages bear on the
                                        requirement without settling it?
  AMBIGUOUS with VAGUE_DURATION         Is the time element really too
                                        imprecise to evaluate?

Answering UNSUPPORTED because a requirement "needs a determination" is a \
misreading of the task. Abstention is a correct outcome and the evidence for \
it is judged the same way as any other.

Answer SUPPORTED only if the passages establish the status on their own. \
Answer UNSUPPORTED if they do not, which includes each of these:

  - the passage is about a different body site, episode, or timeframe
  - the passage shows something was planned, offered, or declined, where the
    requirement asks for something attempted
  - the passage is negated, hedged, or attributed to someone whose statement
    cannot settle the point
  - a date or quantity is misread, or an interval is computed wrongly
  - the requirement needs two things and only one is shown
  - the status is a contradiction but only one side is present

Answer INCONCLUSIVE where you cannot tell from what you were given. Do not \
guess, and do not treat INCONCLUSIVE as a soft UNSUPPORTED. They are different \
findings: one says the evidence fails, the other says you cannot judge.

Return a single JSON object and nothing else:

{"outcome": "SUPPORTED", "detail": "one sentence"}"""

VALID_SUPPORT_OUTCOMES = ("SUPPORTED", "UNSUPPORTED", "INCONCLUSIVE")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def build_support_prompt(criterion: Criterion, criteria_set: CriteriaSet,
                         result: VerifiedCriterion) -> ExtractionPrompt:
    """Assemble the Step 5 prompt. Carries evidence, never the packet."""
    lines = [
        "<requirement>",
        criterion.as_prompt_block(),
        f"Evidence shape: {criterion.evidence_requirement}",
    ]
    if criteria_set.has_exception_pathway and criteria_set.exception_note:
        lines += ["", "EXCEPTION PATHWAY", criteria_set.exception_note]
    lines += ["</requirement>", "", "<proposed>",
              f"status: {result.clinical_status.value if result.clinical_status else 'none'}",
              f"reason codes: {[c.value for c in result.reason_codes] or 'none'}",
              f"explanation: {result.explanation or 'none given'}",
              "</proposed>", "", "<evidence>"]

    for index, item in enumerate(result.verified_evidence, start=1):
        lines.append(f'{index}. [{item.role}] "{item.quote}"')
    if not result.verified_evidence:
        lines.append("(none)")
    lines += ["</evidence>", "",
              "Do the passages support the proposed status? Return the JSON object."]

    body = "\n".join(lines)
    return ExtractionPrompt(
        system=SUPPORT_SYSTEM, criteria_block=body, record_block="",
        task_block="", criterion_ids=(result.criterion_id,),
        exempt_text=(criterion.as_prompt_block(),),
        prompt_version=SUPPORT_PROMPT_VERSION,
    )


def parse_support(text: str) -> tuple[str, str]:
    """Parse a support response, or raise ValueError. Nothing is repaired."""
    stripped = _FENCE.sub("", text.strip())
    if not stripped:
        raise ValueError("empty response")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("response is not an object")
    outcome = payload.get("outcome")
    if outcome not in VALID_SUPPORT_OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of "
                         f"{list(VALID_SUPPORT_OUTCOMES)}")
    detail = payload.get("detail", "")
    if not isinstance(detail, str):
        raise ValueError("detail is not a string")
    return outcome, detail


def needs_support_check(result: VerifiedCriterion) -> bool:
    """Whether Step 5 has anything to check.

    Spec Section 5 skips missing-evidence outputs making no affirmative claim.
    A result with no verified evidence asserts nothing that evidence could
    support, and a result with no clinical status was never a claim.
    """
    if result.clinical_status is None:
        return False
    if not result.verified_evidence:
        return False
    return True


def verify_support(result: VerifiedCriterion, criterion: Criterion,
                   criteria_set: CriteriaSet, client: ModelClient,
                   run: ExtractionRun | None = None, *,
                   model: str = DEFAULT_MODEL,
                   max_tokens: int = 1000,
                   temperature: float | None = DEFAULT_TEMPERATURE,
                   timeout: float = DEFAULT_TIMEOUT_SECONDS,
                   max_attempts: int = MAX_ATTEMPTS) -> VerifiedCriterion:
    """Step 5 for one criterion. Mutates and returns the result.

    An UNSUPPORTED finding downgrades a determinate status to AMBIGUOUS with
    UNSUPPORTED_CONCLUSION. An INCONCLUSIVE finding changes nothing and is
    recorded: Spec Section 3 requires inconclusive checks to be reported rather
    than silently treated as passes, and treating one as a failure would let
    the verifier's own uncertainty rewrite a clinical result.
    """
    if not needs_support_check(result):
        result.support_checked = False
        result.support_outcome = "SKIPPED"
        result.support_detail = ("no affirmative claim resting on verified "
                                 "evidence; nothing for the verifier to check")
        return result

    prompt = build_support_prompt(criterion, criteria_set, result)
    last = "no attempt was made"
    for index in range(1, max_attempts + 1):
        attempt = _call_once(client, prompt, index, model, max_tokens,
                             temperature, timeout)
        if run is not None:
            run.attempts.append(attempt)
        if attempt.error:
            last = attempt.error
            if not attempt.retryable:
                break
            continue
        try:
            outcome, detail = parse_support(attempt.raw_text)
        except ValueError as exc:
            attempt.parse_error = str(exc)
            last = str(exc)
            continue

        result.support_checked = True
        result.support_outcome = outcome
        result.support_detail = detail
        if outcome == "UNSUPPORTED" and result.clinical_status in DETERMINATE:
            result.downgraded = True
            result.downgrade_reason = f"support check found the evidence insufficient: {detail}"
            result.clinical_status = ClinicalStatus.AMBIGUOUS
            result.reason_codes = _with_code(result.reason_codes,
                                             ReasonCode.UNSUPPORTED_CONCLUSION)
        return result

    # The check could not be run. That is a fact about the verifier and not
    # about the record, so it is recorded without touching the clinical status.
    result.support_checked = False
    result.support_outcome = "FAILED"
    result.support_detail = scrub_secrets(f"support check did not complete: {last}")
    return result


# ==========================================================================
# Both steps over a whole run
# ==========================================================================

@dataclass
class VerificationRun:
    case_id: str
    configuration: str
    results: list[VerifiedCriterion] = field(default_factory=list)
    support_attempts: list[Attempt] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def processing_status(self) -> ProcessingStatus:
        if not self.results:
            return ProcessingStatus.FAILED
        failed = [r for r in self.results
                  if r.processing_status is ProcessingStatus.FAILED]
        if not failed:
            return ProcessingStatus.COMPLETE
        if len(failed) == len(self.results):
            return ProcessingStatus.FAILED
        return ProcessingStatus.PARTIAL

    @property
    def returned_spans(self) -> int:
        return sum(len(r.evidence) for r in self.results)

    @property
    def verified_spans(self) -> int:
        return sum(len(r.verified_evidence) for r in self.results)

    @property
    def citation_validity(self) -> float | None:
        """Spec Section 9. None where nothing was returned, never 1.0."""
        return (self.verified_spans / self.returned_spans
                if self.returned_spans else None)

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "configuration": self.configuration,
            "processing_status": self.processing_status.value,
            "returned_spans": self.returned_spans,
            "verified_spans": self.verified_spans,
            "citation_validity": self.citation_validity,
            "downgraded": sum(1 for r in self.results if r.downgraded),
            "support_outcomes": {
                o: sum(1 for r in self.results if r.support_outcome == o)
                for o in (*VALID_SUPPORT_OUTCOMES, "SKIPPED", "FAILED")},
            "seconds": round(self.seconds, 3),
            "results": [r.as_dict() for r in self.results],
            "support_attempts": [a.as_dict() for a in self.support_attempts],
        }


# Stage names reported through `on_progress`. They are the vocabulary the
# interface shows a viewer, kept here rather than in the interface so the
# names describe what the pipeline does rather than what a screen wants to
# say. Spec Section 4: the two checks are separate and both are visible.
STAGE_QUOTE_CHECK = "checking the quote"
STAGE_SUPPORT_CHECK = "checking the quote supports the claim"
STAGE_DONE = "done"


def verify_run(extraction: ExtractionRun, packet: IngestedPacket,
               criteria_set: CriteriaSet, client: ModelClient | None = None,
               on_progress=None, **kwargs) -> VerificationRun:
    """Steps 4 and 5 across one extraction run.

    Step 4 always runs; it needs no model. Step 5 runs only where a client is
    given, so quote verification can be exercised on its own.

    `on_progress(criterion_id, stage, result)` is called before each stage
    begins and once after the criterion is finished, so a caller can render
    progress while the run is still going. It is optional and defaults to
    None: every existing call site behaves exactly as before. `result` is the
    partially verified criterion, or None where the stage has not produced one
    yet. A callback that raises is not caught — a broken display should fail
    loudly rather than silently stop reporting halfway through a run.
    """
    run = VerificationRun(case_id=extraction.case_id,
                          configuration=extraction.configuration)
    started = time.monotonic()

    def report(criterion_id, stage, result=None):
        if on_progress is not None:
            on_progress(criterion_id, stage, result)

    for result in extraction.results:
        report(result.criterion_id, STAGE_QUOTE_CHECK)
        checked = verify_quotes(result, packet)
        # Reported after Step 4 and before Step 5 so a rejected quote is
        # visible at the moment it is rejected, not only in the final state.
        report(checked.criterion_id, STAGE_SUPPORT_CHECK, checked)
        if client is not None and checked.criterion_id in criteria_set.criterion_ids:
            holder = ExtractionRun(case_id=extraction.case_id,
                                   configuration=extraction.configuration,
                                   model=extraction.model,
                                   prompt_version=SUPPORT_PROMPT_VERSION)
            verify_support(checked, criteria_set[checked.criterion_id],
                           criteria_set, client, holder, **kwargs)
            run.support_attempts.extend(holder.attempts)
        run.results.append(checked)
        report(checked.criterion_id, STAGE_DONE, checked)

    run.seconds = time.monotonic() - started
    return run
