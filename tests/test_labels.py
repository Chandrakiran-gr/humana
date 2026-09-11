"""Regression tests for the Stage 1 reference labels.

scripts/validate_labels.py is the full invariant sweep and is what you run while
editing labels. These tests pin the handful of properties that must survive every
future change, so a later edit that quietly relaxes one fails CI rather than
surfacing at scoring time.
"""

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LABELS_PATH = PROJECT_ROOT / "corpus" / "labels.json"
CRITERIA_PATH = PROJECT_ROOT / "criteria" / "criteria_sets.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def instances(case: dict) -> dict:
    return {k: v for k, v in case["expected"].items() if not k.startswith("_")}


class ValidatorTests(unittest.TestCase):
    def test_validator_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "validate_labels.py"), "--quiet"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_document_cites_a_date_later_than_itself(self) -> None:
        # A note cannot review a report written after it. This class of error
        # survived two inspections by eye and was found by an independent
        # reader, so it is guarded mechanically rather than by reading.
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "check_packet_dates.py")],
            capture_output=True,
            text=True,
        )
        forward = result.stdout.split("=== MIXED")[0]
        self.assertIn("none", forward, result.stdout)

    def test_mixed_date_formats_are_declared(self) -> None:
        # Cross-institution date mixing is realistic and is kept, but every
        # packet carrying it must be tagged so a date-related failure is
        # attributable. Within-document and same-institution mixing are errors.
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "check_packet_dates.py")],
            capture_output=True,
            text=True,
        )
        mixed = result.stdout.split("=== MIXED")[1] if "=== MIXED" in result.stdout else ""
        flagged = {line.strip() for line in mixed.splitlines()
                   if line.startswith("  ") and not line.startswith("      ")
                   and line.strip() and line.strip() != "none"}
        tagged = {c["case_id"] for c in load(LABELS_PATH)["cases"]
                  if "mixed_date_convention" in c["scenario_tags"]}
        self.assertEqual(flagged, tagged,
                         f"packets with mixed formats {flagged} must equal tagged {tagged}")


    def test_criteria_prose_is_not_quoted_from_the_packets(self) -> None:
        # Every string in criteria_sets.json is sent to the model at runtime
        # alongside the packet. A worked example quoted verbatim from a document
        # the model is about to read hands it the answer next to the question,
        # in production as well as in evaluation.
        result = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "check_criteria_contamination.py")],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class SplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load(LABELS_PATH)["cases"]

    def test_split_sizes_are_as_assigned(self) -> None:
        counts = Counter(c["split"] for c in self.cases)
        self.assertEqual(counts["development"], 15)
        self.assertEqual(counts["held_out_test"], 9)
        self.assertEqual(counts["transfer"], 5)

    def test_held_out_carries_the_criterion_instances_the_threshold_assumes(self) -> None:
        # Spec Section 9 states the adoption threshold over roughly 48 criterion
        # instances across 8 held-out cases. If this drifts, the threshold no
        # longer describes the test it is applied to.
        total = sum(len(instances(c)) for c in self.cases if c["split"] == "held_out_test")
        scorable = sum(1 for c in self.cases if c["split"] == "held_out_test"
                       for e in instances(c).values()
                       if e["clinical_status"] != "NOT_APPLICABLE")
        self.assertEqual(total, 55)
        self.assertEqual(scorable, 53)

    def test_variants_stay_in_the_parent_split(self) -> None:
        by_id = {c["case_id"]: c for c in self.cases}
        for case in self.cases:
            parent_id = case["parent_case_id"]
            if parent_id is None:
                continue
            with self.subTest(case=case["case_id"]):
                self.assertIn(parent_id, by_id)
                self.assertEqual(by_id[parent_id]["split"], case["split"])

    def test_transfer_is_a_procedure_unused_during_development(self) -> None:
        developed = {c["procedure_id"] for c in self.cases if c["split"] != "transfer"}
        transfer = {c["procedure_id"] for c in self.cases if c["split"] == "transfer"}
        self.assertFalse(developed & transfer)


