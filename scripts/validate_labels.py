#!/usr/bin/env python3
"""Invariant checks for the Stage 1 reference labels.

Validates corpus/labels.json against the rules recorded in its own _meta block
and in docs/PROTOTYPE_SPEC.md. This supports the Task 1.3 manual check; it does
not replace it. A packet can satisfy every check here and still fail to support
its label, which is what the manual read is for.

    python3 scripts/validate_labels.py
    python3 scripts/validate_labels.py --quiet

Exit status 0 if every invariant holds, 1 otherwise.
"""

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

STATUSES = {"MET", "NOT_MET", "AMBIGUOUS", "NOT_APPLICABLE"}
REFERENCE_REASON_CODES = {
    "MISSING_EVIDENCE",
    "CONFLICTING_EVIDENCE",
    "VAGUE_DURATION",
    "INSUFFICIENT_CONTEXT",
}
# Runtime outcomes. These describe pipeline behaviour and can never be a
# property of a document set, so they must not appear in a reference label.
RUNTIME_ONLY_REASON_CODES = {
    "UNVERIFIABLE_QUOTE",
    "UNSUPPORTED_CONCLUSION",
    "PROCESSING_ERROR",
}
INTERPRETATIONS = {"positional", "derived", "semantic"}
JUSTIFICATION_FIELDS = ("contradiction", "record_complete", "no_exception")

SPLITS = ("development", "held_out_test", "transfer")
# Read from the criteria file rather than pinned here. A literal in this
# script would be a second source for the version, which is the failure mode
# recorded in .env.example: a value that is correct when written and silently
# describes something that no longer exists after the next revision.
CRITERIA_SET_VERSION = json.loads(
    (PROJECT_ROOT / "criteria" / "criteria_sets.json").read_text(
        encoding="utf-8"))["_meta"]["criteria_set_version"]
EXPECTED_CASES = {"development": 15, "held_out_test": 9, "transfer": 5}
EXPECTED_INSTANCES = {"development": 89, "held_out_test": 55, "transfer": 45}

REQUIRED_SCENARIOS = {
    "evidence in an unrelated section": {"unrelated_section", "buried_evidence"},
    "duration without dates": {"vague_duration"},
    "contradictory statements": {"contradiction"},
    "near-threshold documentation": {"near_threshold_duration"},
    "requirements never addressed": {"silent_absence"},
    "concise versus verbose": {"density_pair"},
}


def load_criteria_sets(path: Path) -> dict[str, dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        s["procedure_id"]: {c["id"]: c for c in s["criteria"]}
        for s in payload["criteria_sets"]
    }


def instances(case: dict) -> dict[str, dict]:
    """Criterion expectations, skipping _note keys used for commentary."""
    return {k: v for k, v in case["expected"].items() if not k.startswith("_")}


def has_exception_pathway(criteria: dict, procedure_id: str) -> bool:
    for s in criteria["criteria_sets"]:
        if s["procedure_id"] == procedure_id:
            return bool(s.get("has_exception_pathway"))
    return False


