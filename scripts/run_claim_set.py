#!/usr/bin/env python3
"""Run the claim-verification set against the Step 5 support verifier.

Task 2.5. Each bundle carries a proposed status, cited evidence, and an
expected verdict annotated before the verifier ever saw it. This asks the
verifier for its verdict and compares.

Reported by origin, per the pre-registration in
`evals/claim_verification_design.md`:

- the **within-verdict** comparison governs, because the origins do not share
  a verdict distribution and a cross-origin comparison would be confounded
- **counts, not rates**, because six bundles against three cannot carry a
  percentage

    python3 scripts/run_claim_set.py --dry-run
    python3 scripts/run_claim_set.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from um_evidence import (  # noqa: E402
    AnthropicClient, ClinicalStatus, ProcessingStatus, ReasonCode,
    ingest_case, load_criteria, verify_support,
)
from um_evidence.verify import VerifiedCriterion, VerifiedEvidence  # noqa: E402
from um_evidence.extract import DEFAULT_MODEL, SETTINGS_VERSION  # noqa: E402

SET = PROJECT_ROOT / "evals" / "claim_verification_set.json"
CASES = PROJECT_ROOT / "corpus" / "cases"


def to_result(bundle: dict) -> VerifiedCriterion:
    """Rebuild the bundle as the object Step 5 expects."""
    packet = ingest_case(bundle["case_id"], CASES)
    status_text = bundle["proposed_status"].split("/")[0].strip()
    codes = []
    if "/" in bundle["proposed_status"]:
        codes = [ReasonCode(c.strip()) for c in
                 bundle["proposed_status"].split("/", 1)[1].split(",")]

    evidence = []
    for e in bundle["evidence"]:
        doc = packet.by_id(e["document_id"])
        spans = doc.locate(e["quote"])
        if len(spans) != 1:
            raise ValueError(f"{bundle['id']}: quote resolves {len(spans)}x")
        evidence.append(VerifiedEvidence(
            document_id=e["document_id"], quote=e["quote"], role=e["role"],
            span=spans[0], verified=True))

    return VerifiedCriterion(
        criterion_id=bundle["criterion_id"],
        clinical_status=ClinicalStatus(status_text),
        processing_status=ProcessingStatus.COMPLETE,
        reason_codes=codes, evidence=evidence,
        explanation=bundle.get("why_proposed", ""))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default=os.environ.get("UM_MODEL", DEFAULT_MODEL))
    args = ap.parse_args()

    data = json.loads(SET.read_text())
    bundles = data["bundles"]
    print(f"{len(bundles)} bundles, "
          f"{dict(Counter(b['origin'] for b in bundles))} by origin, "
          f"{dict(Counter(b['expected_verdict'] for b in bundles))} by verdict")
    if args.dry_run:
        for b in bundles:
            to_result(b)
        print("--dry-run: every bundle rebuilds and every quote resolves.")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.")
        return 1

    client = AnthropicClient()
    rows = []
    for b in bundles:
        result = to_result(b)
        criteria_set = load_criteria(
            next(c["procedure_id"] for c in
                 json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())["cases"]
                 if c["case_id"] == b["case_id"]))
        verify_support(result, criteria_set[b["criterion_id"]], criteria_set,
                       client, model=args.model)
        agree = result.support_outcome == b["expected_verdict"]
        rows.append({**{k: b[k] for k in
                        ("id", "origin", "category", "case_id", "criterion_id",
                         "proposed_status", "expected_verdict")},
                     "verdict": result.support_outcome,
                     "agree": agree,
                     "detail": result.support_detail})
        print(f"  {b['id']}  o{b['origin']}  expected {b['expected_verdict']:11} "
              f"got {result.support_outcome:13} {'ok' if agree else 'DISAGREE'}")

    print()
    report(rows)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = PROJECT_ROOT / "runs" / f"{stamp}_claimset.json"
    out.write_text(json.dumps({
        "generated": stamp, "model": args.model,
        "settings_version": SETTINGS_VERSION,
        "support_prompt": "support/1.0.0",
        "set_meta": data["_meta"], "results": rows,
    }, indent=2), encoding="utf-8")
    print(f"\nresult: {out.relative_to(PROJECT_ROOT)}")
    return 0


def report(rows: list[dict]) -> None:
    """Counts, never rates. Six against three cannot carry a percentage."""
    print("BY ORIGIN  (counts; the set is too small for rates)")
    for origin in sorted({r["origin"] for r in rows}):
        sub = [r for r in rows if r["origin"] == origin]
        ok = sum(1 for r in sub if r["agree"])
        label = {1: "real run output", 2: "recombined", 3: "ruled_out, unchosen"}[origin]
        print(f"  origin {origin} ({label:20}): {ok} of {len(sub)} agree")

    print("\nWITHIN-VERDICT  (this governs; see the pre-registration)")
    for verdict in ("UNSUPPORTED", "SUPPORTED"):
        sub = [r for r in rows if r["expected_verdict"] == verdict]
        if not sub:
            continue
        print(f"  expected {verdict}:")
        for origin in sorted({r["origin"] for r in sub}):
            s2 = [r for r in sub if r["origin"] == origin]
            ok = sum(1 for r in s2 if r["agree"])
            print(f"      origin {origin}: {ok} of {len(s2)} agree")

    dis = [r for r in rows if not r["agree"]]
    print(f"\nDISAGREEMENTS: {len(dis)} of {len(rows)}")
    for r in dis:
        print(f"  {r['id']} o{r['origin']} {r['case_id']} {r['criterion_id']} "
              f"[{r['category']}]")
        print(f"      expected {r['expected_verdict']}, got {r['verdict']}")
        print(f"      {r['detail'][:150]}")


if __name__ == "__main__":
    sys.exit(main())
