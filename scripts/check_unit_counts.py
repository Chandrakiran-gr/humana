#!/usr/bin/env python3
"""Flag instances whose unit count is below the facts their criterion requires.

Written after the same defect was found four times by hand during Task 2.3b
enumeration. `lumbar_mri` C3 says "Both the attempt and the failed outcome are
required" and four instances of it carried one unit. `total_knee_arthroplasty`
C4 says "each documented as actually attempted and each with a documented
outcome" for two modalities, which is four facts, and every satisfied instance
carried two.

The root cause is one misreading, not many: the reference counted the passage
the author had in mind rather than the facts the criterion enumerates. Once a
root cause is known, waiting for enumeration to reach each instance is the
wrong way to find the rest of them.

What this checks
----------------
A criterion is multi-fact where its `satisfied_by` says so — "both X and Y are
required", "together with", "each ... and each". For every instance that is
**satisfied** on that criterion, the unit count must be at least the number of
facts. Only satisfied instances are checked: where a criterion is unmet or
unresolved, the evidence needed is what shows the shortfall, which is a
different and smaller question.

This finds a floor, not the answer. A criterion needing two facts per modality
across two modalities needs four units; this reports the shape and the
arithmetic is left to a reader, because how many modalities an instance
actually rests on is a property of the packet.

    python3 scripts/check_unit_counts.py
    python3 scripts/check_unit_counts.py --split development

Exit status 0 if no instance is below its floor, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# A criterion offering a branch that is explicitly satisfiable by one passage
# has a floor of one, whatever its other branch requires. The first version of
# this script missed that and flagged seven instances of an explicit-duration
# statement as undercounted, which they are not.
SINGLE_PASSAGE_BRANCH = re.compile(r"which needs one passage", re.I)

# Phrasings that mark a criterion as enumerating more than one required fact.
MULTI_FACT = [
    (re.compile(r"both the .+ and the .+ are required", re.I), 2),
    (re.compile(r"together with a documented outcome", re.I), 2),
    (re.compile(r"a dated start and a dated end", re.I), 2),
    (re.compile(r"plus at least one of", re.I), 2),
    (re.compile(r"which needs both passages", re.I), 2),
]

# Per-modality requirements multiply. Where each counted modality needs an
# attempt and an outcome, a criterion asking for two modalities asks for four
# facts. This has now been got wrong twice:
#
#   v1 scored "each attempted and each with an outcome" as two facts rather
#   than two per modality, and missed every total_knee_arthroplasty C4.
#   v2 fixed that with a pattern matching only TKA C4's exact wording, and so
#   missed lumbar_fusion C4, which says the same thing in different words:
#   physical therapy "with an outcome", plus one more modality "also
#   documented as attempted with an outcome".
#
# Matching wording was the mistake both times. What matters is whether an
# outcome is required per modality, and how many modalities are counted.
PER_ITEM = re.compile(r"with (?:a documented |an )outcome", re.I)

# How many modalities the criterion counts. A mandatory one named alongside
# "at least one of" is two, not one.
MANDATORY_PLUS = re.compile(r"and at least (one|two) of", re.I)
AT_LEAST = re.compile(r"at least (one|two|three) of", re.I)
WORDS = {"one": 1, "two": 2, "three": 3}


def modalities_counted(text: str) -> int:
    m = MANDATORY_PLUS.search(text)
    if m:
        return 1 + WORDS[m.group(1).lower()]
    m = AT_LEAST.search(text)
    return WORDS[m.group(1).lower()] if m else 1

# Statuses where the criterion is satisfied and therefore needs the full set of
# facts. An unresolved or contradicted instance cites what shows the shortfall.
SATISFIED = {"MET"}


def facts_required(text: str, satisfied_by: str) -> tuple[int, str]:
    if SINGLE_PASSAGE_BRANCH.search(satisfied_by):
        return 1, "has a branch satisfiable by one passage"

    if PER_ITEM.search(satisfied_by):
        n = modalities_counted(text)
        return n * 2, f"{n} modalit{'y' if n == 1 else 'ies'}, each needing an attempt and an outcome"

    for pattern, count in MULTI_FACT:
        if pattern.search(satisfied_by):
            return count, pattern.pattern
    return 1, ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", default=None)
    ap.add_argument("--labels", default="corpus/labels.json")
    ap.add_argument("--criteria", default="criteria/criteria_sets.json")
    args = ap.parse_args()

    criteria = json.loads(
        (PROJECT_ROOT / args.criteria).read_text(encoding="utf-8"))
    labels = json.loads(
        (PROJECT_ROOT / args.labels).read_text(encoding="utf-8"))

    sets = {s["procedure_id"]: {c["id"]: c for c in s["criteria"]}
            for s in criteria["criteria_sets"]}

    multi = {}
    for pid, crits in sets.items():
        for cid, c in crits.items():
            n, why = facts_required(c["text"], c["satisfied_by"])
            if n > 1:
                multi[(pid, cid)] = (n, why)

    print(f"{len(multi)} criterion(s) enumerate more than one required fact:\n")
    for (pid, cid), (n, why) in sorted(multi.items()):
        print(f"  {pid} {cid}: {n} facts when satisfied  ({why})")
    print()

    below = []
    checked = 0
    for case in labels["cases"]:
        if args.split and case["split"] != args.split:
            continue
        pid = case["procedure_id"]
        for cid, e in case["expected"].items():
            if not isinstance(e, dict) or (pid, cid) not in multi:
                continue
            if e["clinical_status"] not in SATISFIED:
                continue
            checked += 1
            floor = multi[(pid, cid)][0]
            if e["evidence_units_required"] < floor:
                below.append((case["case_id"], cid, case["split"],
                              e["evidence_units_required"], floor))

    print(f"Checked {checked} satisfied instance(s) of those criteria.\n")
    if below:
        print(f"[FAIL] {len(below)} instance(s) below the floor:\n")
        print(f"  {'case':10} {'crit':5} {'split':14} {'units':>5} {'floor':>6}")
        for case_id, cid, split, units, floor in below:
            print(f"  {case_id:10} {cid:5} {split:14} {units:>5} {floor:>6}")
        print("\nThe floor is a minimum. Check each against its packet before "
              "amending: how many\nmodalities an instance actually rests on is a "
              "property of the packet, not the criterion.")
        return 1

    print("[OK] Every satisfied instance meets the floor for its criterion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
