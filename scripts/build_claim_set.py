#!/usr/bin/env python3
"""Build the claim-verification set. Task 2.5.

Origins 2 and 3 only — nine of sixteen bundles. Both draw on corpus material
rather than run output, so neither depends on which extraction version ran.
Origin 1's seven are drawn separately, from the scored run the verifier will
actually be paired with.

Design and pre-registration: evals/claim_verification_design.md.

Every quote is resolved against the packet as it is written, so a bundle
cannot cite something Step 4 would reject. The reference may not offer the
verifier evidence the pipeline would refuse.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import ingest_case, load_criteria  # noqa: E402

CASES = PROJECT_ROOT / "corpus" / "cases"
LABELS = json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())
OUT = PROJECT_ROOT / "evals" / "claim_verification_set.json"

_packets: dict = {}


def packet(case_id):
    if case_id not in _packets:
        _packets[case_id] = ingest_case(case_id, CASES)
    return _packets[case_id]


def case(case_id):
    return next(c for c in LABELS["cases"] if c["case_id"] == case_id)


def cite(case_id: str, quote: str, role: str = "supporting") -> dict:
    spans = packet(case_id).locate(quote)
    if len(spans) != 1:
        raise ValueError(f"{case_id}: quote resolves to {len(spans)} spans: {quote[:60]!r}")
    span = spans[0]
    doc = packet(case_id).by_id(span.document_id)
    return {"document_id": span.document_id, "filename": doc.filename,
            "quote": quote, "start": span.start, "end": span.end, "role": role}


def bundle(bid, origin, category, case_id, criterion_id, proposed_status,
           evidence, expected, why, provenance) -> dict:
    cs = load_criteria(case(case_id)["procedure_id"])
    return {
        "id": bid,
        "origin": origin,
        "authored": origin == 4,
        "category": category,
        "case_id": case_id,
        "criterion_id": criterion_id,
        "criterion_text": cs[criterion_id].text,
        "satisfied_by": cs[criterion_id].satisfied_by,
        "proposed_status": proposed_status,
        "evidence": evidence,
        "expected_verdict": expected,
        "why": why,
        "provenance": provenance,
    }


# ---------------------------------------------------------------------------
# Origin 3: ruled_out entries from Task 2.3b enumeration.
#
# Selected by a rule fixed before the entries were read: development split,
# corpus order, one per case, first entry whose quote resolves to a single
# span. Each was adjudicated during enumeration, weeks before Step 5 existed,
# with the reason written down and no verifier in view. Nothing here is mine
# to tune.
#
# Each is presented as a MET claim resting on that passage alone. The correct
# verdict is UNSUPPORTED in all six, and the reason is the enumeration
# adjudication, quoted rather than restated.
# ---------------------------------------------------------------------------

def origin_three() -> list[dict]:
    out, seen = [], set()
    for c in LABELS["cases"]:
        if c["split"] != "development" or c["case_id"] in seen:
            continue
        for criterion_id, e in c["expected"].items():
            if not isinstance(e, dict) or e["clinical_status"] == "NOT_APPLICABLE":
                continue
            for ruled in (e.get("acceptable_evidence") or {}).get("ruled_out", []):
                if len(packet(c["case_id"]).locate(ruled["quote"])) != 1:
                    continue
                out.append(bundle(
                    f"CV-3-{len(out) + 1:02d}", 3, "real but irrelevant quote",
                    c["case_id"], criterion_id, "MET",
                    [cite(c["case_id"], ruled["quote"])],
                    "UNSUPPORTED",
                    ruled["why"],
                    "Task 2.3b enumeration ruled_out entry. Adjudicated before "
                    "Step 5 existed; selected by a fixed rule, not chosen."))
                seen.add(c["case_id"])
                break
            if c["case_id"] in seen:
                break
        if len(out) == 6:
            break
    return out


# ---------------------------------------------------------------------------
# Origin 2: real evidence, real criterion, inverted status.
#
# The passage, the criterion and the status vocabulary are all real. The only
# thing constructed is the pairing, and the pairing rule is mechanical: take a
# correct bundle from the reference and invert its status. That produces an
# error of a specific kind without anyone writing an erroneous claim.
#
# This is how the two categories the runs never exhibited get sourced without
# authoring. A negation error is a negated passage offered for the positive
# reading; a date error is a correctly spanning pair of dates offered for the
# claim that they do not span.
# ---------------------------------------------------------------------------

def origin_two() -> list[dict]:
    return [
        bundle(
            "CV-2-01", 2, "negation error", "MRI-001", "C5", "NOT_MET",
            [cite("MRI-001", "No prior lumbar imaging on file for this patient.",
                  "contradicting")],
            "UNSUPPORTED",
            "The passage states that no prior lumbar imaging exists. NOT_MET on "
            "this criterion asserts the opposite: that a prior study exists "
            "within twelve months without documented interval change. The "
            "evidence contradicts the status it is offered for. This is the "
            "reference's own MET evidence with the status inverted.",
            "Real passage, real criterion, status inverted mechanically from "
            "MRI-001 C5, whose reference status is MET on this same passage."),

        bundle(
            "CV-2-02", 2, "incorrect date", "MRI-005", "C2", "NOT_MET",
            [cite("MRI-005", "Date of Visit:  06/15/2026", "contradicting"),
             cite("MRI-005", "Date of Visit:  08/17/2026", "contradicting")],
            "UNSUPPORTED",
            "The two visit headers are nine weeks apart, which exceeds the "
            "six-week threshold. NOT_MET asserts the documented span falls "
            "short of it. The dates are correct and the arithmetic drawn from "
            "them is wrong, which is what makes this a date error rather than "
            "a missing-evidence case.",
            "Real passages, real criterion, status inverted mechanically from "
            "MRI-005 C2, whose reference status is MET on these same two "
            "passages."),

        bundle(
            "CV-2-03", 2, "incomplete evidence", "MRI-001", "C3", "MET",
            [cite("MRI-001", "Patient completed 8 physical therapy sessions.")],
            "UNSUPPORTED",
            "lumbar_mri C3 states that both the attempt and the failed outcome "
            "are required. This bundle offers the attempt alone. The passage is "
            "correct, the status is correct, and the evidence is half of what "
            "the criterion asks for. The reference records two units here for "
            "exactly this reason.",
            "Real passage, real criterion, real status. One of the reference's "
            "two required units withheld; nothing added."),
    ]


# ---------------------------------------------------------------------------
# Origin 1: real run output, supported claims only.
#
# All seven are SUPPORTED, and that is forced rather than chosen. Origins 2 and
# 3 can only produce unsupported bundles, so origin 1 is the sole source of the
# supported class. At four supported against twelve unsupported, a verifier
# that answers UNSUPPORTED to everything would score 75%, which reads as a
# pass. At seven against nine the same broken verifier scores 56%, visibly at
# chance. The majority-class baseline decides the composition.
#
# Origin 1 cannot supply unsupported bundles. Not because none exist — the
# first scored run produced four UNSUPPORTED verdicts — but because they cannot
# be annotated. Taking the verifier's verdict is circular; adjudicating them
# myself reintroduces the judgement origin 3 exists to exclude. See
# evals/claim_verification_design.md.
#
# Selection is mechanical: from the scored run, instances where the model's
# status AND reason codes both match the reference exactly and evidence was
# cited, taken in corpus order, at most one per case, three MET then two
# contradictions then two abstentions.
# ---------------------------------------------------------------------------

RUN = PROJECT_ROOT / "runs" / "20260910T202912Z_eval_development_A.json"


def origin_one() -> list[dict]:
    run = json.loads(RUN.read_text())
    exp = {(c["case_id"], k): e for c in LABELS["cases"]
           for k, e in c["expected"].items() if isinstance(e, dict)}
    buckets: dict[str, list] = {"met": [], "contradiction": [], "abstention": []}

    for entry in run["cases"]:
        for r in entry["verification"]["results"]:
            e = exp.get((entry["case_id"], r["criterion_id"]))
            if not e or not r["evidence"]:
                continue
            if r["verification"]["support_check"]["outcome"] != "SUPPORTED":
                continue
            if r["clinical_status"] != e["clinical_status"]:
                continue
            if sorted(r["reason_codes"]) != sorted(e["reason_codes"]):
                continue
            codes = sorted(r["reason_codes"])
            kind = ("contradiction" if "CONFLICTING_EVIDENCE" in codes
                    else "abstention" if codes else "met")
            buckets[kind].append((entry["case_id"], r))

    wanted = [("met", 3, "supported claim"),
              ("contradiction", 2, "contradiction"),
              ("abstention", 2, "supported claim")]
    out, used = [], set()
    for kind, n, category in wanted:
        taken = 0
        for case_id, r in buckets[kind]:
            if taken >= n:
                break
            if kind != "contradiction" and case_id in used:
                continue
            evidence = [cite(case_id, ev["quote"], ev["role"])
                        for ev in r["evidence"]]
            codes = ", ".join(r["reason_codes"]) or "none"
            out.append(bundle(
                f"CV-1-{len(out) + 1:02d}", 1, category, case_id,
                r["criterion_id"],
                r["clinical_status"] + (f" / {codes}" if r["reason_codes"] else ""),
                evidence, "SUPPORTED",
                _why(kind, r),
                "Real Baseline A output, prompt extraction/1.2.0, run "
                "20260910T202912Z. Selected mechanically: status and reason "
                "codes both match the reference and evidence was cited."))
            used.add(case_id)
            taken += 1
    return out


def _why(kind: str, r: dict) -> str:
    if kind == "contradiction":
        return ("The claim is that the record conflicts on this point, and the "
                "bundle cites both sides. An unresolved status is a claim like "
                "any other and the passages establish it. Support prompt 1.0.0 "
                "failed exactly here, returning UNSUPPORTED on a correct "
                "CONFLICTING_EVIDENCE result because the criterion 'requires a "
                "clear determination'; 1.1.0 was written to fix that and this "
                "bundle tests the fix on real material.")
    if kind == "abstention":
        return ("The claim is that the record addresses this criterion without "
                "settling it, and the cited passage is what addresses it. "
                "Abstention is a correct outcome and its evidence is judged the "
                "same way as any other.")
    return ("The cited passages establish the criterion on their own. Status "
            "and reason codes both match the reference, which was written "
            "before any document existed.")


def main() -> int:
    bundles = origin_three() + origin_two() + origin_one()
    payload = {
        "_meta": {
            "purpose": "Validates the Step 5 support verifier. Spec Section 8.",
            "not_status_labels": (
                "These bundles are NOT the criterion-status labels in "
                "corpus/labels.json and cannot be substituted for them. A "
                "verifier scoring well here says nothing about evidence "
                "recall. The two sets are never pooled."),
            "design": "evals/claim_verification_design.md",
            "built": "2026-09-10",
            "complete": True,
            "composition_note": (
                "Sixteen bundles. All seven origin-1 bundles are SUPPORTED and "
                "all nine origin-2 and origin-3 bundles are UNSUPPORTED. That "
                "split is forced by the material, not chosen: origins 2 and 3 "
                "can only produce unsupported bundles, and origin 1's "
                "unsupported candidates cannot be annotated without "
                "circularity. Majority-class baseline is 9 of 16, so a "
                "verifier answering UNSUPPORTED to everything scores 56 "
                "percent and is visibly at chance."),
            "excluded_deliberately": (
                "The five critical errors in the source run are the most "
                "interesting material available and none is included. They are "
                "claims the reference calls wrong whose cited evidence "
                "genuinely supports them; the disagreement is about record "
                "completeness, which Step 5 structurally cannot assess because "
                "it never sees the record. Including them would test the "
                "verifier on a question it is designed not to answer. Their "
                "absence is a decision, not an oversight."),
            "categories_with_one_bundle": (
                "incomplete evidence, incorrect date, negation error. Each "
                "rests on a single observation and is reported as a category "
                "this set cannot measure rather than padded."),
        },
        "bundles": bundles,
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")

    from collections import Counter
    print(f"{len(bundles)} bundles -> {OUT.relative_to(PROJECT_ROOT)}")
    print("  by origin  :", dict(Counter(b["origin"] for b in bundles)))
    print("  by category:", dict(Counter(b["category"] for b in bundles)))
    print("  by verdict :", dict(Counter(b["expected_verdict"] for b in bundles)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
