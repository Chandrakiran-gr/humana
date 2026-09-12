"""The fault injection controls, Task 3.4.

Each control must do the thing it claims and nothing more. The point of both
is that the *handling* is real: the fault is injected at the input and the
rejection, the preserved reason and the incomplete state all come from the
pipeline rather than from a mock. If a control faked its output it would
demonstrate the mock.
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import (  # noqa: E402
    ClinicalStatus, ExtractedEvidence, FailureKind, ProcessingStatus,
    ReasonCode, ingest_case, load_criteria, verify_quotes,
)
from um_evidence.extract import CriterionExtraction  # noqa: E402
from um_evidence.faults import (  # noqa: E402
    Fault, OBSERVED_TRUNCATION, corrupt_first_quote, replay_truncation,
)

CASES = PROJECT_ROOT / "corpus" / "cases"


def real_result(case_id="MRI-005", criterion_id="C3"):
    """A genuine verified citation from the corpus reference."""
    labels = json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())
    case = next(c for c in labels["cases"] if c["case_id"] == case_id)
    q = case["expected"][criterion_id]["acceptable_evidence"]["units"][0]["quotes"][0]
    return {
        "criterion_id": criterion_id,
        "clinical_status": "MET",
        "evidence": [{"document_id": q["document_id"], "quote": q["quote"],
                      "role": "supporting", "verified": True}],
    }


class UnverifiableQuoteTests(unittest.TestCase):
    def test_the_corrupted_quote_no_longer_resolves(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        before = real_result()
        self.assertEqual(
            len(packet.locate(before["evidence"][0]["quote"])), 1,
            "the uncorrupted quote must resolve, or the test proves nothing")
        after, injection = corrupt_first_quote([before], packet)
        self.assertIs(injection.fault, Fault.UNVERIFIABLE_QUOTE)
        self.assertEqual(len(packet.locate(after[0]["evidence"][0]["quote"])), 0)

    def test_step_4_rejects_it_and_preserves_the_reason(self) -> None:
        """The rejection comes from verify.py, not from the injector."""
        packet = ingest_case("MRI-005", CASES)
        after, _ = corrupt_first_quote([real_result()], packet)
        item = after[0]["evidence"][0]
        extraction = CriterionExtraction(
            criterion_id="C3", clinical_status=ClinicalStatus.MET,
            processing_status=ProcessingStatus.COMPLETE,
            evidence=[ExtractedEvidence(item["document_id"], item["quote"],
                                        item["role"])])
        verified = verify_quotes(extraction, packet)
        self.assertEqual(len(verified.rejected_evidence), 1)
        self.assertIn("not a citation", verified.rejected_evidence[0].detail)
        self.assertIn(ReasonCode.UNVERIFIABLE_QUOTE, verified.reason_codes)

    def test_a_conclusion_losing_its_only_support_is_downgraded(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        after, _ = corrupt_first_quote([real_result()], packet)
        item = after[0]["evidence"][0]
        verified = verify_quotes(CriterionExtraction(
            criterion_id="C3", clinical_status=ClinicalStatus.MET,
            processing_status=ProcessingStatus.COMPLETE,
            evidence=[ExtractedEvidence(item["document_id"], item["quote"],
                                        item["role"])]), packet)
        self.assertIs(verified.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertIs(verified.extracted_status, ClinicalStatus.MET)
        self.assertTrue(verified.downgraded)

    def test_only_one_quote_is_corrupted(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        two = [real_result("MRI-005", "C3"), real_result("MRI-005", "C1")]
        after, _ = corrupt_first_quote(two, packet)
        corrupted = sum(1 for r in after for e in r["evidence"]
                        if len(packet.locate(e["quote"])) == 0)
        self.assertEqual(corrupted, 1, "the control alters exactly one span")

    def test_it_is_deterministic(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        a, _ = corrupt_first_quote([real_result()], packet)
        b, _ = corrupt_first_quote([real_result()], packet)
        self.assertEqual(a, b, "a demonstration that varies is not one")

    def test_a_case_with_nothing_to_corrupt_says_so(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        _, injection = corrupt_first_quote(
            [{"criterion_id": "C4", "clinical_status": "AMBIGUOUS",
              "evidence": []}], packet)
        self.assertIn("no verified quote", injection.detail)


class TruncationTests(unittest.TestCase):
    def test_it_reproduces_the_observed_failure(self) -> None:
        """Replayed from a real run, not invented."""
        artifact = PROJECT_ROOT / "runs" / "20260910T205411Z_eval_batch8_A.json"
        self.assertTrue(artifact.exists(), "the source artifact must exist")
        data = json.loads(artifact.read_text())
        case = next(c for c in data["cases"] if c["case_id"] == "MRI-007")
        observed = case["extraction"]["results"]
        self.assertTrue(all(r["clinical_status"] is None for r in observed))

        replayed, injection = replay_truncation([r["criterion_id"] for r in observed])
        self.assertIs(injection.fault, Fault.OUTPUT_TRUNCATION)
        self.assertIn("Replayed, not invented", injection.provenance)
        self.assertEqual(len(replayed), len(observed))
        for r, o in zip(replayed, observed):
            self.assertEqual(r.criterion_id, o["criterion_id"])
            self.assertIsNone(r.clinical_status)
            self.assertEqual(r.failure_kind.value, o["failure_kind"])
            self.assertIn(OBSERVED_TRUNCATION, r.detail)

    def test_no_criterion_receives_a_clinical_status(self) -> None:
        """A system failure must never surface as a clinical finding.

        None is not AMBIGUOUS: AMBIGUOUS says the record was read and did not
        settle the question, None says no judgement was reached at all.
        """
        replayed, _ = replay_truncation(["C1", "C2", "C3", "C4", "C5"])
        for r in replayed:
            self.assertIsNone(r.clinical_status)
            self.assertIsNot(r.clinical_status, ClinicalStatus.AMBIGUOUS)
            self.assertIs(r.processing_status, ProcessingStatus.FAILED)
            self.assertIn(ReasonCode.PROCESSING_ERROR, r.reason_codes)

    def test_it_is_deterministic(self) -> None:
        a, _ = replay_truncation(["C1", "C2"])
        b, _ = replay_truncation(["C1", "C2"])
        self.assertEqual([r.as_dict() for r in a], [r.as_dict() for r in b])


class LabellingTests(unittest.TestCase):
    def test_both_controls_are_labelled_as_deliberate(self) -> None:
        """Spec Section 13: fault injection is labeled as such.

        The wording is aimed at the reviewer rather than at the spec. It
        used to read "Injected fault", which is the system's word for it;
        "Deliberate failure" says the same thing to someone who has not read
        the specification. What must not change is that the label states the
        failure was caused on purpose.
        """
        from um_evidence.faults import LABELS, NOT_A_RATE
        for fault, (headline, detail) in LABELS.items():
            self.assertTrue(headline.startswith("Deliberate failure"),
                            f"{fault} is not labelled as deliberate")
            self.assertTrue(detail.strip())
        self.assertIn("not an observed error rate", NOT_A_RATE.lower())

    def test_the_reviewer_wording_carries_no_internal_detail(self) -> None:
        """The banner is over a clinical screen. An enum, a run artifact, an
        observation date or a source case id tells a reviewer nothing and
        makes the screen read as a developer tool."""
        from um_evidence.faults import LABELS, OBSERVED_TRUNCATION_SOURCE
        import re
        for fault, (headline, detail) in LABELS.items():
            text = f"{headline} {detail}"
            self.assertNotRegex(text, r"\b[A-Z][A-Z_]{3,}\b",
                                f"{fault} label contains an enum name")
            self.assertNotIn(".json", text)
            self.assertNotIn("2026", text)
            self.assertNotIn("Step ", text)
            for case in ("MRI-", "TKA-", "LF-"):
                self.assertNotIn(case, text)
        # The provenance still exists, for run details.
        self.assertIn(".json", OBSERVED_TRUNCATION_SOURCE)

    def test_the_interface_labels_them_too(self) -> None:
        """The app renders the headline from LABELS rather than hardcoding
        it, so the check is that it surfaces the headline and carries the
        caveat, not that a literal string appears."""
        app = (PROJECT_ROOT / "app.py").read_text()
        self.assertIn("injection.headline", app,
                      "the injected-fault headline must reach the screen")
        self.assertIn("NOT_A_RATE", app,
                      "the banner must carry the standing caveat")
        # Twice: once on the sidebar control, once on the active banner. The
        # sidebar spells it out; the banner takes it from the constant.
        self.assertIn("not an observed error rate", app.lower())

    def test_the_interface_does_not_cite_the_specification(self) -> None:
        """A spec section number means nothing to a reviewer, who has no way
        to look it up."""
        import ast
        import re
        tree = ast.parse((PROJECT_ROOT / "app.py").read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            if node.value.lstrip().startswith(("Reviewer interface",
                                               "The display wording",
                                               "Counts by status")):
                continue          # module and function docstrings
            self.assertNotRegex(
                node.value, r"Spec Section \d+",
                f"line {node.lineno} renders a specification reference")


if __name__ == "__main__":
    unittest.main()
