"""The reviewer correction store.

The system produces no coverage determination. It surfaces evidence and a
person decides. This is where that decision is recorded, and it exists because
without it the claim is asserted and never demonstrated: a read-only evidence
map shows the system's half of the workflow and leaves the reviewer's half as
a description of something nobody can see.

Three properties, each enforced structurally rather than by convention.

**Append-only.** Corrections are written to a JSON Lines file, one record per
line, never rewritten. A reviewer who changes their mind adds a record; the
earlier one stays. Nothing here overwrites model output, and nothing here
overwrites a reference label.

**Separate from both.** Model output lives in `runs/`. Reference labels live
in `corpus/labels.json`. Corrections live in `corrections/` and no code path
writes from one into another. A correction names the run and criterion it
concerns and copies what the system said, so the record is readable on its own
without mutating the thing it refers to.

**Invisible to the scorer.** `um_evidence/score.py` does not import this
module and must not. A reviewer disagreeing with a result is not evidence about
whether the result matched the reference, and letting corrections reach the
scorer would let the evaluation be tuned by the people reading it.
`tests/test_corrections.py` asserts the isolation and a mutation confirms the
test can fail.

Corrections are also not reference labels. A reviewer saying a row is wrong is
one clinician's judgement recorded at a terminal, not an adjudication made
against the criteria before any document existed. Promoting corrections into
`corpus/labels.json` would destroy the property that makes the labels worth
anything, and there is deliberately no function here that does it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

CORRECTIONS_DIR = Path(__file__).resolve().parents[1] / "corrections"
CORRECTIONS_FILE = CORRECTIONS_DIR / "corrections.jsonl"

# What a reviewer can say about a row. Deliberately not a status vocabulary:
# a reviewer is not entering a clinical determination into the system, they
# are flagging that the row as presented is not usable and saying why.
DISAGREEMENT_KINDS = (
    "status_wrong",          # the clinical result does not match the record
    "evidence_wrong",        # a cited passage does not support the row
    "evidence_missing",      # the record contains support that was not found
    "citation_unusable",     # the citation does not resolve to a readable place
    "other",
)


@dataclass(frozen=True)
class Correction:
    """One reviewer disagreement with one row of one run."""

    recorded_at: str
    run_artifact: str
    case_id: str
    criterion_id: str
    kind: str
    reason: str
    reviewer: str = ""
    # What the system said, copied at the time of the correction so the record
    # stands alone. This is a snapshot, never a pointer that could go stale.
    system_clinical_status: str | None = None
    system_processing_status: str | None = None
    system_reason_codes: list[str] = field(default_factory=list)
    system_evidence_count: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


def record(run_artifact: str, case_id: str, criterion_id: str, kind: str,
           reason: str, reviewer: str = "", result: dict | None = None,
           path: Path | None = None) -> Correction:
    """Append one correction. Never modifies anything that already exists."""
    if kind not in DISAGREEMENT_KINDS:
        raise ValueError(f"kind must be one of {list(DISAGREEMENT_KINDS)}")
    if not reason.strip():
        raise ValueError("a correction requires a reason; a bare disagreement "
                         "is not reviewable by anyone else")

    result = result or {}
    correction = Correction(
        recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        run_artifact=run_artifact, case_id=case_id, criterion_id=criterion_id,
        kind=kind, reason=reason.strip(), reviewer=reviewer.strip(),
        system_clinical_status=result.get("clinical_status"),
        system_processing_status=result.get("processing_status"),
        system_reason_codes=list(result.get("reason_codes") or []),
        system_evidence_count=len(result.get("evidence") or []),
    )
    target = path or CORRECTIONS_FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(correction.as_dict(), ensure_ascii=False) + "\n")
    return correction


def load(path: Path | None = None) -> list[Correction]:
    """Every correction ever recorded, in the order recorded."""
    target = path or CORRECTIONS_FILE
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(Correction(**json.loads(line)))
    return out


def for_run(run_artifact: str, path: Path | None = None) -> dict[tuple[str, str], list[Correction]]:
    """Corrections on one run, keyed by case and criterion."""
    out: dict[tuple[str, str], list[Correction]] = {}
    for c in load(path):
        if c.run_artifact == run_artifact:
            out.setdefault((c.case_id, c.criterion_id), []).append(c)
    return out


def summary(path: Path | None = None) -> dict:
    from collections import Counter
    items = load(path)
    return {
        "total": len(items),
        "by_kind": dict(Counter(c.kind for c in items)),
        "cases": sorted({c.case_id for c in items}),
    }
