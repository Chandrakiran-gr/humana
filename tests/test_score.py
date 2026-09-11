"""The scorer, fed known-wrong results and required to say so.

A scorer that cannot report a failure is the sixth checker. Five of five
written for this project passed on their first run while the defect they
existed to catch was present, so this one is built the other way round: every
test below constructs a result that is wrong in a specific way and asserts the
figure moves.

The construction matters. These are not canned score objects; they are real
`VerifiedCriterion` values scored against the real reference for MRI-005, so a
change to the acceptable sets or to the units-and-spans model breaks them.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import (  # noqa: E402
    ClinicalStatus, FailureKind, ProcessingStatus, ReasonCode, RunScore,
    format_report, load_labels, score_instance,
)
from um_evidence.verify import VerifiedCriterion, VerifiedEvidence  # noqa: E402
from um_evidence import ingest_case  # noqa: E402

CASES = PROJECT_ROOT / "corpus" / "cases"
LABELS = load_labels()


def expectation(case_id: str, criterion_id: str) -> dict:
    case = next(c for c in LABELS["cases"] if c["case_id"] == case_id)
    return case["expected"][criterion_id]


def evidence_for(case_id: str, criterion_id: str, unit_index: int = 0,
                 quote_index: int = 0) -> VerifiedEvidence:
    """A correct citation, taken from the reference's own acceptable set."""
    entry = expectation(case_id, criterion_id)["acceptable_evidence"]["units"][
        unit_index]["quotes"][quote_index]
    packet = ingest_case(case_id, CASES)
    doc = packet.by_id(entry["document_id"])
    span = doc.locate(entry["quote"])[0]
    return VerifiedEvidence(document_id=entry["document_id"], quote=entry["quote"],
                            role="supporting", span=span, verified=True)


def result(case_id: str, criterion_id: str, status, evidence=(),
           failure=FailureKind.NONE) -> VerifiedCriterion:
    return VerifiedCriterion(
        criterion_id=criterion_id, clinical_status=status,
        processing_status=(ProcessingStatus.COMPLETE if status
                           else ProcessingStatus.FAILED),
        reason_codes=[], evidence=list(evidence), failure_kind=failure)


def scored(case_id, criterion_id, status, evidence=(), failure=FailureKind.NONE):
    return score_instance(result(case_id, criterion_id, status, evidence, failure),
                          expectation(case_id, criterion_id), case_id, "development")


class ARightAnswerScoresRight(unittest.TestCase):
    """The control. Without it, every failing test below proves nothing."""

    def test_a_correct_result_scores_full_marks(self) -> None:
        # MRI-005 C2 is COMPOSITE at two units: the two visit-header dates.
        s = scored("MRI-005", "C2", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C2", 0),
                    evidence_for("MRI-005", "C2", 1)])
        self.assertEqual((s.units_required, s.units_recovered), (2, 2))
        self.assertEqual((s.spans_returned, s.spans_accepted), (2, 2))
        self.assertTrue(s.status_match)


