"""Task 2.4: score a verified run against the reference.

Implements the contract in `evals/decision_rules.md`, which was written before
any result existed and is not edited to fit one.

Three things this module refuses to do.

**It prints no rate for either critical error direction.** Both are counts with
the affected instances named. The larger direction has a computable
denominator and is still reported as counts, because a near-zero rate over a
large denominator reads as a safety claim and Spec Section 9 says explicitly
that zero observed failures in a small test is not proof of safety. The smaller
direction has six instances corpus-wide and two in held-out, so a rate would
move in fifty-point steps.

**Every figure carries the counts it came from.** A `Metric` is a numerator and
a denominator, and its string form is "4 of 45 (8.9%)". A percentage alone
hides that 8.9% here is four instances, which is the difference between a
finding and a coincidence.

**It never scores a NOT_APPLICABLE instance.** Six instances are waived by a
triggered exception pathway. They are out of scope for the request rather than
failed or unresolved, and Section 2 excludes them from every denominator.

Units and spans are many-to-many
--------------------------------
A unit is a fact the criterion requires. A span is a citation. One returned
span can recover several units at once — a review-of-systems block covers four
red flag categories in one quote — and one unit can be recovered by any of
several equivalent passages. Recall counts units recovered; precision counts
spans accepted. Neither is derivable from the other.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .results import ClinicalStatus, FailureKind, ProcessingStatus
from .spans import canonicalize
from .verify import VerificationRun, VerifiedCriterion

CRITICAL_REFERENCE = (ClinicalStatus.MET, ClinicalStatus.NOT_MET)


@dataclass(frozen=True)
class Metric:
    """A figure that cannot be printed without the counts behind it."""

    name: str
    numerator: int
    denominator: int

    @property
    def value(self) -> float | None:
        return self.numerator / self.denominator if self.denominator else None

    def __str__(self) -> str:
        if not self.denominator:
            return f"{self.name}: no instances"
        return (f"{self.name}: {self.numerator} of {self.denominator} "
                f"({self.value:.1%})")

    def as_dict(self) -> dict:
        return {"numerator": self.numerator, "denominator": self.denominator,
                "value": self.value}


@dataclass
class InstanceScore:
    """One criterion instance, scored."""

    case_id: str
    criterion_id: str
    split: str
    reference_status: str
    returned_status: str | None
    status_match: bool = False
    failure_kind: FailureKind = FailureKind.NONE
    units_required: int = 0
    units_recovered: int = 0
    spans_returned: int = 0
    spans_accepted: int = 0
    spans_verified: int = 0
    span_chars: int = 0
    unenumerated: list[str] = field(default_factory=list)

    @property
    def scorable_for_status(self) -> bool:
        """Contract rejections leave the status denominator, per Section 2."""
        return self.failure_kind is not FailureKind.CONTRACT_REJECTION

    @property
    def is_superset(self) -> bool:
        return self.spans_accepted > self.units_required

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id, "criterion_id": self.criterion_id,
            "split": self.split,
            "reference_status": self.reference_status,
            "returned_status": self.returned_status,
            "status_match": self.status_match,
            "failure_kind": self.failure_kind.value,
            "units": {"required": self.units_required,
                      "recovered": self.units_recovered},
            "spans": {"returned": self.spans_returned,
                      "accepted": self.spans_accepted,
                      "verified": self.spans_verified},
            "unenumerated_spans": self.unenumerated,
        }


# How much larger than the reference passage a returned span may be and still
# count as citing it. Without a cap, one span covering a whole document would
# overlap every reference span in it and score perfectly. The cap is a guard
# against that degenerate case rather than a quality bar, which is why it is
# generous; citation volume and span length are reported as diagnostics so
# verbosity is visible without being folded into precision.
MAX_SPAN_FACTOR = 4
MAX_SPAN_SLACK = 300

# Fraction of the shorter span that the overlap must cover. A model quoting
# more widely than the reference, or quoting the key phrase inside it, is
# citing the same passage either way.
MIN_OVERLAP = 0.5


def _overlaps(a: tuple[str, int, int], b: tuple[str, int, int]) -> bool:
    return a[0] == b[0] and a[1] < b[2] and b[1] < a[2]


def cites_same_passage(returned: tuple[str, int, int],
                       reference: tuple[str, int, int]) -> bool:
    """Whether a returned span cites the passage a reference span marks.

    Compared by position, not by string. An earlier version required the
    returned quote to equal the reference quote after canonicalization, and
    scored the first real run at 23% recall against 87% status agreement. The
    model was citing the right passages with different boundaries: it returned
    "PRIOR IMAGING: No prior lumbar imaging on file for this patient. No
    outside stud..." where the reference recorded "No prior lumbar imaging on
    file for this patient." The reference span sits wholly inside the returned
    one and scored zero.

    decision_rules.md Section 2 specified deduplication by overlapping ranges
    and never specified the acceptance rule, so exact equality was implemented
    by omission rather than chosen. The rule below fills that gap.
    """
    if not _overlaps(returned, reference):
        return False
    ref_len = reference[2] - reference[1]
    ret_len = returned[2] - returned[1]
    if ret_len > max(ref_len * MAX_SPAN_FACTOR, ref_len + MAX_SPAN_SLACK):
        return False
    overlap = min(returned[2], reference[2]) - max(returned[1], reference[1])
    shorter = min(ref_len, ret_len)
    return shorter > 0 and overlap / shorter >= MIN_OVERLAP


def _reference_spans(entries: list[dict]) -> list[tuple[str, int, int]]:
    return [(e["document_id"], e["start"], e["end"]) for e in entries]


def score_instance(result: VerifiedCriterion, expectation: dict,
                   case_id: str, split: str) -> InstanceScore:
    """Score one criterion against its reference acceptable set."""
    acceptable = expectation.get("acceptable_evidence") or {}
    units = acceptable.get("units", [])
    also = acceptable.get("also_acceptable", [])

    score = InstanceScore(
        case_id=case_id, criterion_id=result.criterion_id, split=split,
        reference_status=expectation["clinical_status"],
        returned_status=(result.clinical_status.value
                         if result.clinical_status else None),
        failure_kind=result.failure_kind,
        units_required=len(units),
    )
    score.status_match = (score.returned_status == score.reference_status)

    # Deduplicate returned spans by overlapping range within a document.
    # Section 2: identical text in different documents is distinct evidence,
    # because copy-forward makes it common and provenance differs.
    seen: list[tuple[str, int, int]] = []
    returned: list[tuple[tuple[str, int, int], object]] = []
    for item in result.evidence:
        if item.span is None:
            # Unverified: it has no location, so it cannot be deduplicated by
            # one. Counted once as returned and never as accepted.
            returned.append(((item.document_id, -1, -1), item))
            continue
        rng = (item.span.document_id, item.span.start, item.span.end)
        if any(_overlaps(rng, s) for s in seen):
            continue
        seen.append(rng)
        returned.append((rng, item))

    score.spans_returned = len(returned)
    score.spans_verified = sum(1 for _, item in returned if item.verified)

    located = [rng for rng, item in returned if item.verified and rng[1] >= 0]

    # A unit is recovered when any returned span cites one of its passages.
    for unit in units:
        targets = _reference_spans(unit.get("quotes", []))
        if any(cites_same_passage(r, t) for r in located for t in targets):
            score.units_recovered += 1

    acceptable = [t for unit in units
                  for t in _reference_spans(unit.get("quotes", []))]
    acceptable += _reference_spans(also)
    for rng, item in returned:
        if not item.verified or rng[1] < 0:
            continue
        if any(cites_same_passage(rng, t) for t in acceptable):
            score.spans_accepted += 1
            score.span_chars += rng[2] - rng[1]
        else:
            score.unenumerated.append(f"{item.document_id}: {item.quote[:80]}")
    return score


@dataclass
class RunScore:
    """Every metric for one configuration over one set of cases."""

    configuration: str
    split: str
    instances: list[InstanceScore] = field(default_factory=list)

    @property
    def scored(self) -> list[InstanceScore]:
        return [i for i in self.instances if i.scorable_for_status]

    # -- primary --------------------------------------------------------

    @property
    def evidence_recall(self) -> Metric:
        return Metric("evidence recall",
                      sum(i.units_recovered for i in self.instances),
                      sum(i.units_required for i in self.instances))

    @property
    def evidence_precision(self) -> Metric:
        return Metric("evidence precision",
                      sum(i.spans_accepted for i in self.instances),
                      sum(i.spans_returned for i in self.instances))

    @property
    def status_agreement(self) -> Metric:
        scored = self.scored
        return Metric("status agreement",
                      sum(1 for i in scored if i.status_match), len(scored))

    @property
    def complete_processing(self) -> Metric:
        return Metric("complete processing",
                      sum(1 for i in self.instances
                          if i.failure_kind is FailureKind.NONE),
                      len(self.instances))

    # -- critical errors: counts, never rates ----------------------------

    @property
    def met_or_ambiguous_output_not_met(self) -> list[InstanceScore]:
        return [i for i in self.scored
                if i.reference_status in ("MET", "AMBIGUOUS")
                and i.returned_status == "NOT_MET"]

    @property
    def not_met_output_met(self) -> list[InstanceScore]:
        return [i for i in self.scored
                if i.reference_status == "NOT_MET" and i.returned_status == "MET"]

    # -- reported apart from the primary set -----------------------------

    @property
    def contract_rejections(self) -> list[InstanceScore]:
        return [i for i in self.instances
                if i.failure_kind is FailureKind.CONTRACT_REJECTION]

    @property
    def citation_validity(self) -> Metric:
        return Metric("citation validity",
                      sum(i.spans_verified for i in self.instances),
                      sum(i.spans_returned for i in self.instances))

    @property
    def mean_spans(self) -> float | None:
        n = len(self.instances)
        return sum(i.spans_returned for i in self.instances) / n if n else None

    @property
    def mean_span_chars(self) -> float | None:
        """Reported so verbosity is visible without entering precision."""
        accepted = sum(i.spans_accepted for i in self.instances)
        return (sum(i.span_chars for i in self.instances) / accepted
                if accepted else None)

    @property
    def superset_rate(self) -> Metric:
        return Metric("superset rate",
                      sum(1 for i in self.instances if i.is_superset),
                      len(self.instances))

    @property
    def confusion(self) -> dict[str, dict[str, int]]:
        out: dict[str, Counter] = {}
        for i in self.scored:
            out.setdefault(i.reference_status, Counter())[
                i.returned_status or "none"] += 1
        return {k: dict(v) for k, v in out.items()}

    def as_dict(self) -> dict:
        return {
            "configuration": self.configuration,
            "split": self.split,
            "instances_scored": len(self.instances),
            "primary": {
                "evidence_recall": self.evidence_recall.as_dict(),
                "evidence_precision": self.evidence_precision.as_dict(),
                "status_agreement": self.status_agreement.as_dict(),
                "complete_processing": self.complete_processing.as_dict(),
            },
            "critical_errors": {
                "_note": ("Counts only. evals/decision_rules.md records why "
                          "neither direction is reportable as a rate at this "
                          "corpus size."),
                "reference_met_or_ambiguous_output_not_met": {
                    "count": len(self.met_or_ambiguous_output_not_met),
                    "instances": [f"{i.case_id} {i.criterion_id}"
                                  for i in self.met_or_ambiguous_output_not_met],
                },
                "reference_not_met_output_met": {
                    "count": len(self.not_met_output_met),
                    "instances": [f"{i.case_id} {i.criterion_id}"
                                  for i in self.not_met_output_met],
                },
            },
            "reported_separately": {
                "contract_rejections": {
                    "count": len(self.contract_rejections),
                    "instances": [f"{i.case_id} {i.criterion_id}"
                                  for i in self.contract_rejections],
                },
                "citation_validity": self.citation_validity.as_dict(),
                "mean_spans_per_instance": self.mean_spans,
                "mean_accepted_span_chars": self.mean_span_chars,
                "superset_rate": self.superset_rate.as_dict(),
            },
            "confusion": self.confusion,
            "instances": [i.as_dict() for i in self.instances],
        }


def score_run(verification: VerificationRun, labels: dict,
              run_score: RunScore | None = None) -> RunScore:
    """Fold one case's verified results into a RunScore."""
    case = next(c for c in labels["cases"] if c["case_id"] == verification.case_id)
    out = run_score or RunScore(configuration=verification.configuration,
                                split=case["split"])
    for result in verification.results:
        expectation = case["expected"].get(result.criterion_id)
        if not isinstance(expectation, dict):
            continue
        if expectation["clinical_status"] == "NOT_APPLICABLE":
            continue    # Section 2: excluded from every denominator.
        out.instances.append(
            score_instance(result, expectation, case["case_id"], case["split"]))
    return out


