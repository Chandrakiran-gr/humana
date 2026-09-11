"""Result and status types shared across the six pipeline steps.

The central constraint of this system is in Spec Section 3: clinical status and
processing status are independent, and a system failure must never surface as a
clinical finding. That is enforced here structurally rather than by convention,
because a convention is a thing people follow until they are busy.

`ProcessingStatus` and `ClinicalStatus` are separate enumerations with no
conversion between them. There is deliberately no function anywhere in this
package that takes a processing failure and returns a clinical status.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ProcessingStatus(str, Enum):
    """Whether the pipeline was able to do its work. Never a clinical finding."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ClinicalStatus(str, Enum):
    """What the located evidence supports. Only ever set by Steps 3 and 5."""

    MET = "MET"
    NOT_MET = "NOT_MET"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ReasonCode(str, Enum):
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    VAGUE_DURATION = "VAGUE_DURATION"
    UNVERIFIABLE_QUOTE = "UNVERIFIABLE_QUOTE"
    UNSUPPORTED_CONCLUSION = "UNSUPPORTED_CONCLUSION"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"
    PROCESSING_ERROR = "PROCESSING_ERROR"


class FailureKind(str, Enum):
    """Why a criterion produced no clinical status.

    Every value here is a processing failure and none is a clinical finding.
    They are distinguished because pooling them misstates what went wrong.

    A CONTRACT_REJECTION is a case where the model reached a conclusion and the
    output contract refused its shape. On TKA-004 C7 the model returned the
    reference status and the reference reason code, then cited passages
    alongside MISSING_EVIDENCE, and the result was rejected. Counting that as a
    status error would say the system read the record wrongly, which it did
    not. Counting it as correct would ignore that the row could not be shown to
    a reviewer. It is neither, so it is reported on its own.
    """

    NONE = "NONE"
    CONTRACT_REJECTION = "CONTRACT_REJECTION"
    NO_RESPONSE = "NO_RESPONSE"
    NOT_ATTEMPTED = "NOT_ATTEMPTED"


class DocumentOutcome(str, Enum):
    """Per-document ingestion outcome. Step 2 only.

    Every one of these except OK means the document contributes no citable text.
    They are distinguished rather than collapsed because a reviewer needs to know
    whether a document was unreadable, empty, or a scan, and because the
    demonstration in Spec Section 13 requires a processing failure to be visible
    as a specific state rather than a generic error.
    """

    OK = "OK"
    EMPTY = "EMPTY"
    NO_TEXT_LAYER = "NO_TEXT_LAYER"
    UNSUPPORTED_TYPE = "UNSUPPORTED_TYPE"
    UNREADABLE = "UNREADABLE"
    INPUT_LIMIT_EXCEEDED = "INPUT_LIMIT_EXCEEDED"

    @property
    def is_usable(self) -> bool:
        return self is DocumentOutcome.OK


@dataclass(frozen=True)
class Span:
    """A half-open character range into a document's canonical text.

    See docs/SPAN_REPRESENTATION.md for why this shape and not another. The
    document hash travels with the span so that a citation stored today can be
    shown to refer to the bytes that were actually read, rather than to whatever
    the file contains when someone opens it later.
    """

    document_id: str
    content_sha256: str
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError(f"invalid span [{self.start}, {self.end})")

    @property
    def length(self) -> int:
        return self.end - self.start

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "content_sha256": self.content_sha256,
            "start": self.start,
            "end": self.end,
        }


@dataclass
class StepResult:
    """Outcome of one deterministic pipeline step.

    Carries a processing status and never a clinical one. Steps 1, 2, 4 and 6
    return this. Steps 3 and 5 return criterion results, which carry a clinical
    status, and can only be reached from a StepResult that did not fail.
    """

    step: str
    processing_status: ProcessingStatus
    detail: str = ""
    reason_codes: list[ReasonCode] = field(default_factory=list)
    payload: object | None = None

    @property
    def ok(self) -> bool:
        return self.processing_status is ProcessingStatus.COMPLETE

    @property
    def can_continue(self) -> bool:
        """A partial result may proceed; a failed one may not.

        Spec Section 3: a case whose documents could not be read is not
        presented as a completed evidence review. Partial processing is
        reportable with its state visible; failure stops the pipeline.
        """
        return self.processing_status is not ProcessingStatus.FAILED

    def as_dict(self) -> dict:
        return {
            "step": self.step,
            "processing_status": self.processing_status.value,
            "detail": self.detail,
            "reason_codes": [r.value for r in self.reason_codes],
        }