def check_case(case: dict, sets: dict, criteria: dict, by_case: dict) -> list[str]:
    failures = []

    def check(condition: bool, message: str) -> None:
        if not condition:
            failures.append(message)

    case_id = case["case_id"]
    procedure_id = case["procedure_id"]

    check(procedure_id in sets, f"{case_id}: unknown procedure {procedure_id}")
    if procedure_id not in sets:
        return failures

    expected = instances(case)
    check(sorted(expected) == sorted(sets[procedure_id]),
          f"{case_id}: criteria do not match set {procedure_id}")
    check(case["criteria_set_version"] == CRITERIA_SET_VERSION, f"{case_id}: unexpected criteria_set_version")
    check(case["reference_version"] == "1.0", f"{case_id}: unexpected reference_version")
    check(bool(case.get("scenario_tags")), f"{case_id}: no scenario_tags")
    check(bool(case.get("notes", "").strip()), f"{case_id}: empty notes")

    # Copies, ablations, and paraphrases stay in the parent case's split.
    # Spec Section 6.
    parent_id = case["parent_case_id"]
    if parent_id is not None:
        check(parent_id in by_case, f"{case_id}: parent {parent_id} not found")
        if parent_id in by_case:
            parent = by_case[parent_id]
            check(parent["split"] == case["split"], f"{case_id}: parent is in a different split")
            check(parent["procedure_id"] == procedure_id,
                  f"{case_id}: parent has a different procedure")

    for criterion_id, expectation in expected.items():
        at = f"{case_id}.{criterion_id}"
        status = expectation["clinical_status"]
        reason_codes = expectation["reason_codes"]
        units = expectation["evidence_units_required"]
        requirement = expectation["evidence_requirement"]

        check(status in STATUSES, f"{at}: bad clinical_status {status!r}")
        check(not RUNTIME_ONLY_REASON_CODES & set(reason_codes),
              f"{at}: runtime-only reason code in a reference label")
        check(not set(reason_codes) - REFERENCE_REASON_CODES,
              f"{at}: unknown reason code {reason_codes}")
        check(bool(expectation.get("evidence_note", "").strip()), f"{at}: empty evidence_note")

        if status == "AMBIGUOUS":
            check(len(reason_codes) == 1, f"{at}: AMBIGUOUS needs exactly one reason code")
        else:
            check(reason_codes == [], f"{at}: {status} must carry an empty reason_codes list")

        # A waived criterion is out of scope, not failed and not unresolved.
        # NOT_APPLICABLE and a waiver imply each other, checked both ways.
        waived_here = bool(expectation.get("waived_by_exception"))
        check((status == "NOT_APPLICABLE") == waived_here,
              f"{at}: NOT_APPLICABLE and waived_by_exception must agree")
        if status == "NOT_APPLICABLE":
            check(units == 0 and requirement == "NONE",
                  f"{at}: a waived criterion carries no required evidence")
            alt = expectation.get("if_not_waived")
            check(isinstance(alt, dict) and alt.get("clinical_status") in STATUSES,
                  f"{at}: waived criterion must record if_not_waived for diagnostics")

        # Absence of located evidence is never a finding about the record.
        # Scoped to AMBIGUOUS, because NOT_APPLICABLE also carries zero units.
        check(("MISSING_EVIDENCE" in reason_codes) == (units == 0 and status == "AMBIGUOUS"),
              f"{at}: MISSING_EVIDENCE and zero AMBIGUOUS units must agree")
        # A contradiction needs both sides. Spec Section 3.
        check("CONFLICTING_EVIDENCE" not in reason_codes or units >= 2,
              f"{at}: a contradiction needs both sides")

        expected_requirement = "NONE" if units == 0 else "ALTERNATIVE" if units == 1 else "COMPOSITE"
        check(requirement == expected_requirement,
              f"{at}: {units} units but evidence_requirement {requirement}")

        # NOT_MET carries a high bar. Spec Section 4.
        if status == "NOT_MET":
            check(units > 0, f"{at}: NOT_MET cannot rest on zero evidence")
            justification = expectation.get("not_met_justification") or {}
            for field in JUSTIFICATION_FIELDS:
                check(bool(justification.get(field, "").strip()),
                      f"{at}: NOT_MET missing justification.{field}")

        # Task 2.3b. Every scorable instance carries the passages that
        # satisfy it, resolved to spans. Without these, evidence recall and
        # precision are the primary comparison metric and are uncomputable.
        if status != "NOT_APPLICABLE":
            acceptable = expectation.get("acceptable_evidence")
            check(isinstance(acceptable, dict),
                  f"{at}: no acceptable_evidence; recall cannot be scored")
            if isinstance(acceptable, dict):
                unit_list = acceptable.get("units", [])
                check(len(unit_list) == units,
                      f"{at}: {len(unit_list)} acceptable units against "
                      f"evidence_units_required {units}")
                for unit in unit_list:
                    check(bool(unit.get("quotes")),
                          f"{at}: unit {unit.get('unit')} lists no quote")
                    check(unit.get("role") in ("supporting", "contradicting"),
                          f"{at}: unit {unit.get('unit')} has role "
                          f"{unit.get('role')!r}")
                # A contradiction needs both sides present, not merely two units.
                if "CONFLICTING_EVIDENCE" in reason_codes:
                    roles = {u.get("role") for u in unit_list}
                    check(roles == {"supporting", "contradicting"},
                          f"{at}: CONFLICTING_EVIDENCE but the units are all "
                          f"{roles}; a contradiction needs both sides")

        if "interpretation" in expectation:
            interpretation = expectation["interpretation"]
            check(interpretation in INTERPRETATIONS, f"{at}: bad interpretation {interpretation!r}")
            check(units > 0, f"{at}: interpretation set on an instance with no evidence")
            if interpretation == "semantic":
                check(bool(expectation.get("lexical_constraint", "").strip()),
                      f"{at}: semantic instance needs a lexical_constraint for Task 1.2")
                # A semantic instance claims the criterion cannot be satisfied
                # without the interpretation. That is a claim about every other
                # path through the criterion, and it is easy to assert and easy
                # to get wrong. TKA-004 C4 was marked semantic while physical
                # therapy, an explicitly listed modality, sat in the packet with
                # a documented outcome; nothing caught it until the case was run
                # and the model took the easy path. The claim must therefore be
                # stated and attributed, not assumed.
                manual = expectation.get("manual_only_constraint", "")
                check("no_bypass" in expectation or "bypass" in manual.lower()
                      or "easier than" in manual.lower(),
                      f"{at}: semantic instance must record whether a non-semantic "
                      f"path satisfies the same criterion. Add no_bypass stating "
                      f"which other paths were checked and ruled out.")

        # A prose constraint alone cannot be checked against a generated packet.
        # Anything carrying one must also carry a machine-readable term list and
        # an explicit statement of what the term list cannot cover, so a clean
        # automated result is never mistaken for a satisfied constraint.
        if expectation.get("lexical_constraint"):
            terms = expectation.get("prohibited_terms")
            check(isinstance(terms, list) and len(terms) > 0,
                  f"{at}: lexical_constraint without prohibited_terms is unenforceable")
            if isinstance(terms, list):
                check(all(isinstance(t, str) and t.strip() for t in terms),
                      f"{at}: prohibited_terms must be non-empty strings")
                check(len(terms) == len({t.lower() for t in terms}),
                      f"{at}: duplicate prohibited_terms")
            check(bool(expectation.get("manual_only_constraint", "").strip()),
                  f"{at}: needs manual_only_constraint naming what the term list cannot check")
            scope = expectation.get("prohibited_scope", "packet")
            check(isinstance(scope, str) and scope.strip(),
                  f"{at}: prohibited_scope must be 'packet', a glob, or '!' plus a glob")

        waived = expectation.get("waived_by_exception")
        if waived:
            check(waived in expected, f"{at}: waived_by_exception names unknown criterion {waived}")
            check(has_exception_pathway(criteria, procedure_id),
                  f"{at}: waiver in a criteria set with no exception pathway")

    return failures


