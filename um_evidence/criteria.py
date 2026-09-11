"""Step 1: load a versioned criteria set by procedure code.

Deterministic. No model call, no network, no inference about which policy
applies. Spec Section 5 is explicit that there is no automated policy extraction
and no real policy applicability resolution here: the procedure code selects a
set from a file, and an unrecognised code is an explicit unsupported-case result
rather than a best guess.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .results import ProcessingStatus, StepResult

DEFAULT_CRITERIA_PATH = Path(__file__).resolve().parents[1] / "criteria" / "criteria_sets.json"


@dataclass(frozen=True)
class Criterion:
    id: str
    text: str
    evidence_type: str
    difficulty: str
    satisfied_by: str
    evidence_requirement: str
    trap_note: str = ""

    def as_prompt_block(self) -> str:
        """The criterion as it is presented to the model at Step 3.

        Everything here reaches the model. criteria_sets.json carries an
        audience_warning about that, and scripts/check_criteria_contamination.py
        enforces that the rule prose contains no wording quoted from a packet.
        """
        parts = [f"{self.id}. {self.text}", f"Satisfied by: {self.satisfied_by}"]
        if self.trap_note:
            parts.append(f"Note: {self.trap_note}")
        return "\n".join(parts)


@dataclass(frozen=True)
class CriteriaSet:
    procedure_id: str
    procedure_name: str
    cpt: str
    version: str
    has_exception_pathway: bool
    exception_note: str
    criteria: tuple[Criterion, ...]
    rules: dict

    def __getitem__(self, criterion_id: str) -> Criterion:
        for c in self.criteria:
            if c.id == criterion_id:
                return c
        raise KeyError(criterion_id)

    @property
    def criterion_ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.criteria)


class UnsupportedProcedure(LookupError):
    """Raised for a procedure code with no criteria set.

    Spec Section 3: no valid criteria match means stop with an explicit
    unsupported-case message. Do not guess.
    """


@lru_cache(maxsize=None)
def _load_file(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _build(raw_set: dict, meta: dict) -> CriteriaSet:
    return CriteriaSet(
        procedure_id=raw_set["procedure_id"],
        procedure_name=raw_set["procedure_name"],
        cpt=raw_set["cpt"],
        version=raw_set["criteria_set_version"],
        has_exception_pathway=bool(raw_set.get("has_exception_pathway")),
        exception_note=raw_set.get("exception_note", ""),
        criteria=tuple(
            Criterion(
                id=c["id"], text=c["text"], evidence_type=c["evidence_type"],
                difficulty=c["difficulty"], satisfied_by=c["satisfied_by"],
                evidence_requirement=c["evidence_requirement"],
                trap_note=c.get("trap_note", ""),
            )
            for c in raw_set["criteria"]
        ),
        # The rule prose travels with the set because Steps 3 and 5 send it to
        # the model and every run log records which version was in effect.
        rules={k: meta[k] for k in
               ("not_met_bar", "addresses_rule", "waiver_rule",
                "evidence_requirement_note", "audience_warning")
               if k in meta},
    )


def load_criteria(procedure_id: str, path: Path | str = DEFAULT_CRITERIA_PATH) -> CriteriaSet:
    """Look up a criteria set by procedure id. Raises UnsupportedProcedure."""
    payload = _load_file(str(path))
    for raw_set in payload["criteria_sets"]:
        if raw_set["procedure_id"] == procedure_id:
            return _build(raw_set, payload["_meta"])
    raise UnsupportedProcedure(
        f"No criteria set for procedure {procedure_id!r}. "
        f"Supported: {', '.join(s['procedure_id'] for s in payload['criteria_sets'])}. "
        f"This is an unsupported case and must be reported as such, not approximated "
        f"with a different set.")


def load_criteria_by_cpt(cpt: str, path: Path | str = DEFAULT_CRITERIA_PATH) -> CriteriaSet:
    payload = _load_file(str(path))
    for raw_set in payload["criteria_sets"]:
        if raw_set["cpt"] == cpt:
            return _build(raw_set, payload["_meta"])
    raise UnsupportedProcedure(
        f"No criteria set for CPT {cpt!r}. "
        f"Supported: {', '.join(s['cpt'] for s in payload['criteria_sets'])}.")


def load_step(procedure_id: str, path: Path | str = DEFAULT_CRITERIA_PATH) -> StepResult:
    """Step 1 as a pipeline step, so an unsupported code is a status not a crash."""
    try:
        criteria_set = load_criteria(procedure_id, path)
    except UnsupportedProcedure as exc:
        return StepResult(step="1_load_criteria",
                          processing_status=ProcessingStatus.FAILED,
                          detail=str(exc))
    return StepResult(
        step="1_load_criteria",
        processing_status=ProcessingStatus.COMPLETE,
        detail=(f"{criteria_set.procedure_id} v{criteria_set.version}, "
                f"{len(criteria_set.criteria)} criteria"),
        payload=criteria_set,
    )
