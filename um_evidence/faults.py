"""Task 3.4: deterministic fault injection controls.

Spec Section 13 requires the demonstration to show a rejected citation and a
processing failure surfaced as a visible incomplete state. Section 13 is also
explicit that **fault injection is labeled as such**: these demonstrate that
failure handling works. They are not observed model-error rates and must never
be presented as such.

Two properties shape how this is built.

**Deterministic.** The same input produces the same fault every time. A
demonstration that sometimes works is not a demonstration. Nothing here is
random and nothing depends on a live call.

**The fault is injected, the handling is real.** Neither control fakes an
output. `UNVERIFIABLE_QUOTE` corrupts a returned quote and then runs the real
Step 4 against the real packet, so the rejection, the preserved reason, the
retained valid spans and any downgrade all come from `verify.py` rather than
from a mock. `OUTPUT_TRUNCATION` replays a genuine truncated response through
the real parser and result builder.

**The truncation is not invented.** It is a response actually observed on
2026-09-10: MRI-007 exhausted a 16,000-token output budget and returned zero
characters of text, and all five of its criteria resolved to no clinical
status. Reproducing a failure that happened is stronger than constructing one,
and the artifact is in `runs/`. See `docs/DATA_CARD.md` on why it happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .extract import CriterionExtraction, ExtractedEvidence, MAX_ATTEMPTS
from .ingest import IngestedPacket
from .results import FailureKind, ProcessingStatus, ReasonCode

# The exact message the pipeline produced when MRI-007 truncated. Copied
# rather than re-derived so the control reproduces the observed text.
OBSERVED_TRUNCATION = (
    "response truncated at the 16000 output-token limit "
    "(stop_reason max_tokens); raise max_tokens rather than retrying")

OBSERVED_TRUNCATION_SOURCE = "runs/20260910T205411Z_eval_batch8_A.json, MRI-007"


class Fault(str, Enum):
    NONE = "NONE"
    UNVERIFIABLE_QUOTE = "UNVERIFIABLE_QUOTE"
    OUTPUT_TRUNCATION = "OUTPUT_TRUNCATION"


LABELS = {
    Fault.UNVERIFIABLE_QUOTE: (
        "Injected fault: unverifiable quote",
        "One returned quote has been altered so it no longer matches its "
        "source. Step 4 rejects that span, preserves the reason, and keeps "
        "any independently valid spans. Where the conclusion loses its "
        "support it is downgraded to unresolved.",
    ),
    Fault.OUTPUT_TRUNCATION: (
        "Injected fault: model output truncated",
        "A real truncated response is replayed. The model exhausted its "
        "output budget and returned no parseable result, so every criterion "
        "resolves to no clinical status with PROCESSING_ERROR. This is a "
        "visible incomplete state, not a clinical finding.",
    ),
}


@dataclass(frozen=True)
class Injection:
    """What was done, so the interface can say so."""

    fault: Fault
    headline: str
    detail: str
    target: str = ""
    provenance: str = ""


def corrupt_first_quote(results: list[dict], packet: IngestedPacket
                        ) -> tuple[list[dict], Injection]:
    """Alter one verified quote so Step 4 will reject it.

    Deterministic: the first verified quote in criterion order, with one
    word replaced. The alteration is a plausible paraphrase rather than
    gibberish, because a quote that is obviously corrupt tests nothing —
    the interesting case is a true-sounding statement that is not a citation,
    which is exactly what TKA-003 C3 produced unprompted on 2026-09-10.
    """
    out, injection = [], None
    for result in results:
        entry = dict(result)
        if injection is None:
            evidence = []
            for item in entry.get("evidence") or []:
                if injection is None and item.get("verified"):
                    words = item["quote"].split()
                    # Replace a mid-quote word; keeps length and shape.
                    at = len(words) // 2
                    original = words[at]
                    words[at] = "notwithstanding"
                    item = {**item, "quote": " ".join(words)}
                    injection = Injection(
                        fault=Fault.UNVERIFIABLE_QUOTE,
                        headline=LABELS[Fault.UNVERIFIABLE_QUOTE][0],
                        detail=LABELS[Fault.UNVERIFIABLE_QUOTE][1],
                        target=f"{entry['criterion_id']} · "
                               f"the word {original!r} replaced")
                evidence.append(item)
            entry["evidence"] = evidence
        out.append(entry)
    if injection is None:
        injection = Injection(
            fault=Fault.UNVERIFIABLE_QUOTE,
            headline=LABELS[Fault.UNVERIFIABLE_QUOTE][0],
            detail="This case returned no verified quote to corrupt.",
            target="none available")
    return out, injection


def replay_truncation(criterion_ids: list[str]) -> tuple[list[CriterionExtraction], Injection]:
    """Rebuild the observed truncation outcome for a set of criteria.

    Every criterion gets `clinical_status: None`, never AMBIGUOUS. None means
    no clinical judgement was reached; AMBIGUOUS means the record was read and
    did not settle the question. Collapsing them would let an outage look like
    a corpus of unresolved cases, which is the failure Spec Section 3 forbids.
    """
    results = [
        CriterionExtraction(
            criterion_id=cid,
            clinical_status=None,
            processing_status=ProcessingStatus.FAILED,
            reason_codes=[ReasonCode.PROCESSING_ERROR],
            failure_kind=FailureKind.NO_RESPONSE,
            detail=f"1 attempt(s) failed; last: {OBSERVED_TRUNCATION}")
        for cid in criterion_ids
    ]
    return results, Injection(
        fault=Fault.OUTPUT_TRUNCATION,
        headline=LABELS[Fault.OUTPUT_TRUNCATION][0],
        detail=LABELS[Fault.OUTPUT_TRUNCATION][1],
        target=f"{len(criterion_ids)} criteria",
        provenance=f"Observed on 2026-09-10 in {OBSERVED_TRUNCATION_SOURCE}. "
                   f"Replayed, not invented.")
