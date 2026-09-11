#!/usr/bin/env python3
"""Task 2.4: the evaluation harness. Command line, independent of any interface.

Runs Steps 1 to 5 over a split, scores against the reference, and writes a
timestamped result file so runs stay comparable.

    python3 scripts/run_eval.py --split development --config A --dry-run
    python3 scripts/run_eval.py --split development --config A
    python3 scripts/run_eval.py --case MRI-005 --config A

Every printed figure carries the counts it came from. Neither critical error
direction is printed as a rate; both are counts with the affected instances
named. `evals/decision_rules.md` records why, and it was written before any
result existed.

Held-out and transfer are refused without `--unlock`, on the same reasoning as
`run_extraction.py`: a split looked at during development is no longer held
out, so using one has to be a deliberate act with a name.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
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
    AnthropicClient, PreflightError, ProcessingStatus, RunScore,
    build_extraction_prompt, extract, format_report, ingest_case, load_criteria,
    load_labels, preflight, score_run, verify_run,
)
from um_evidence.extract import (  # noqa: E402
    DEFAULT_MODEL, DEFAULT_TIMEOUT_SECONDS, MAX_ATTEMPTS,
)

CASES = PROJECT_ROOT / "corpus" / "cases"
LOCKED = {"held_out_test", "transfer"}


def independent_case_count(labels: dict, case_ids: list[str]) -> int:
    """Variants are one observation with their parent, not two.

    decision_rules.md Section 3: a difference appearing in both TKA-103 and
    TKA-103V is one finding observed twice.
    """
    by_id = {c["case_id"]: c for c in labels["cases"]}
    roots = set()
    for case_id in case_ids:
        case = by_id[case_id]
        roots.add(case["parent_case_id"] or case_id)
    return len(roots)


def format_timings(timings: list[tuple[str, float, float]], total: float,
                   in_tok: int, out_tok: int) -> str:
    """Per-case wall clock as a distribution, not a mean.

    Spec Section 13 requires a case run live, selected during the session. The
    number that matters for that is not the average: it is how long the slowest
    case takes, because that is the silence a presenter has to hold. A mean
    over fifteen cases hides a single case that runs four times as long.
    """
    if not timings:
        return "\nOPERATIONAL\n  no cases ran"
    totals = sorted(t[1] + t[2] for t in timings)
    n = len(totals)

    def pct(p: float) -> float:
        return totals[min(n - 1, int(round(p * (n - 1))))]

    slowest = sorted(timings, key=lambda t: -(t[1] + t[2]))[:3]
    lines = [
        "", "OPERATIONAL  (sequential; Spec Section 11 fixes this)",
        f"  tokens: {in_tok} in, {out_tok} out over {n} case(s)",
        f"  wall clock total: {total:.1f}s",
        "",
        "  per-case seconds, the distribution rather than the mean",
        f"    min {totals[0]:.1f}   median {pct(0.5):.1f}   "
        f"p90 {pct(0.9):.1f}   max {totals[-1]:.1f}",
        f"    mean {sum(totals) / n:.1f}",
        "",
        "  slowest cases, which is what a live demonstration has to hold",
    ]
    for case_id, extract_s, verify_s in slowest:
        lines.append(f"    {case_id:10} {extract_s + verify_s:6.1f}s  "
                     f"(extraction {extract_s:.1f}, verification {verify_s:.1f})")
    if totals[-1] > 60:
        lines.append(f"    NOTE: the slowest case is {totals[-1]:.0f}s of silence "
                     f"in a live run.")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", default=None,
                    choices=("development", "held_out_test", "transfer"))
    ap.add_argument("--case", default=None, help="one case id instead of a split")
    ap.add_argument("--cases", default=None,
                    help="comma-separated case ids. Exists so a run can be "
                         "split into batches that finish inside a foreground "
                         "timeout; a full split takes about 720 seconds and a "
                         "background run cannot be told from a stalled one.")
    ap.add_argument("--config", choices=("A", "B"), default="A")
    ap.add_argument("--model", default=os.environ.get("UM_MODEL", DEFAULT_MODEL))
    ap.add_argument("--dry-run", action="store_true",
                    help="assemble prompts and report cost, making no call")
    ap.add_argument("--unlock", action="store_true")
    ap.add_argument("--allow-model-override", action="store_true")
    ap.add_argument("--no-support", action="store_true",
                    help="Step 4 only; skip the support-verification calls")
    args = ap.parse_args()

    if not args.split and not args.case and not args.cases:
        print("give --split, --case, or --cases")
        return 1

    try:
        checks = preflight(model=args.model,
                           allow_model_override=args.allow_model_override
                           ).raise_if_failed()
    except PreflightError as exc:
        print(exc)
        return 1

    labels = load_labels()
    if args.cases:
        wanted = [x.strip() for x in args.cases.split(",") if x.strip()]
        selected = [c for c in labels["cases"] if c["case_id"] in wanted]
        missing = set(wanted) - {c["case_id"] for c in selected}
        if missing:
            print(f"unknown case id(s): {sorted(missing)}")
            return 1
    elif args.case:
        selected = [c for c in labels["cases"] if c["case_id"] == args.case]
    else:
        selected = [c for c in labels["cases"] if c["split"] == args.split]
    if not selected:
        print("no matching case")
        return 1

    splits = {c["split"] for c in selected}
    if (splits & LOCKED) and not args.unlock:
        print(f"{', '.join(sorted(splits & LOCKED))} is locked.\n"
              f"Looking at it now costs the ability to use it later.\n"
              f"Pass --unlock if that is what you intend.")
        return 1

    print(f"preflight: model={checks.model} prompt={checks.prompt_version} "
          f"criteria={checks.criteria_set_version}")
    print(f"{len(selected)} case(s), configuration {args.config}\n")

    # Ingest everything first, so a corpus problem surfaces before any spend.
    packets, criteria, calls, tokens = {}, {}, 0, 0
    for case in selected:
        case_id = case["case_id"]
        packet = ingest_case(case_id, CASES)
        packets[case_id] = packet
        criteria[case_id] = load_criteria(case["procedure_id"])
        if packet.manifest_check.get("status") != "match":
            print(f"  {case_id}: manifest {packet.manifest_check.get('status')}")
        if packet.processing_status is ProcessingStatus.FAILED:
            print(f"  {case_id}: ingestion FAILED, will not be sent")
            continue
        n = 1 if args.config == "A" else len(criteria[case_id].criteria)
        calls += n
        prompt = build_extraction_prompt(criteria[case_id], packet)
        tokens += packet.estimated_tokens * n

    print(f"extraction calls: {calls}   packet tokens sent: ~{tokens} (estimate)")
    if args.dry_run:
        print("\n--dry-run: nothing was sent.")
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("\nANTHROPIC_API_KEY is not set. cp .env.example .env")
        return 1

    client = AnthropicClient()
    attempts = int(os.environ.get("UM_MAX_RETRIES", MAX_ATTEMPTS - 1)) + 1
    timeout = float(os.environ.get("UM_REQUEST_TIMEOUT_SECONDS",
                                   DEFAULT_TIMEOUT_SECONDS))

    score = RunScore(configuration=args.config,
                     split=args.split or selected[0]["split"])
    per_case, in_tok, out_tok, seconds = [], 0, 0, 0.0
    timings: list[tuple[str, float, float]] = []

    for case in selected:
        case_id = case["case_id"]
        packet = packets[case_id]
        criteria_set = criteria[case_id]
        run = extract(criteria_set, packet, client, configuration=args.config,
                      model=args.model, max_attempts=attempts, timeout=timeout)
        verified = verify_run(run, packet, criteria_set,
                              None if args.no_support else client,
                              model=args.model, timeout=timeout,
                              max_attempts=attempts)
        score_run(verified, labels, score)
        in_tok += run.input_tokens
        out_tok += run.output_tokens
        seconds += run.seconds + verified.seconds
        timings.append((case_id, run.seconds, verified.seconds))
        per_case.append({"case_id": case_id, "extraction": run.as_dict(),
                         "verification": verified.as_dict()})
        print(f"  {case_id:10} {run.processing_status.value:9} "
              f"{verified.verified_spans}/{verified.returned_spans} quotes verified"
              f"   {run.seconds + verified.seconds:6.1f}s")

    print()
    print(format_report(
        score, independent_case_count(labels, [c["case_id"] for c in selected])))
    print(format_timings(timings, seconds, in_tok, out_tok))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = PROJECT_ROOT / "runs"
    out_dir.mkdir(exist_ok=True)
    name = args.case or args.split or f"batch{len(selected)}"
    out_path = out_dir / f"{stamp}_eval_{name}_{args.config}.json"
    out_path.write_text(json.dumps({
        "generated": stamp,
        "split": score.split,
        "configuration": args.config,
        "preflight": checks.as_dict(),
        "settings": {"model": args.model, "max_attempts": attempts,
                     "timeout_seconds": timeout,
                     "support_verification": not args.no_support,
                     "execution": "sequential"},
        "operational": {
            "input_tokens": in_tok, "output_tokens": out_tok,
            "seconds": round(seconds, 3),
            "per_case_seconds": [
                {"case_id": c, "extraction": round(e, 3),
                 "verification": round(v, 3), "total": round(e + v, 3)}
                for c, e, v in timings],
        },
        "score": score.as_dict(),
        "cases": per_case,
    }, indent=2), encoding="utf-8")
    print(f"\nresult: {out_path.relative_to(PROJECT_ROOT)}")
    print("Neither critical error direction is reported as a rate. See "
          "evals/decision_rules.md for why.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