class AWrongAnswerScoresWrong(unittest.TestCase):

    def test_a_wrong_status_does_not_match(self) -> None:
        s = scored("MRI-005", "C2", ClinicalStatus.NOT_MET,
                   [evidence_for("MRI-005", "C2", 0)])
        self.assertFalse(s.status_match)

    def test_recovering_one_of_two_units_scores_one_of_two(self) -> None:
        s = scored("MRI-005", "C2", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C2", 0)])
        self.assertEqual((s.units_required, s.units_recovered), (2, 1))

    def test_citing_nothing_recovers_nothing(self) -> None:
        s = scored("MRI-005", "C2", ClinicalStatus.MET)
        self.assertEqual(s.units_recovered, 0)
        self.assertEqual(s.spans_returned, 0)

    def test_an_unenumerated_span_is_a_precision_miss_and_is_named(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        doc = packet.usable[0]
        quote = "Electronically signed"
        span = doc.locate(quote)[0]
        s = scored("MRI-005", "C2", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C2", 0),
                    VerifiedEvidence(doc.document_id, quote, "supporting",
                                     span, True)])
        self.assertEqual((s.spans_returned, s.spans_accepted), (2, 1))
        self.assertEqual(len(s.unenumerated), 1)
        self.assertIn("Electronically signed", s.unenumerated[0])

    def test_an_unverified_span_counts_against_precision(self) -> None:
        s = scored("MRI-005", "C2", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C2", 0),
                    VerifiedEvidence("doc_x", "invented", "supporting",
                                     None, False, "did not verify")])
        self.assertEqual((s.spans_returned, s.spans_accepted, s.spans_verified),
                         (2, 1, 1))

    def test_repeated_spans_are_deduplicated(self) -> None:
        # Section 1 requires consistent deduplication. Citing one passage twice
        # must not inflate either the numerator or the denominator.
        one = evidence_for("MRI-005", "C2", 0)
        s = scored("MRI-005", "C2", ClinicalStatus.MET, [one, one])
        self.assertEqual((s.spans_returned, s.spans_accepted), (1, 1))

    def test_a_superset_is_flagged_without_costing_precision(self) -> None:
        # MRI-005 C1 needs one unit and lists three acceptable alternatives.
        s = scored("MRI-005", "C1", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C1", 0, 0),
                    evidence_for("MRI-005", "C1", 0, 1)])
        self.assertEqual((s.units_required, s.units_recovered), (1, 1))
        self.assertEqual((s.spans_returned, s.spans_accepted), (2, 2))
        self.assertTrue(s.is_superset)


class BoundariesDifferFromTheReference(unittest.TestCase):
    """The defect the first real run exposed.

    Every test in the two classes above cites the reference's own strings, so
    they passed while the scorer was matching on exact canonical equality and
    scoring the first development run at 23% recall against 87% status
    agreement. A model does not return the reference's boundaries. These tests
    use spans that differ from the reference on purpose.
    """

    def wider(self, case_id, criterion_id, before=0, after=0):
        """A citation of the same passage with different boundaries."""
        entry = expectation(case_id, criterion_id)["acceptable_evidence"][
            "units"][0]["quotes"][0]
        packet = ingest_case(case_id, CASES)
        doc = packet.by_id(entry["document_id"])
        start = max(0, entry["start"] - before)
        end = min(len(doc.canonical), entry["end"] + after)
        return VerifiedEvidence(
            document_id=entry["document_id"],
            quote=doc.canonical[start:end], role="supporting",
            span=doc.span(start, end), verified=True)

    def test_a_wider_quote_cites_the_same_passage(self) -> None:
        # What MRI-001 C5 actually returned: the section header plus the
        # sentence plus the one after it.
        s = scored("MRI-005", "C1", ClinicalStatus.MET,
                   [self.wider("MRI-005", "C1", before=15, after=40)])
        self.assertEqual(s.units_recovered, 1)
        self.assertEqual(s.spans_accepted, 1)

    def test_a_narrower_quote_cites_the_same_passage(self) -> None:
        s = scored("MRI-005", "C1", ClinicalStatus.MET,
                   [self.wider("MRI-005", "C1", after=-20)])
        self.assertEqual(s.units_recovered, 1)

    def test_a_span_that_barely_touches_does_not_count(self) -> None:
        entry = expectation("MRI-005", "C1")["acceptable_evidence"]["units"][0]["quotes"][0]
        packet = ingest_case("MRI-005", CASES)
        doc = packet.by_id(entry["document_id"])
        # Overlaps by two characters at the tail.
        start, end = entry["end"] - 2, entry["end"] + 120
        s = scored("MRI-005", "C1", ClinicalStatus.MET,
                   [VerifiedEvidence(entry["document_id"],
                                     doc.canonical[start:end], "supporting",
                                     doc.span(start, end), True)])
        self.assertEqual(s.units_recovered, 0)

    def test_a_document_sized_span_does_not_recover_everything(self) -> None:
        """Without a size cap, one huge span would score perfectly."""
        packet = ingest_case("MRI-005", CASES)
        doc = next(d for d in packet.usable if "06-15" in d.filename)
        whole = VerifiedEvidence(doc.document_id, doc.canonical, "supporting",
                                 doc.span(0, len(doc.canonical)), True)
        s = scored("MRI-005", "C1", ClinicalStatus.MET, [whole])
        self.assertEqual(s.units_recovered, 0,
                         "a whole-document span must not count as a citation")
        self.assertEqual(s.spans_accepted, 0)

    def test_a_span_in_the_wrong_document_does_not_count(self) -> None:
        entry = expectation("MRI-005", "C2")["acceptable_evidence"]["units"][0]["quotes"][0]
        packet = ingest_case("MRI-005", CASES)
        other = next(d for d in packet.usable
                     if d.document_id != entry["document_id"])
        s = scored("MRI-005", "C2", ClinicalStatus.MET,
                   [VerifiedEvidence(other.document_id, other.canonical[:60],
                                     "supporting", other.span(0, 60), True)])
        self.assertEqual(s.units_recovered, 0)


