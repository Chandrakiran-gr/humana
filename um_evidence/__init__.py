"""UM evidence map: clinical evidence mapping for utilization management review.

Six steps. Steps 3 and 5 call the model; 1, 2, 4 and 6 are deterministic.
This package currently implements Steps 1 and 2.

The system produces no coverage determination, recommendation, or aggregate
score. Its output vocabulary is evidence status only.

Clinical status and processing status are separate throughout, and there is no
function in this package that converts one into the other.
"""

from .criteria import (
    CriteriaSet,
    Criterion,
    UnsupportedProcedure,
    load_criteria,
    load_criteria_by_cpt,
    load_step,
)
from .extract import (
    AnthropicClient,
    Attempt,
    CriterionExtraction,
    ExtractedEvidence,
    ExtractionRun,
    MalformedResponse,
    ModelClient,
    ModelResponse,
    build_result,
    extract,
    parse_response,
    scrub_secrets,
)
from .ingest import (
    IngestedDocument,
    IngestedPacket,
    document_id_for,
    estimate_tokens,
    ingest_case,
    ingest_document,
    ingest_step,
)
from .prompts import (
    EXTRACTION_SYSTEM,
    EXTRACTOR_REASON_CODES,
    PROMPT_VERSION,
    ExtractionPrompt,
    build_extraction_prompt,
)
from .preflight import (
    Preflight,
    PreflightError,
    declared_criteria_version,
    preflight,
)
from .score import (
    InstanceScore,
    Metric,
    RunScore,
    format_report,
    load_labels,
    score_instance,
    score_run,
)
from .verify import (
    VerificationRun,
    VerifiedCriterion,
    VerifiedEvidence,
    build_support_prompt,
    needs_support_check,
    parse_support,
    verify_quotes,
    verify_run,
    STAGE_QUOTE_CHECK,
    STAGE_SUPPORT_CHECK,
    STAGE_DONE,
    verify_support,
)
from .results import (
    ClinicalStatus,
    DocumentOutcome,
    FailureKind,
    ProcessingStatus,
    ReasonCode,
    Span,
    StepResult,
)
from .spans import CanonicalText, canonicalize

__all__ = [
    "EXTRACTION_SYSTEM", "EXTRACTOR_REASON_CODES", "PROMPT_VERSION",
    "AnthropicClient", "Attempt", "CanonicalText", "ClinicalStatus",
    "CriteriaSet", "Criterion", "CriterionExtraction", "DocumentOutcome",
    "ExtractedEvidence", "ExtractionPrompt", "ExtractionRun",
    "IngestedDocument", "IngestedPacket", "MalformedResponse", "ModelClient",
    "ModelResponse", "Preflight", "PreflightError", "ProcessingStatus",
    "ReasonCode", "Span", "StepResult", "UnsupportedProcedure",
    "build_extraction_prompt", "build_result", "canonicalize",
    "declared_criteria_version", "document_id_for", "estimate_tokens",
    "extract", "ingest_case", "ingest_document", "ingest_step",
    "load_criteria", "load_criteria_by_cpt", "load_step", "parse_response",
    "preflight", "scrub_secrets", "FailureKind", "VerificationRun",
    "VerifiedCriterion", "VerifiedEvidence", "build_support_prompt",
    "needs_support_check", "parse_support", "verify_quotes", "verify_run",
    "STAGE_QUOTE_CHECK", "STAGE_SUPPORT_CHECK", "STAGE_DONE",
    "verify_support", "InstanceScore", "Metric", "RunScore", "format_report",
    "load_labels", "score_instance", "score_run",
]