def format_report(score: RunScore, independent_cases: int | None = None) -> str:
    """A report where no figure appears without its denominator."""
    lines = [
        f"Configuration {score.configuration} · {score.split} · "
        f"{len(score.instances)} scorable criterion instances",
        "",
        "PRIMARY",
        f"  {score.evidence_recall}",
        f"  {score.evidence_precision}",
        f"  {score.status_agreement}",
        f"  {score.complete_processing}",
        "",
        "CRITICAL ERRORS  (counts only; see evals/decision_rules.md)",
    ]
    for label, group in (
        ("reference MET or AMBIGUOUS returned as NOT_MET",
         score.met_or_ambiguous_output_not_met),
        ("reference NOT_MET returned as MET", score.not_met_output_met),
    ):
        lines.append(f"  {label}: {len(group)}")
        for i in group:
            lines.append(f"      {i.case_id} {i.criterion_id} "
                         f"(reference {i.reference_status})")

    lines += ["", "REPORTED SEPARATELY",
              f"  contract rejections: {len(score.contract_rejections)}"]
    for i in score.contract_rejections:
        lines.append(f"      {i.case_id} {i.criterion_id}")
    lines += [f"  {score.citation_validity}",
              f"  mean returned spans per instance: "
              f"{score.mean_spans:.2f}" if score.mean_spans is not None
              else "  mean returned spans per instance: none",
              f"  {score.superset_rate}"]
    if score.mean_span_chars is not None:
        lines.append(f"  mean accepted span length: "
                     f"{score.mean_span_chars:.0f} characters")

    lines += ["", "CONFUSION  (reference down, returned across)"]
    for reference, row in sorted(score.confusion.items()):
        total = sum(row.values())
        cells = ", ".join(f"{k} {v}" for k, v in sorted(row.items()))
        lines.append(f"  {reference:16} n={total:<4} {cells}")

    cases = sorted({i.case_id for i in score.instances})
    lines += ["", f"CASES  {len(cases)}"
              + (f", {independent_cases} independent"
                 if independent_cases is not None else "")]
    lines.append("  " + ", ".join(cases))
    return "\n".join(lines)


def load_labels(path: Path | str | None = None) -> dict:
    path = Path(path) if path else (
        Path(__file__).resolve().parents[1] / "corpus" / "labels.json")
    return json.loads(path.read_text(encoding="utf-8"))