class AggregatesTests(unittest.TestCase):

    def build(self) -> RunScore:
        run = RunScore(configuration="A", split="development")
        run.instances = [
            scored("MRI-005", "C2", ClinicalStatus.MET,
                   [evidence_for("MRI-005", "C2", 0),
                    evidence_for("MRI-005", "C2", 1)]),
            scored("MRI-005", "C1", ClinicalStatus.NOT_MET,
                   [evidence_for("MRI-005", "C1", 0, 0)]),
            scored("MRI-005", "C4", ClinicalStatus.AMBIGUOUS),
            scored("MRI-005", "C3", None, failure=FailureKind.CONTRACT_REJECTION),
        ]
        return run

    def test_every_metric_carries_its_denominator(self) -> None:
        run = self.build()
        self.assertEqual(str(run.evidence_recall), "evidence recall: 3 of 5 (60.0%)")
        self.assertIn(" of ", str(run.evidence_precision))
        self.assertIn(" of ", str(run.status_agreement))

    def test_a_contract_rejection_leaves_the_status_denominator(self) -> None:
        run = self.build()
        self.assertEqual(len(run.instances), 4)
        self.assertEqual(run.status_agreement.denominator, 3)
        self.assertEqual(len(run.contract_rejections), 1)

    def test_a_contract_rejection_still_counts_against_complete_processing(self) -> None:
        self.assertEqual(self.build().complete_processing.numerator, 3)

    def test_a_critical_error_is_counted_and_named(self) -> None:
        run = self.build()
        errors = run.met_or_ambiguous_output_not_met
        self.assertEqual(len(errors), 1)
        self.assertEqual((errors[0].case_id, errors[0].criterion_id),
                         ("MRI-005", "C1"))

    def test_no_rate_is_printed_for_either_critical_direction(self) -> None:
        report = format_report(self.build())
        block = report.split("CRITICAL ERRORS")[1].split("REPORTED SEPARATELY")[0]
        self.assertNotIn("%", block, "a critical error direction was given a rate")
        self.assertIn("MRI-005 C1", block, "the affected instance must be named")

    def test_the_report_never_prints_a_bare_percentage(self) -> None:
        for line in format_report(self.build()).splitlines():
            if "%" in line:
                self.assertIn(" of ", line,
                              f"figure without its denominator: {line.strip()}")

    def test_not_applicable_instances_are_excluded(self) -> None:
        from um_evidence import score_run
        from um_evidence.verify import VerificationRun
        # MRI-003 C2 and C3 are waived by the exception pathway.
        v = VerificationRun(case_id="MRI-003", configuration="A")
        v.results = [result("MRI-003", cid, ClinicalStatus.MET)
                     for cid in ("C1", "C2", "C3", "C4", "C5")]
        run = score_run(v, LABELS)
        ids = {i.criterion_id for i in run.instances}
        self.assertEqual(ids, {"C1", "C4", "C5"})
        self.assertNotIn("C2", ids)


if __name__ == "__main__":
    unittest.main()
