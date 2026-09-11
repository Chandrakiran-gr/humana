#!/usr/bin/env python3
"""Write acceptable_evidence into corpus/labels.json, one instance at a time.

Task 2.3b. The adjudication was done adversarially during enumeration; this
records the result. Quotes are validated as they are written, so a quote that
does not resolve to exactly one span is refused rather than stored.

That refusal is the point. The reference may not cite what the system would be
forbidden from citing: Step 4 rejects a quote resolving nowhere as
unverifiable, and one resolving twice as failing to identify a location. A
reference containing either would score the system against evidence it could
not have cited.

Usage is programmatic. Import `write` and call it per instance:

    write("MRI-005", "C2",
          units=[(["Date of Visit:  06/15/2026"], "supporting"),
                 (["Date of Visit:  08/17/2026"], "supporting")],
          also=["Same right low back pain across the belt line ..."],
          ruled_out=[("She also brings up low back pain, ...",
                      "documents the symptom but not the span; the derivation "
                      "runs on the header dates")])

`python3 scripts/write_acceptable_evidence.py --zero-unit` fills every
zero-unit instance with an empty set in one pass. Those were each verified
against every document in their packet during enumeration, and an empty
acceptable set is the positive claim that nothing in the packet addresses the
criterion, not the absence of a claim.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import ingest_case  # noqa: E402

LABELS = PROJECT_ROOT / "corpus" / "labels.json"
CASES = PROJECT_ROOT / "corpus" / "cases"

_packets: dict[str, object] = {}


def packet(case_id: str):
    if case_id not in _packets:
        _packets[case_id] = ingest_case(case_id, CASES)
    return _packets[case_id]


def resolve(case_id: str, quote: str) -> list[dict]:
    """Locate a quote, or raise. Returns one entry per document it occurs in.

    Validation matches Step 4, which resolves a quote *within the document the
    citation names* rather than across the packet. A passage carried forward
    into a second note therefore yields two acceptable entries, one per
    document, because they are different evidence: MRI-005 C2 turns on which
    of two encounters a fact came from.

    What is refused is a quote occurring more than once inside a single
    document, which Step 4 rejects as failing to identify a location. The
    reference may not cite what the system would be forbidden from citing.

    An earlier version of this function used packet-level lookup and refused
    any quote appearing in two documents. That was stricter than Step 4 and
    would have written correct evidence out of the reference as unciteable.
    """
    p = packet(case_id)
    by_doc: dict[str, int] = {}
    for span in p.locate(quote):
        by_doc[span.document_id] = by_doc.get(span.document_id, 0) + 1
    if not by_doc:
        raise ValueError(f"{case_id}: quote resolves nowhere\n  {quote[:100]!r}")
    repeated = [k for k, n in by_doc.items() if n > 1]
    if repeated:
        raise ValueError(
            f"{case_id}: quote occurs more than once inside "
            f"{p.by_id(repeated[0]).filename}, so it identifies no location and "
            f"Step 4 would reject it\n  {quote[:100]!r}")
    out = []
    for span in p.locate(quote):
        doc = p.by_id(span.document_id)
        out.append({"document_id": span.document_id, "filename": doc.filename,
                    "quote": quote, "start": span.start, "end": span.end})
    return out


def load() -> dict:
    return json.loads(LABELS.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    LABELS.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")


def write(case_id: str, criterion_id: str, units: list, also: list | None = None,
          ruled_out: list | None = None, data: dict | None = None) -> dict:
    """Record one instance's acceptable evidence. Validates every quote."""
    standalone = data is None
    data = data if data is not None else load()
    case = next(c for c in data["cases"] if c["case_id"] == case_id)
    expectation = case["expected"][criterion_id]

    required = expectation["evidence_units_required"]
    if len(units) != required:
        raise ValueError(
            f"{case_id} {criterion_id}: {len(units)} units given, "
            f"evidence_units_required is {required}. Fix one of them "
            f"deliberately; do not let transcription revise the count.")

    built = []
    for index, (quotes, role) in enumerate(units, start=1):
        assert role in ("supporting", "contradicting"), role
        resolved = [entry for q in quotes for entry in resolve(case_id, q)]
        built.append({"unit": index, "role": role, "quotes": resolved})

    expectation["acceptable_evidence"] = {
        "units": built,
        "also_acceptable": [e for q in (also or []) for e in resolve(case_id, q)],
        "ruled_out": [{"quote": q, "why": why} for q, why in (ruled_out or [])],
    }
    if standalone:
        save(data)
    return data


def fill_zero_unit() -> int:
    """Empty acceptable sets for every zero-unit scorable instance."""
    data = load()
    n = 0
    for case in data["cases"]:
        for criterion_id, e in case["expected"].items():
            if not isinstance(e, dict):
                continue
            if e["clinical_status"] == "NOT_APPLICABLE":
                continue
            if e["evidence_units_required"] != 0:
                continue
            if "acceptable_evidence" in e:
                continue
            e["acceptable_evidence"] = {"units": [], "also_acceptable": [],
                                        "ruled_out": []}
            n += 1
    save(data)
    return n


def coverage() -> tuple[int, int, list[str]]:
    data = load()
    done = total = 0
    missing = []
    for case in data["cases"]:
        for criterion_id, e in case["expected"].items():
            if not isinstance(e, dict) or e["clinical_status"] == "NOT_APPLICABLE":
                continue
            total += 1
            if "acceptable_evidence" in e:
                done += 1
            else:
                missing.append(f"{case['case_id']} {criterion_id}")
    return done, total, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--zero-unit", action="store_true",
                    help="fill every zero-unit instance with an empty set")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()

    if args.zero_unit:
        print(f"filled {fill_zero_unit()} zero-unit instance(s)")
    done, total, missing = coverage()
    print(f"coverage: {done}/{total} scorable instances")
    if args.coverage and missing:
        print(f"missing {len(missing)}:")
        for m in missing:
            print(f"  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
