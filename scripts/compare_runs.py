#!/usr/bin/env python3
"""Compare two evaluation runs case by case.

Written to separate two explanations for a latency change: an instruction that
made the model produce more, against a case that is simply variable. One
measurement of each cannot distinguish them, and the distinguishing evidence is
output tokens rather than seconds.

Across the first scored development run, wall clock tracked output length at
roughly 100 tokens per second on every case. So a case that got slower without
producing more is variance, and a case that got slower by producing more is a
cost the change introduced.

    python3 scripts/compare_runs.py runs/<older>.json runs/<newer>.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def load(path: str) -> tuple[dict, dict]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    by_case = {c["case_id"]: c["extraction"] for c in d["cases"]}
    return d, by_case


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    old, a = load(sys.argv[1])
    new, b = load(sys.argv[2])

    print(f"{'':10} {'prompt':>16}  {old['preflight']['prompt_version']:>16} -> "
          f"{new['preflight']['prompt_version']}")
    print(f"\n{'case':10} {'sec A':>7} {'sec B':>7} {'Δsec':>7}   "
          f"{'out A':>7} {'out B':>7} {'Δout':>7}   {'tok/s A':>7} {'tok/s B':>7}")

    rows = []
    for case_id in sorted(set(a) & set(b)):
        sa, sb = a[case_id]["seconds"], b[case_id]["seconds"]
        oa, ob = a[case_id]["output_tokens"], b[case_id]["output_tokens"]
        rows.append((case_id, sa, sb, oa, ob))
        ra = oa / sa if sa else 0
        rb = ob / sb if sb else 0
        print(f"{case_id:10} {sa:7.1f} {sb:7.1f} {sb - sa:+7.1f}   "
              f"{oa:7} {ob:7} {ob - oa:+7}   {ra:7.0f} {rb:7.0f}")

    tot_sa = sum(r[1] for r in rows)
    tot_sb = sum(r[2] for r in rows)
    tot_oa = sum(r[3] for r in rows)
    tot_ob = sum(r[4] for r in rows)
    print(f"\n{'TOTAL':10} {tot_sa:7.1f} {tot_sb:7.1f} {tot_sb - tot_sa:+7.1f}   "
          f"{tot_oa:7} {tot_ob:7} {tot_ob - tot_oa:+7}")
    print(f"\noutput tokens overall: {tot_ob / tot_oa:.2f}x")

    print("\nPer case, sorted by change in output tokens:")
    for case_id, sa, sb, oa, ob in sorted(rows, key=lambda r: -(r[4] - r[3])):
        pct = (ob - oa) / oa * 100 if oa else 0
        verdict = ("MORE OUTPUT" if abs(pct) > 25 and ob > oa else
                   "LESS OUTPUT" if abs(pct) > 25 else "similar output")
        print(f"  {case_id:10} {pct:+6.0f}% output   {sb - sa:+6.1f}s   {verdict}")

    print("\nReading: a case slower with similar output is variance. A case "
          "slower\nbecause it produced substantially more is a cost the change "
          "introduced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