def tally(cases: list[dict]) -> tuple[Counter, defaultdict, Counter, Counter, int]:
    status = Counter()
    per_split = defaultdict(Counter)
    reason_codes = Counter()
    requirements = Counter()
    total_units = 0
    for case in cases:
        for expectation in instances(case).values():
            status[expectation["clinical_status"]] += 1
            per_split[case["split"]][expectation["clinical_status"]] += 1
            per_split[case["split"]]["instances"] += 1
            for code in expectation["reason_codes"]:
                reason_codes[code] += 1
            requirements[expectation["evidence_requirement"]] += 1
            total_units += expectation["evidence_units_required"]
    return status, per_split, reason_codes, requirements, total_units


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--labels", default="corpus/labels.json")
    ap.add_argument("--criteria", default="criteria/criteria_sets.json")
    ap.add_argument("--quiet", action="store_true", help="Print failures only.")
    args = ap.parse_args()

    labels_path = PROJECT_ROOT / args.labels
    criteria_path = PROJECT_ROOT / args.criteria
    for path in (labels_path, criteria_path):
        if not path.exists():
            print(f"[FAIL] Not found: {path}")
            return 1

    labels = json.loads(labels_path.read_text(encoding="utf-8"))
    criteria = json.loads(criteria_path.read_text(encoding="utf-8"))
    sets = load_criteria_sets(criteria_path)
    cases = labels["cases"]
    by_case = {c["case_id"]: c for c in cases}

    failures = []

    case_ids = [c["case_id"] for c in cases]
    if len(case_ids) != len(set(case_ids)):
        failures.append("duplicate case_id")
    for split, expected_count in EXPECTED_CASES.items():
        found = sum(1 for c in cases if c["split"] == split)
        if found != expected_count:
            failures.append(f"{split}: expected {expected_count} cases, found {found}")

    for case in cases:
        failures.extend(check_case(case, sets, criteria, by_case))

    # A MET exception trigger forces every criterion it waives to
    # NOT_APPLICABLE. The earlier waiver check only tested that NOT_APPLICABLE
    # and waived_by_exception agreed, which a label that simply forgets the
    # waiver satisfies vacuously. A blind reader found the gap on LF-204 C3,
    # where the exception fired and the label still read MET.
    triggers = {}
    for s in criteria["criteria_sets"]:
        m = re.search(r"If (C\d+) is MET, then ((?:C\d+(?:, | and )?)+) (?:is|are) waived",
                      s.get("exception_note", ""))
        if m:
            triggers[s["procedure_id"]] = (m.group(1), re.findall(r"C\d+", m.group(2)))
    for case in cases:
        trig = triggers.get(case["procedure_id"])
        if not trig:
            continue
        trigger_id, waived_ids = trig
        exp = instances(case)
        if exp.get(trigger_id, {}).get("clinical_status") == "MET":
            for w in waived_ids:
                if w in exp and exp[w]["clinical_status"] != "NOT_APPLICABLE":
                    failures.append(
                        f"{case['case_id']}.{w}: {trigger_id} is MET, so the exception "
                        f"pathway waives this criterion and it must be NOT_APPLICABLE. "
                        f"Found {exp[w]['clinical_status']}.")

    status, per_split, reason_codes, requirements, total_units = tally(cases)

    for split, expected_count in EXPECTED_INSTANCES.items():
        found = per_split[split]["instances"]
        if found != expected_count:
            failures.append(f"{split}: expected {expected_count} criterion instances, found {found}")

    # The recorded distribution must match what is actually in the file, so a
    # later edit cannot silently leave the summary stale.
    recorded = labels["_meta"]["distribution_at_authoring"]
    for label, expected_value, actual_value in (
        ("total_criterion_instances", recorded["total_criterion_instances"], sum(status.values())),
        ("clinical_status", recorded["clinical_status"], dict(status)),
        ("reason_codes", recorded["reason_codes"], dict(reason_codes)),
        ("critical_instances_met_or_not_met",
         recorded["critical_instances_met_or_not_met"], status["MET"] + status["NOT_MET"]),
        ("total_reference_evidence_units", recorded["total_reference_evidence_units"], total_units),
        ("evidence_requirement", recorded["evidence_requirement"], dict(requirements)),
    ):
        if expected_value != actual_value:
            failures.append(f"_meta.{label} is stale: recorded {expected_value}, actual {actual_value}")
    for split in SPLITS:
        if recorded["by_split"][split] != dict(per_split[split]):
            failures.append(f"_meta.by_split.{split} is stale")

    used_tags = {t for c in cases for t in c["scenario_tags"]}
    defined_tags = set(labels["_meta"]["scenario_tags"])
    if used_tags - defined_tags:
        failures.append(f"scenario tags used but undefined: {sorted(used_tags - defined_tags)}")
    if defined_tags - used_tags:
        failures.append(f"scenario tags defined but unused: {sorted(defined_tags - used_tags)}")

    for label, tags in REQUIRED_SCENARIOS.items():
        if not any(tags & set(c["scenario_tags"]) for c in cases):
            failures.append(f"required scenario not covered: {label}")

    # Spec Section 13 item 2 needs a semantic instance available to demonstrate.
    semantic_dev = [
        f"{c['case_id']} {k}"
        for c in cases if c["split"] == "development"
        for k, v in instances(c).items() if v.get("interpretation") == "semantic"
    ]
    if not semantic_dev:
        failures.append("no semantic instance in development for the Spec Section 13 demonstration")

    if not args.quiet:
        total = sum(status.values())
        print(f"cases {len(cases)}   criterion instances {total}   "
              f"reference evidence units {total_units}")
        for split in SPLITS:
            counts = per_split[split]
            case_count = sum(1 for c in cases if c["split"] == split)
            independent = sum(1 for c in cases
                              if c["split"] == split and c["parent_case_id"] is None)
            print(f"  {split:14} cases {case_count:2} (independent {independent})  "
                  f"instances {counts['instances']:3}   "
                  f"MET {counts['MET']:3}  AMBIGUOUS {counts['AMBIGUOUS']:3}  "
                  f"NOT_MET {counts['NOT_MET']:2}  N/A {counts['NOT_APPLICABLE']:2}")
        print("  " + "  ".join(
            f"{name} {status[name]} ({status[name] / total * 100:.1f}%)"
            for name in ("MET", "AMBIGUOUS", "NOT_MET", "NOT_APPLICABLE")))
        print(f"  scorable instances, excluding NOT_APPLICABLE: {total - status['NOT_APPLICABLE']}")
        print(f"  reason codes  {dict(reason_codes.most_common())}")
        print(f"  semantic instances in development: {', '.join(semantic_dev)}")
        print()

    if failures:
        print(f"[FAIL] {len(failures)} invariant(s) violated:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("[OK] All invariants hold.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
