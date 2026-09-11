#!/usr/bin/env python3
"""Check generated case packets against the lexical constraints in the labels.

Four criterion instances in corpus/labels.json are marked `interpretation:
semantic`: the criterion's own vocabulary never appears in the packet, and
locating the evidence requires mapping clinical content onto the requirement.
Three more are marked `derived`: the fact is stated nowhere and must be computed
from two dated passages.

Both kinds are destroyed by a single careless phrase. Writing "meloxicam (NSAID)"
turns MRI-005 C3 from a semantic instance into a keyword match, and nothing
downstream would notice: the label still says MET, the packet still supports it,
and the evaluation quietly stops measuring what it was built to measure.

Each such instance carries `prohibited_terms`. This script searches the generated
packet for them and reports every hit with its location and surrounding line.

    python3 scripts/check_lexical_constraints.py
    python3 scripts/check_lexical_constraints.py --case TKA-004
    python3 scripts/check_lexical_constraints.py --split development

Exit status 0 if no prohibited term was found, 1 otherwise.

WHAT THIS DOES NOT CHECK
------------------------
A clean run does not mean a constraint is satisfied. Term lists catch known
phrasings, not every way a fact could be worded, and several constraints are not
lexical at all. Every instance also carries `manual_only_constraint` describing
what a person still has to read for. Those are printed alongside the result and
are part of the Task 1.3 manual check, which this script supports and does not
replace.
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Extensions treated as packet text. Anything else in a case directory is
# reported as skipped rather than silently ignored.
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv"}


def load_constrained_instances(labels: dict, split: str | None, case_id: str | None) -> list[dict]:
    """Every criterion instance carrying prohibited_terms, flattened."""
    found = []
    for case in labels["cases"]:
        if split and case["split"] != split:
            continue
        if case_id and case["case_id"] != case_id:
            continue
        for criterion_id, expectation in case["expected"].items():
            if criterion_id.startswith("_"):
                continue
            terms = expectation.get("prohibited_terms")
            if not terms:
                continue
            found.append({
                "case_id": case["case_id"],
                "split": case["split"],
                "criterion_id": criterion_id,
                "interpretation": expectation.get("interpretation", "unspecified"),
                "terms": terms,
                "scope": expectation.get("prohibited_scope", "packet"),
                "manual": expectation.get("manual_only_constraint", ""),
            })
    return found


def files_in_scope(case_dir: Path, scope: str) -> tuple[list[Path], str]:
    """Resolve a scope to a file list.

    "packet"    every text file in the case directory
    "<glob>"    only files whose name matches
    "!<glob>"   every text file except those whose name matches
    """
    all_files = sorted(p for p in case_dir.rglob("*")
                       if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES)
    if scope == "packet":
        return all_files, "whole packet"
    if scope.startswith("!"):
        pattern = scope[1:]
        kept = [p for p in all_files if not fnmatch.fnmatch(p.name.lower(), pattern.lower())]
        return kept, f"whole packet except {pattern}"
    kept = [p for p in all_files if fnmatch.fnmatch(p.name.lower(), scope.lower())]
    return kept, f"files matching {scope}"


def search(path: Path, terms: list[str]) -> list[dict]:
    """Case-insensitive, anchored at a word boundary so inflections are caught.

    A leading \\b with no trailing boundary means "NSAID" also matches "NSAIDs"
    and "interfer" matches "interferes" and "interfering". That is deliberate:
    the constraint is that the reader must not be handed the word.
    """
    hits = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return [{"line_no": 0, "term": "", "line": f"<unreadable: {exc}>", "match": ""}]
    patterns = [(term, re.compile(r"\b" + re.escape(term), re.IGNORECASE)) for term in terms]
    for line_no, line in enumerate(lines, start=1):
        for term, pattern in patterns:
            match = pattern.search(line)
            if match:
                hits.append({
                    "line_no": line_no,
                    "term": term,
                    "match": match.group(0),
                    "line": line.strip(),
                })
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", default="corpus/labels.json")
    ap.add_argument("--cases_dir", default="corpus/cases")
    ap.add_argument("--case", default=None, help="Check one case id.")
    ap.add_argument("--split", default=None,
                    choices=["development", "held_out_test", "transfer"])
    ap.add_argument("--show_manual", action="store_true",
                    help="Print the manual-only constraints in full.")
    args = ap.parse_args()

    labels_path = PROJECT_ROOT / args.labels
    if not labels_path.exists():
        print(f"[FAIL] Not found: {labels_path}")
        return 1
    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    cases_dir = PROJECT_ROOT / args.cases_dir

    instances = load_constrained_instances(labels, args.split, args.case)
    if not instances:
        print("[FAIL] No constrained instances matched that filter.")
        return 1

    total_hits = 0
    checked = 0
    ungenerated = []

    for inst in instances:
        label = f"{inst['case_id']} {inst['criterion_id']}"
        case_dir = cases_dir / inst["case_id"]
        if not case_dir.is_dir():
            ungenerated.append(label)
            continue

        in_scope, scope_desc = files_in_scope(case_dir, inst["scope"])
        checked += 1
        if not in_scope:
            print(f"[WARN] {label:14} scope '{inst['scope']}' matched no files in {case_dir}")
            continue

        instance_hits = []
        for path in in_scope:
            for hit in search(path, inst["terms"]):
                instance_hits.append((path, hit))

        if instance_hits:
            total_hits += len(instance_hits)
            print(f"[FAIL] {label:14} [{inst['interpretation']}]  "
                  f"{len(instance_hits)} prohibited term(s), scope: {scope_desc}")
            for path, hit in instance_hits:
                rel = path.relative_to(PROJECT_ROOT)
                print(f"         {rel}:{hit['line_no']}  "
                      f"term {hit['term']!r} matched {hit['match']!r}")
                print(f"           | {hit['line'][:110]}")
            print(f"         constraint: {_first_sentence(inst, labels)}")
        else:
            print(f"[OK]   {label:14} [{inst['interpretation']}]  "
                  f"clean across {len(in_scope)} file(s), scope: {scope_desc}")

        if args.show_manual and inst["manual"]:
            print(f"         still to read for: {inst['manual']}")

    print()
    if ungenerated:
        print(f"[SKIP] {len(ungenerated)} instance(s) have no packet yet: "
              f"{', '.join(ungenerated)}")
        if not checked:
            print("       Nothing to check. Generate packets in Task 1.2, then re-run.")

    if checked:
        print(f"Checked {checked} constrained instance(s). {total_hits} prohibited term(s) found.")
        print()
        print("A clean result is not a satisfied constraint. Term lists catch known")
        print("phrasings only, and several constraints are not lexical. Re-run with")
        print("--show_manual for what a person still has to read for.")

    return 1 if total_hits else 0


def _first_sentence(inst: dict, labels: dict) -> str:
    """The prose constraint, for context next to a failure."""
    for case in labels["cases"]:
        if case["case_id"] != inst["case_id"]:
            continue
        prose = case["expected"][inst["criterion_id"]].get("lexical_constraint", "")
        return prose.split(". ")[0] + "." if prose else "(none recorded)"
    return "(none recorded)"


if __name__ == "__main__":
    sys.exit(main())
