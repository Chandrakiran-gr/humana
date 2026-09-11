"""Step 3: evidence extraction, in two configurations.

Baseline A makes one call carrying the whole packet and every criterion.
Candidate B makes one call per criterion, each carrying the whole packet. Both
build their prompt with `prompts.build_extraction_prompt`, so the only thing
that differs is call structure. Per-criterion calls are a testable hypothesis
and nothing here should be read as asserting they work better.

Three things this module is careful about.

**A failure is never a finding.** A timeout, a malformed response, a refusal, an
invented criterion id: each of these produces a result whose `clinical_status`
is None and whose `processing_status` is FAILED, carrying PROCESSING_ERROR.
None is not AMBIGUOUS. AMBIGUOUS means the record was read and did not settle
the question; None means no clinical judgement was reached at all. Collapsing
them would let an outage look like a corpus of unresolved cases.

**Raw output is kept.** Spec Section 3 requires rejected raw results to be
preserved in the run log, so every attempt is retained on the result whether it
parsed or not. A malformed response that is thrown away cannot be diagnosed.

**Nothing is repaired quietly.** A response naming a criterion that was not
asked about, or a status outside the four, or a reason code reserved for a
later step, is rejected and recorded. Coercing it to the nearest legal value
would produce a clinical status the model did not assert.

Execution is sequential. Spec Section 11 fixes that for the experiment, and
Candidate B's latency is only interpretable against it.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from .criteria import CriteriaSet
from .ingest import IngestedPacket
from .prompts import (
    EXTRACTOR_REASON_CODES, PROMPT_VERSION, ExtractionPrompt,
    build_extraction_prompt,
)
from .results import ClinicalStatus, FailureKind, ProcessingStatus, ReasonCode

DEFAULT_MODEL = "claude-sonnet-5"

# Settings that change what the model does, versioned so a run log records
# which regime produced it. Spec Section 11 requires settings in every run
# record; a change here invalidates comparison with runs made under an
# earlier value.
#
# 1  Implicit defaults. Extended thinking was ON, because it is the model
#    default for claude-sonnet-5 and nothing here disabled it.
# 2  Extended thinking explicitly disabled. See docs/DATA_CARD.md.
SETTINGS_VERSION = "settings/2"

# Extended thinking is disabled deliberately, and this is not a performance
# tweak. Thinking tokens count against max_tokens, are not returned as text,
# and the model decides adaptively per request whether to use them. On MRI-007
# that produced 6,893, 7,732, 11,288 and once more than 16,000 output tokens
# from identical input, with the last returning no text at all and failing.
# Disabling it cut that case to 2,232 output tokens while returning 6,487
# characters of answer against 3,882: fewer tokens, more content.
#
# Whether thinking improves extraction quality was never measured and is an
# open question in the roadmap. What is established is that it consumed most
# of the output budget, varied without bound, and crossed a hard limit
# unpredictably.
THINKING = {"type": "disabled"}
# Raised from 8000 after the first development run. Three of fifteen cases
# exhausted the limit exactly, and the failure presented as "empty response"
# and "not valid JSON: Unterminated string", which named the symptom and hid
# the cause. A nine-criterion set with evidence and explanations does not fit
# in 8000 output tokens.
DEFAULT_MAX_TOKENS = 16000
MAX_ATTEMPTS = 3
DEFAULT_TIMEOUT_SECONDS = 120.0

# Not sent unless explicitly set. The first live run returned 400
# "`temperature` is deprecated for this model", so sending a default of 0.0
# made every call fail before the packet was ever read. Sampling settings are
# a property of the model rather than of this pipeline, and the run log records
# what was sent, so omitting it is both correct and honest.
DEFAULT_TEMPERATURE: float | None = None

# HTTP statuses where the request itself is the problem. Retrying one of these
# repeats an identical request and gets an identical refusal: the first live
# run made three calls and three 400s in 0.9 seconds. Spec Section 11 asks for
# a small retry limit, which is for transient failure, not for a request the
# server has already told us it will never accept.
NON_RETRYABLE_STATUS = frozenset({400, 401, 403, 404, 405, 413, 422})

VALID_STATUSES = {s.value for s in ClinicalStatus}
VALID_ROLES = {"supporting", "contradicting"}

# Spec Section 11: keys are held outside source files and saved run artifacts.
# Everything an attempt captures is written to the run log, and a transport
# exception is a string the SDK composed, not one this code controls. It has no
# business carrying a credential, but "has no business" is not an enforcement,
# and a key that reaches a log has to be rotated rather than deleted.
_SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]{8,}")


def scrub_secrets(text: str) -> str:
    return _SECRET.sub("sk-ant-<redacted>", text)


def is_retryable(exc: BaseException) -> bool:
    """Whether repeating this call could plausibly succeed.

    Unknown failures are treated as retryable, because the cost of one extra
    call is small and the cost of abandoning a recoverable run is a gap in the
    results. A status the server has already rejected is not.
    """
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status not in NON_RETRYABLE_STATUS
    return True


# --------------------------------------------------------------------------
# Transport
# --------------------------------------------------------------------------

class ModelClient(Protocol):
    """The one call this module makes.

    Narrow on purpose. Tests substitute a client that returns canned text,
    including malformed text, so the rejection paths can be exercised without a
    network. Those paths are most of the behaviour worth testing, and they are
    unreachable through a real API that mostly returns well-formed JSON.
    """

    def complete(self, system: str, user: str, *, model: str, max_tokens: int,
                 temperature: float, timeout: float) -> "ModelResponse": ...


@dataclass(frozen=True)
class ModelResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


class AnthropicClient:
    """The real transport. Constructed lazily so tests never need a key."""

    def __init__(self, api_key: str | None = None) -> None:
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key) if api_key else \
            anthropic.Anthropic()

    def complete(self, system: str, user: str, *, model: str, max_tokens: int,
                 temperature: float | None, timeout: float) -> ModelResponse:
        kwargs = dict(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            timeout=timeout,
        )
        if temperature is not None:
            kwargs["temperature"] = temperature
        if THINKING is not None:
            kwargs["thinking"] = THINKING
        message = self._client.messages.create(**kwargs)
        text = "".join(b.text for b in message.content if b.type == "text")
        return ModelResponse(
            text=text,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            stop_reason=message.stop_reason or "",
        )


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

@dataclass
class ExtractedEvidence:
    """One cited passage, before Step 4 has checked it.

    The quote is what the model returned. It has not been matched against any
    document yet, so it carries no span. Step 4 resolves it, and until then it
    is a claim about the record rather than a location in it.
    """

    document_id: str
    quote: str
    role: str

    def as_dict(self) -> dict:
        return {"document_id": self.document_id, "quote": self.quote, "role": self.role}


@dataclass
class CriterionExtraction:
    """One criterion's extracted result.

    `clinical_status` is None exactly when no clinical judgement was reached.
    See the module docstring on why that is not AMBIGUOUS.
    """

    criterion_id: str
    clinical_status: ClinicalStatus | None = None
    processing_status: ProcessingStatus = ProcessingStatus.COMPLETE
    reason_codes: list[ReasonCode] = field(default_factory=list)
    evidence: list[ExtractedEvidence] = field(default_factory=list)
    explanation: str = ""
    detail: str = ""
    failure_kind: FailureKind = FailureKind.NONE
    rejected_payload: dict | None = None

    @property
    def ok(self) -> bool:
        return self.processing_status is ProcessingStatus.COMPLETE

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
            "rejected_payload": self.rejected_payload,
        }


@dataclass
class Attempt:
    """One model call, retained whether or not it produced anything usable."""

    index: int
    raw_text: str
    input_tokens: int = 0
    output_tokens: int = 0
    seconds: float = 0.0
    error: str = ""
    parse_error: str = ""
    retryable: bool = True
    stop_reason: str = ""
    preamble: bool = False

    def as_dict(self) -> dict:
        return {
            "index": self.index, "seconds": round(self.seconds, 3),
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "error": self.error, "parse_error": self.parse_error,
            "retryable": self.retryable, "stop_reason": self.stop_reason,
            "preamble": self.preamble,
            "raw_text": self.raw_text,
        }


@dataclass
class ExtractionRun:
    """Everything one configuration did for one case.

    `attempts` is the raw record and `results` is the parsed one, kept apart
    because Spec Section 3 requires rejected raw output to survive.
    """

    case_id: str
    configuration: str
    model: str
    prompt_version: str
    results: list[CriterionExtraction] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)
    prompts: list[dict] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def calls(self) -> int:
        return len(self.attempts)

    @property
    def input_tokens(self) -> int:
        return sum(a.input_tokens for a in self.attempts)

    @property
    def output_tokens(self) -> int:
        return sum(a.output_tokens for a in self.attempts)

    def count_failures(self, kind: FailureKind) -> int:
        return sum(1 for r in self.results if r.failure_kind is kind)

    @property
    def contract_rejections(self) -> list[CriterionExtraction]:
        """Answers refused on shape. Reported apart from clinical errors.

        A clinically correct answer rejected on format is a different failure
        from a wrong answer, and pooling them would misstate status
        performance in both directions at once.
        """
        return [r for r in self.results
                if r.failure_kind is FailureKind.CONTRACT_REJECTION]

    @property
    def processing_status(self) -> ProcessingStatus:
        """Aggregate state. Derived from the results, never from a clinical value."""
        if not self.results:
            return ProcessingStatus.FAILED
        failed = [r for r in self.results if not r.ok]
        if not failed:
            return ProcessingStatus.COMPLETE
        if len(failed) == len(self.results):
            return ProcessingStatus.FAILED
        return ProcessingStatus.PARTIAL

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "configuration": self.configuration,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "settings_version": SETTINGS_VERSION,
            "parser_version": PARSER_VERSION,
            "processing_status": self.processing_status.value,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "seconds": round(self.seconds, 3),
            "failures": {k.value: self.count_failures(k) for k in FailureKind
                         if k is not FailureKind.NONE},
            "results": [r.as_dict() for r in self.results],
            "prompts": self.prompts,
            "attempts": [a.as_dict() for a in self.attempts],
        }


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

class MalformedResponse(ValueError):
    """The response could not be read as the agreed contract. Never repaired."""


# Spec Section 11 requires the parser version in every run record.
# 1  Strip a code fence at the start or end of the whole response.
# 2  Also accept a fenced JSON block preceded by prose. Disabling extended
#    thinking moved the model's reasoning into the text channel, where it
#    appears as preamble before the JSON. MRI-007 failed three attempts with
#    "Expecting value: line 1 column 1" on complete, well-formed responses
#    whose JSON began 7,000 characters in.
PARSER_VERSION = "parser/2"

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")
_FENCED_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def extract_json_text(text: str) -> tuple[str, bool]:
    """Return the JSON payload and whether anything preceded it.

    This is parsing, not repair. The prompt asks for a bare JSON object; where
    the model wraps it in a fence or precedes it with commentary, there is
    exactly one candidate object and no judgement is involved in finding it.
    Nothing about the content is altered, and the fact that preamble was
    present is recorded on the attempt so its frequency is visible rather
    than absorbed.
    """
    stripped = _FENCE.sub("", text.strip())
    if stripped.startswith("{"):
        return stripped, False
    blocks = _FENCED_BLOCK.findall(text)
    if blocks:
        return blocks[-1], True
    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        return text[first:last + 1], True
    return stripped, False


def parse_response(text: str, expected_ids: tuple[str, ...]) -> dict[str, dict]:
    """Parse a response into {criterion_id: payload}, or raise.

    Strictness is the point. Everything this rejects would otherwise become a
    clinical status that the model did not actually assert, on a row a reviewer
    is being asked to trust.

    A surrounding code fence is stripped, because that is a formatting habit
    rather than a disagreement about content. Nothing else is repaired.
    """
    stripped, _ = extract_json_text(text)
    if not stripped:
        raise MalformedResponse("empty response")
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise MalformedResponse(f"not valid JSON: {exc}") from exc

    if not isinstance(payload, dict) or "results" not in payload:
        raise MalformedResponse("no 'results' key at the top level")
    if not isinstance(payload["results"], list):
        raise MalformedResponse("'results' is not a list")

    out: dict[str, dict] = {}
    for entry in payload["results"]:
        if not isinstance(entry, dict):
            raise MalformedResponse(f"result entry is not an object: {entry!r}")
        cid = entry.get("criterion_id")
        if cid not in expected_ids:
            raise MalformedResponse(
                f"criterion_id {cid!r} was not asked about; expected one of "
                f"{list(expected_ids)}")
        if cid in out:
            raise MalformedResponse(f"criterion_id {cid!r} returned more than once")
        out[cid] = entry
    return out


def build_result(criterion_id: str, entry: dict) -> CriterionExtraction:
    """Validate one entry into a result, or return an explicit failure.

    A failure here is a processing failure. It carries no clinical status,
    because the alternative is inventing one.
    """
    def failed(detail: str) -> CriterionExtraction:
        # A contract rejection: the model answered and the shape was refused.
        # The payload is retained so a reviewer can see what was rejected and
        # judge whether the clinical reading was sound despite the shape.
        return CriterionExtraction(
            criterion_id=criterion_id, clinical_status=None,
            processing_status=ProcessingStatus.FAILED,
            reason_codes=[ReasonCode.PROCESSING_ERROR], detail=detail,
            failure_kind=FailureKind.CONTRACT_REJECTION,
            rejected_payload=entry)

    status = entry.get("clinical_status")
    if status not in VALID_STATUSES:
        return failed(f"clinical_status {status!r} is not one of {sorted(VALID_STATUSES)}")

    raw_codes = entry.get("reason_codes") or []
    if not isinstance(raw_codes, list):
        return failed("reason_codes is not a list")
    for code in raw_codes:
        if code not in EXTRACTOR_REASON_CODES:
            return failed(
                f"reason code {code!r} is not one the extractor may assign; "
                f"permitted: {list(EXTRACTOR_REASON_CODES)}")

    raw_evidence = entry.get("evidence") or []
    if not isinstance(raw_evidence, list):
        return failed("evidence is not a list")
    evidence: list[ExtractedEvidence] = []
    for item in raw_evidence:
        if not isinstance(item, dict):
            return failed(f"evidence entry is not an object: {item!r}")
        quote = item.get("quote")
        document_id = item.get("document_id")
        role = item.get("role", "supporting")
        if not isinstance(quote, str) or not quote.strip():
            return failed("evidence entry has no quote")
        if not isinstance(document_id, str) or not document_id:
            return failed("evidence entry has no document_id")
        if role not in VALID_ROLES:
            return failed(f"evidence role {role!r} is not supporting or contradicting")
        evidence.append(ExtractedEvidence(document_id, quote, role))

    # Spec Section 3: AMBIGUOUS must carry a visible reason. An unresolved row
    # with no reason code tells a reviewer nothing about what to do next.
    if status == ClinicalStatus.AMBIGUOUS.value and not raw_codes:
        return failed("AMBIGUOUS returned with no reason code")

    # "Not found" must not arrive as NOT_MET. The instruction says so and this
    # rejects it anyway, because an instruction is not an enforcement.
    if status == ClinicalStatus.NOT_MET.value and not evidence:
        return failed("NOT_MET returned with no evidence; absence is not contradiction")

    if ReasonCode.MISSING_EVIDENCE.value in raw_codes and evidence:
        return failed("MISSING_EVIDENCE returned alongside cited evidence")

    explanation = entry.get("explanation", "")
    if not isinstance(explanation, str):
        return failed("explanation is not a string")

    return CriterionExtraction(
        criterion_id=criterion_id,
        clinical_status=ClinicalStatus(status),
        processing_status=ProcessingStatus.COMPLETE,
        reason_codes=[ReasonCode(c) for c in raw_codes],
        evidence=evidence,
        explanation=explanation,
    )


# --------------------------------------------------------------------------
# The two configurations
# --------------------------------------------------------------------------

def _call_once(client: ModelClient, prompt: ExtractionPrompt, index: int,
               model: str, max_tokens: int, temperature: float,
               timeout: float) -> Attempt:
    """One call. An exception becomes a recorded attempt, not a raised error."""
    started = time.monotonic()
    try:
        response = client.complete(
            prompt.system, prompt.user, model=model, max_tokens=max_tokens,
            temperature=temperature, timeout=timeout)
    except Exception as exc:  # transport, timeout, rate limit, anything
        return Attempt(index=index, raw_text="",
                       seconds=time.monotonic() - started,
                       error=scrub_secrets(f"{type(exc).__name__}: {exc}"),
                       retryable=is_retryable(exc))
    attempt = Attempt(index=index, raw_text=scrub_secrets(response.text),
                      input_tokens=response.input_tokens,
                      output_tokens=response.output_tokens,
                      stop_reason=response.stop_reason,
                      seconds=time.monotonic() - started)
    if response.stop_reason == "max_tokens":
        # A configuration limit, not a model failure. Retrying sends the same
        # request and truncates at the same place, exactly as retrying a 400
        # did before it was classified. Say what happened and stop.
        attempt.parse_error = (
            f"response truncated at the {max_tokens} output-token limit "
            f"(stop_reason max_tokens); raise max_tokens rather than retrying")
        attempt.retryable = False
    return attempt


def _extract_for(client: ModelClient, prompt: ExtractionPrompt, run: ExtractionRun,
                 *, model: str, max_tokens: int, temperature: float,
                 timeout: float, max_attempts: int) -> list[CriterionExtraction]:
    """Run one call with retries, then validate. Every attempt is retained.

    A retry is for a call that failed or came back unreadable. A response that
    parsed is accepted even where its content is rejected per criterion,
    because retrying until the model says something acceptable would be
    selecting the answer.
    """
    run.prompts.append(prompt.as_log_dict())
    last_detail = "no attempt was made"

    for index in range(1, max_attempts + 1):
        attempt = _call_once(client, prompt, index, model, max_tokens,
                             temperature, timeout)
        run.attempts.append(attempt)
        if attempt.error:
            last_detail = attempt.error
            if not attempt.retryable:
                last_detail = (f"{attempt.error} — the server rejected the "
                               f"request itself, so it was not retried")
                break
            continue
        if not attempt.retryable:
            # Truncated at the output limit. Deterministic given this input.
            last_detail = attempt.parse_error
            break
        attempt.preamble = extract_json_text(attempt.raw_text)[1]
        try:
            entries = parse_response(attempt.raw_text, prompt.criterion_ids)
        except MalformedResponse as exc:
            attempt.parse_error = str(exc)
            last_detail = str(exc)
            continue

        results = [
            build_result(cid, entries[cid]) if cid in entries else
            CriterionExtraction(
                criterion_id=cid, clinical_status=None,
                processing_status=ProcessingStatus.FAILED,
                reason_codes=[ReasonCode.PROCESSING_ERROR],
                detail="the model returned no result for this criterion",
                failure_kind=FailureKind.NO_RESPONSE)
            for cid in prompt.criterion_ids
        ]
        return results

    # Every attempt failed. One explicit failure per criterion, no clinical
    # status. The count is what was actually spent, which is not max_attempts
    # when a non-retryable refusal stopped the loop early.
    made = sum(1 for a in run.attempts if a.index <= max_attempts)
    return [
        CriterionExtraction(
            criterion_id=cid, clinical_status=None,
            processing_status=ProcessingStatus.FAILED,
            reason_codes=[ReasonCode.PROCESSING_ERROR],
            detail=f"{made} attempt(s) failed; last: {last_detail}",
            failure_kind=FailureKind.NO_RESPONSE)
        for cid in prompt.criterion_ids
    ]


def extract(criteria_set: CriteriaSet, packet: IngestedPacket,
            client: ModelClient, *, configuration: str = "A",
            model: str = DEFAULT_MODEL, max_tokens: int = DEFAULT_MAX_TOKENS,
            temperature: float = DEFAULT_TEMPERATURE,
            timeout: float = DEFAULT_TIMEOUT_SECONDS,
            max_attempts: int = MAX_ATTEMPTS) -> ExtractionRun:
    """Step 3 in either configuration.

    "A" is one call for every criterion. "B" is one call per criterion. The
    prompt is built by the same function either way; only the list of criterion
    ids passed to it differs.

    A packet that failed ingestion is not sent. There is nothing to read, and
    asking the model to assess an unreadable record would produce clinical
    statuses derived from a processing failure, which Spec Section 3 forbids.
    """
    if configuration not in ("A", "B"):
        raise ValueError(f"configuration must be 'A' or 'B', got {configuration!r}")

    run = ExtractionRun(case_id=packet.case_id, configuration=configuration,
                        model=model, prompt_version=PROMPT_VERSION)
    started = time.monotonic()

    if packet.processing_status is ProcessingStatus.FAILED:
        run.results = [
            CriterionExtraction(
                criterion_id=cid, clinical_status=None,
                processing_status=ProcessingStatus.FAILED,
                reason_codes=[ReasonCode.PROCESSING_ERROR],
                detail="ingestion failed for this packet; no extraction was attempted",
                failure_kind=FailureKind.NOT_ATTEMPTED)
            for cid in criteria_set.criterion_ids
        ]
        run.seconds = time.monotonic() - started
        return run

    common = dict(model=model, max_tokens=max_tokens, temperature=temperature,
                  timeout=timeout, max_attempts=max_attempts)

    if configuration == "A":
        prompt = build_extraction_prompt(criteria_set, packet)
        run.results = _extract_for(client, prompt, run, **common)
    else:
        # Sequential. Spec Section 11 fixes this for the experiment, and the
        # cost comparison is only meaningful if B is not quietly parallelised.
        for criterion_id in criteria_set.criterion_ids:
            prompt = build_extraction_prompt(criteria_set, packet, (criterion_id,))
            run.results.extend(_extract_for(client, prompt, run, **common))

    run.seconds = time.monotonic() - started
    return run