class HardConstraintTests(unittest.TestCase):
    """The constraints in CLAUDE.md that must never be relaxed."""

    def setUp(self) -> None:
        self.cases = load(LABELS_PATH)["cases"]
        self.criteria = load(CRITERIA_PATH)

    def test_missing_evidence_never_becomes_not_met(self) -> None:
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if expectation["evidence_units_required"] == 0:
                    with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                        self.assertNotEqual(expectation["clinical_status"], "NOT_MET")
                        # Zero units means either genuine absence or a waived
                        # criterion that was never asked.
                        if expectation["clinical_status"] != "NOT_APPLICABLE":
                            self.assertIn("MISSING_EVIDENCE", expectation["reason_codes"])

    def test_waived_criteria_are_not_applicable_and_unscored(self) -> None:
        # A criterion waived by an exception is out of scope, not failed and not
        # unresolved. It cannot be MET, NOT_MET, or AMBIGUOUS.
        found = 0
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                waived = bool(expectation.get("waived_by_exception"))
                na = expectation["clinical_status"] == "NOT_APPLICABLE"
                with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                    self.assertEqual(waived, na)
                if na:
                    found += 1
                    with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                        self.assertEqual(expectation["evidence_units_required"], 0)
                        self.assertEqual(expectation["reason_codes"], [])
                        # The unscored assessment is kept for diagnostics.
                        self.assertIn("if_not_waived", expectation)
        self.assertGreater(found, 0)

    def test_waivers_only_where_the_set_has_a_pathway(self) -> None:
        pathways = {s["procedure_id"]: bool(s.get("has_exception_pathway"))
                    for s in self.criteria["criteria_sets"]}
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if expectation.get("waived_by_exception"):
                    with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                        self.assertTrue(pathways[case["procedure_id"]])

    def test_every_not_met_states_all_three_grounds(self) -> None:
        # Spec Section 4: affirmatively contradictory, record complete on the
        # point, and no applicable exception.
        found = 0
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if expectation["clinical_status"] != "NOT_MET":
                    continue
                found += 1
                with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                    justification = expectation.get("not_met_justification", {})
                    for field in ("contradiction", "record_complete", "no_exception"):
                        self.assertTrue(justification.get(field, "").strip())
        self.assertGreater(found, 0)

    def test_not_met_stays_rare(self) -> None:
        status = Counter(e["clinical_status"] for c in self.cases for e in instances(c).values())
        total = sum(status.values())
        self.assertLess(status["NOT_MET"] / total, 0.10)

    def test_criteria_text_does_not_make_silence_satisfy_an_exclusion(self) -> None:
        # A satisfied_by clause reading "absence of documented X" tells a model
        # that a silent packet satisfies the criterion, which contradicts the
        # rule that absence resolves to AMBIGUOUS. This defect was present on
        # three criteria at version 1.0.0.
        for s in self.criteria["criteria_sets"]:
            for cr in s["criteria"]:
                if cr["evidence_type"] != "exclusion":
                    continue
                with self.subTest(at=f"{s['procedure_id']}.{cr['id']}"):
                    sat = cr["satisfied_by"].lower()
                    self.assertNotRegex(
                        sat, r"absence of (documented|recent)",
                        "satisfied_by makes silence satisfy an exclusion")
                    self.assertTrue(cr.get("trap_note", "").strip(),
                                    "an exclusion criterion needs a trap_note")

    def test_no_runtime_reason_codes_in_reference_labels(self) -> None:
        runtime_only = {"UNVERIFIABLE_QUOTE", "UNSUPPORTED_CONCLUSION", "PROCESSING_ERROR"}
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                    self.assertFalse(runtime_only & set(expectation["reason_codes"]))

    def test_no_coverage_determination_vocabulary_anywhere(self) -> None:
        # CLAUDE.md: the output vocabulary is evidence status only.
        raw = LABELS_PATH.read_text(encoding="utf-8").lower()
        for banned in ('"recommendation"', '"decision"', '"approved"', '"denied"', '"score"'):
            with self.subTest(field=banned):
                self.assertNotIn(banned, raw)

    def test_evidence_is_a_list_not_a_single_quote(self) -> None:
        # A contradiction needs both sides; a derived duration needs both dates.
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if "CONFLICTING_EVIDENCE" in expectation["reason_codes"]:
                    with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                        self.assertGreaterEqual(expectation["evidence_units_required"], 2)


class DistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cases = load(LABELS_PATH)["cases"]
        self.status = Counter(
            e["clinical_status"] for c in self.cases for e in instances(c).values()
        )

    def test_set_discriminates(self) -> None:
        # A corpus skewed to MET cannot distinguish a good extractor from one
        # that answers MET by default.
        total = sum(self.status.values())
        self.assertLess(self.status["MET"] / total, 0.60)
        self.assertGreater(self.status["AMBIGUOUS"] / total, 0.30)

    def test_every_split_has_a_reference_not_met(self) -> None:
        # Without one, the critical error "reference NOT_MET output as MET" has
        # no denominator at all in that split.
        for split in ("development", "held_out_test", "transfer"):
            with self.subTest(split=split):
                found = sum(
                    1 for c in self.cases if c["split"] == split
                    for e in instances(c).values() if e["clinical_status"] == "NOT_MET"
                )
                self.assertGreater(found, 0)


class ScenarioCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.labels = load(LABELS_PATH)
        self.cases = self.labels["cases"]
        self.tags = {t for c in self.cases for t in c["scenario_tags"]}

    def test_required_scenarios_are_present(self) -> None:
        for label, required in {
            "unrelated section": {"unrelated_section", "buried_evidence"},
            "duration without dates": {"vague_duration"},
            "contradictory statements": {"contradiction"},
            "near-threshold": {"near_threshold_duration"},
            "never addressed": {"silent_absence"},
            "concise versus verbose": {"density_pair"},
        }.items():
            with self.subTest(scenario=label):
                self.assertTrue(required & self.tags)

    def test_semantic_instance_available_for_the_demonstration(self) -> None:
        # Spec Section 13 item 2. Positionally buried evidence does not satisfy
        # this; the criterion's vocabulary has to be absent.
        semantic = [
            (c["case_id"], k) for c in self.cases if c["split"] == "development"
            for k, v in instances(c).items() if v.get("interpretation") == "semantic"
        ]
        self.assertTrue(semantic)

    def test_semantic_instances_carry_a_lexical_constraint(self) -> None:
        # Task 1.2 needs the prohibited terms named, or document generation
        # dissolves the instance.
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if expectation.get("interpretation") == "semantic":
                    with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                        self.assertTrue(expectation.get("lexical_constraint", "").strip())

    def test_lexical_constraints_are_machine_checkable(self) -> None:
        # Prose alone cannot be checked against a packet. Every constraint needs
        # a term list scripts/check_lexical_constraints.py can search for.
        found = 0
        for case in self.cases:
            for criterion_id, expectation in instances(case).items():
                if not expectation.get("lexical_constraint"):
                    continue
                found += 1
                with self.subTest(at=f"{case['case_id']}.{criterion_id}"):
                    terms = expectation.get("prohibited_terms")
                    self.assertIsInstance(terms, list)
                    self.assertTrue(terms)
                    self.assertTrue(all(isinstance(t, str) and t.strip() for t in terms))
                    # And an explicit statement of what greping cannot cover, so
                    # a clean run is never read as a satisfied constraint.
                    self.assertTrue(expectation.get("manual_only_constraint", "").strip())
        self.assertEqual(found, 7)

    def test_prohibited_terms_do_not_collide_within_a_case(self) -> None:
        # A term prohibited for one criterion must not be required wording for
        # another in the same packet, unless the scopes keep them apart.
        for case in self.cases:
            packet_wide = {}
            for criterion_id, expectation in instances(case).items():
                if expectation.get("prohibited_scope", "packet") != "packet":
                    continue
                for term in expectation.get("prohibited_terms", []):
                    packet_wide.setdefault(term.lower(), []).append(criterion_id)
            for term, criteria in packet_wide.items():
                with self.subTest(case=case["case_id"], term=term):
                    # Same term banned by two criteria is fine and consistent.
                    # This asserts no term is banned packet-wide while also
                    # appearing in another instance's required evidence wording.
                    for other_id, other in instances(case).items():
                        if other_id in criteria:
                            continue
                        note = other.get("evidence_note", "").lower()
                        self.assertNotIn(
                            f" {term} ", note,
                            f"{case['case_id']}: {term!r} banned by {criteria} "
                            f"but appears in {other_id} evidence_note",
                        )


class CriteriaSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.criteria = load(CRITERIA_PATH)
        self.cases = load(LABELS_PATH)["cases"]

    def test_every_case_labels_every_criterion(self) -> None:
        sets = {s["procedure_id"]: [c["id"] for c in s["criteria"]]
                for s in self.criteria["criteria_sets"]}
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(sorted(instances(case)), sorted(sets[case["procedure_id"]]))

    def test_criteria_set_version_is_consistent(self) -> None:
        # Must match the version the criteria file actually declares, so a
        # criteria edit cannot leave the labels pointing at a version that no
        # longer describes them.
        declared = self.criteria["_meta"]["criteria_set_version"]
        # Deliberately not pinned to a literal here. A literal in a test is a
        # second source for the version and drifts the same way .env.example
        # did. What is checked instead is that everything agrees with the file,
        # and that the version the file declares has a recorded reason.
        self.assertIn(declared,
                      [v["version"] for v in self.criteria["_meta"]["version_history"]],
                      "the declared version has no version_history entry")
        for s in self.criteria["criteria_sets"]:
            self.assertEqual(s["criteria_set_version"], declared)
        for case in self.cases:
            with self.subTest(case=case["case_id"]):
                self.assertEqual(case["criteria_set_version"], declared)


if __name__ == "__main__":
    unittest.main()
