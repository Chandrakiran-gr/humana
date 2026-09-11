"""Live execution for the demonstration, with visible progress.

A recorded run appears instantly and tells a viewer nothing about how it was
produced. A live run takes half a minute, and if that half minute is a blank
screen it looks like a page reload rather than fourteen — or, under the
adopted configuration, eight — model calls. This module runs the pipeline and
reports where it is while it is still going.

**The extraction display is honest about Baseline A.** A is one call for every
criterion. Rows therefore do not fill in one at a time during extraction,
because there is no per-criterion extraction call to return: every criterion
arrives in a single response. All rows sit on `reading the record` together
and resolve together. That shared wait is the visible signature of the adopted
configuration and is exactly what distinguishes it from Candidate B on screen.
Revealing rows one at a time on a timer would animate a call structure the
system does not have, and the evaluation rejected the structure that would
have justified the animation.

Verification is genuinely per criterion, so from Step 4 onward rows do stream:
quote check, then support check, then done, one criterion at a time.

**Every failure is a processing state.** Truncation, a rejected request,
exhausted credit, an unreachable network and an unexpected exception all
resolve to `processing_status: FAILED` with no clinical status. This module
adds no failure handling of its own for anything reachable through `extract`;
it routes into the existing classification in `extract.py` so the demo path
and the evaluation path fail the same way. The only handling added here is a
last-resort guard for exceptions raised outside a model call, which produces
the same shape rather than a different one.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .criteria import CriteriaSet
from .extract import (
    DEFAULT_MAX_TOKENS, DEFAULT_MODEL, ModelClient, extract, scrub_secrets,
)
from .ingest import IngestedPacket
from .results import FailureKind, ProcessingStatus, ReasonCode
from .verify import (
    STAGE_DONE, STAGE_QUOTE_CHECK, STAGE_SUPPORT_CHECK, verify_run,
)

# Live artifacts are written here and never to `runs/`. The evaluation harness
# and the interface's recorded-run picker both read `runs/*.json`, which is a
# non-recursive glob, so a demonstration cannot put a file where a scored run
# is looked for. `tests/test_live.py` asserts that rather than trusting it.
LIVE_RUNS = Path(__file__).resolve().parents[1] / "runs" / "live"

STAGE_PENDING = "pending"
STAGE_READING = "reading the record"
STAGE_FAILED = "failed"

# The order a viewer sees. Used by the interface to draw a row's position.
STAGES = (STAGE_PENDING, STAGE_READING, STAGE_QUOTE_CHECK,
          STAGE_SUPPORT_CHECK, STAGE_DONE)


def failed_results(criterion_ids, detail: str,
                   kind: FailureKind = FailureKind.NOT_ATTEMPTED) -> list[dict]:
    """One explicit processing failure per criterion. Never a clinical status.

    Used only where the failure happened outside a model call, so `extract`
    never saw it and could not classify it. The shape matches what `extract`
    produces for the same situation, so the interface has one thing to render
    rather than two.
    """
    return [
        {
            "criterion_id": cid,
            "clinical_status": None,
            "processing_status": ProcessingStatus.FAILED.value,
            "reason_codes": [ReasonCode.PROCESSING_ERROR.value],
            "detail": scrub_secrets(detail),
            "failure_kind": kind.value,
            "evidence": [],
            "explanation": "",
        }
        for cid in criterion_ids
    ]


def run_live(case_id: str, criteria_set: CriteriaSet, packet: IngestedPacket,
             client: ModelClient, *, model: str = DEFAULT_MODEL,
             max_tokens: int = DEFAULT_MAX_TOKENS, on_progress=None,
             write_dir: Path | None = LIVE_RUNS) -> dict:
    """Run the pipeline live, reporting progress, and return the payload.

    `on_progress(criterion_ids, stage, result)` is called with a tuple of the
    criteria entering a stage. Extraction reports every criterion at once
    because that is what one call does; verification reports one at a time.
    """
    ids = list(criteria_set.criterion_ids)

    def report(criterion_ids, stage, result=None):
        if on_progress is not None:
            on_progress(tuple(criterion_ids), stage, result)

    started = datetime.now(timezone.utc)
    report(ids, STAGE_PENDING)

    try:
        # One call, all criteria. Every row waits on this together.
        report(ids, STAGE_READING)
        run = extract(criteria_set, packet, client, configuration="A",
                      model=model, max_tokens=max_tokens)

        verified = verify_run(
            run, packet, criteria_set, client,
            on_progress=lambda cid, stage, result: report((cid,), stage, result))
        extraction_payload = run.as_dict()
        verification_payload = verified.as_dict()
    except Exception as exc:
        # Reached only for a failure outside a model call: `extract` turns
        # transport, timeout, rate limit and refusal into recorded attempts
        # rather than raising. Anything arriving here is unexpected, which is
        # the case where rendering a clinical result would be worst.
        detail = scrub_secrets(f"{type(exc).__name__}: {exc}")
        extraction_payload = {
            "case_id": case_id, "configuration": "A", "model": model,
            "processing_status": ProcessingStatus.FAILED.value,
            "results": failed_results(ids, detail, FailureKind.NOT_ATTEMPTED),
        }
        verification_payload = {
            "case_id": case_id, "configuration": "A",
            "results": failed_results(ids, detail, FailureKind.NOT_ATTEMPTED),
        }
        for cid in ids:
            report((cid,), STAGE_FAILED)

    payload = {
        "generated": started.strftime("%Y%m%dT%H%M%SZ"),
        "mode": "live",
        "cases": [{
            "case_id": case_id,
            "extraction": extraction_payload,
            "verification": verification_payload,
        }],
    }

    if write_dir is not None:
        write_dir.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, default=str)
        # Defence in depth. `extract` scrubs attempt text and errors already;
        # this catches anything that reached the payload by another route.
        # Spec Section 11: no key in a saved artifact.
        path = write_dir / f"{payload['generated']}_live_{case_id}.json"
        path.write_text(scrub_secrets(text), encoding="utf-8")
        payload["artifact"] = str(path)

    return payload
