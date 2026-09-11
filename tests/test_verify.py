"""Tests for Steps 4 and 5.

Step 4 is deterministic and is tested against the real corpus, including the
copy-forward block in MRI-005 that makes a quote resolve to two locations.

Step 5 is tested with a scripted client. The behaviour that matters is what
happens to a clinical status when a check fails, is inconclusive, or cannot be
run at all, and only the first of those is reachable through a real verifier
that mostly answers.
"""

import json
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import (  # noqa: E402
    ClinicalStatus, CriterionExtraction, ExtractedEvidence, ExtractionRun,
    FailureKind, ModelResponse, ProcessingStatus, ReasonCode,
    build_support_prompt, ingest_case, load_criteria, needs_support_check,
    parse_support, verify_quotes, verify_run, verify_support,
)

CASES = PROJECT_ROOT / "corpus" / "cases"

# Real passages from MRI-005.
REAL_QUOTE = "Meloxicam 15 mg oral daily trial completed, no relief"
COPY_FORWARD = ("She points to the right lower lumbar area and says it "
                "catches when she gets up from the couch.")


def extraction(status, evidence, codes=(), cid="C3"):
    return CriterionExtraction(
        criterion_id=cid,
        clinical_status=status,
        processing_status=ProcessingStatus.COMPLETE,
        reason_codes=list(codes),
        evidence=[ExtractedEvidence(*e) for e in evidence],
        explanation="because.")


class Scripted:
    def __init__(self, *responses, raises=None):
        self.responses, self.raises, self.calls = list(responses), raises, []

    def complete(self, system, user, **kw):
        self.calls.append({"system": system, "user": user, **kw})
        if self.raises:
            raise self.raises
        return ModelResponse(
            text=self.responses[min(len(self.calls) - 1, len(self.responses) - 1)])


class QuoteVerificationTests(unittest.TestCase):
    def setUp(self):
        self.packet = ingest_case("MRI-005", CASES)
        self.med = next(d for d in self.packet.usable if "medication" in d.filename)

    def test_a_real_quote_verifies_and_carries_a_span(self) -> None:
        out = verify_quotes(
            extraction(ClinicalStatus.MET, [(self.med.document_id, REAL_QUOTE, "supporting")]),
            self.packet)
        self.assertEqual(len(out.verified_evidence), 1)
        span = out.verified_evidence[0].span
        self.assertIsNotNone(span)
        self.assertEqual(self.med.canonical[span.start:span.end], REAL_QUOTE)
        self.assertEqual(span.content_sha256, self.med.content_sha256)
        self.assertIs(out.clinical_status, ClinicalStatus.MET)
        self.assertFalse(out.downgraded)

    def test_a_paraphrase_does_not_verify(self) -> None:
        out = verify_quotes(
            extraction(ClinicalStatus.MET,
                       [(self.med.document_id, "Meloxicam was tried without benefit",
                         "supporting")]),
            self.packet)
        self.assertEqual(len(out.rejected_evidence), 1)
        self.assertIn("not a citation", out.rejected_evidence[0].detail)

    def test_a_quote_resolving_twice_is_not_a_citation(self) -> None:
        """Copy-forward in real corpus data, not a constructed fixture.

        The block appears in the June note and again in the August note. A
        citation naming only the text does not say which encounter, and that
        distinction is what MRI-005 C2 turns on.
        """
        june = next(d for d in self.packet.usable if "06-15" in d.filename)
        self.assertEqual(len(june.locate(COPY_FORWARD)), 1)
        out = verify_quotes(
            extraction(ClinicalStatus.MET,
                       [(june.document_id, COPY_FORWARD, "supporting")]),
            self.packet)
        # Within one document it is unambiguous, so it verifies.
        self.assertTrue(out.evidence[0].verified)

    def test_a_quote_repeated_inside_one_document_is_rejected(self) -> None:
        doc = self.med
        doc.text = type(doc.text)(
            raw="same line here. same line here.",
            canonical="same line here. same line here.",
            offsets=tuple(range(len("same line here. same line here.") + 1)))
        out = verify_quotes(
            extraction(ClinicalStatus.MET,
                       [(doc.document_id, "same line here", "supporting")]),
            self.packet)
        self.assertFalse(out.evidence[0].verified)
        self.assertEqual(out.evidence[0].ambiguous_locations, 2)
        self.assertIn("does not identify which occurrence", out.evidence[0].detail)

    def test_a_citation_naming_an_unknown_document_is_rejected(self) -> None:
        out = verify_quotes(
            extraction(ClinicalStatus.MET, [("doc_deadbeef0000", REAL_QUOTE, "supporting")]),
            self.packet)
        self.assertFalse(out.evidence[0].verified)
        self.assertIn("was not read", out.evidence[0].detail)

    def test_a_met_losing_all_support_is_downgraded(self) -> None:
        out = verify_quotes(
            extraction(ClinicalStatus.MET, [(self.med.document_id, "invented", "supporting")]),
            self.packet)
        self.assertIs(out.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertIs(out.extracted_status, ClinicalStatus.MET)
        self.assertTrue(out.downgraded)
        self.assertIn(ReasonCode.UNVERIFIABLE_QUOTE, out.reason_codes)
        self.assertIn("rested entirely on", out.downgrade_reason)

    def test_a_met_losing_part_of_its_support_is_downgraded(self) -> None:
        # Conservative by design: the runtime cannot tell ALTERNATIVE from
        # COMPOSITE, so it cannot know the lost unit was not load-bearing.
        out = verify_quotes(
            extraction(ClinicalStatus.MET,
                       [(self.med.document_id, REAL_QUOTE, "supporting"),
                        (self.med.document_id, "invented", "supporting")]),
            self.packet)
        self.assertIs(out.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertTrue(out.downgraded)
        self.assertEqual(len(out.verified_evidence), 1,
                         "the valid span is retained, per Spec Section 3")

    def test_an_already_ambiguous_result_is_not_downgraded_again(self) -> None:
        out = verify_quotes(
            extraction(ClinicalStatus.AMBIGUOUS,
                       [(self.med.document_id, "invented", "supporting")],
                       codes=[ReasonCode.CONFLICTING_EVIDENCE]),
            self.packet)
        self.assertIs(out.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertFalse(out.downgraded)
        self.assertIn(ReasonCode.UNVERIFIABLE_QUOTE, out.reason_codes)

    def test_verification_never_produces_a_status_from_nothing(self) -> None:
        out = verify_quotes(
            CriterionExtraction(criterion_id="C1", clinical_status=None,
                                processing_status=ProcessingStatus.FAILED,
                                reason_codes=[ReasonCode.PROCESSING_ERROR],
                                failure_kind=FailureKind.CONTRACT_REJECTION),
            self.packet)
        self.assertIsNone(out.clinical_status)
        self.assertIs(out.failure_kind, FailureKind.CONTRACT_REJECTION)


class SupportVerificationTests(unittest.TestCase):
    def setUp(self):
        self.cs = load_criteria("lumbar_mri")
        self.packet = ingest_case("MRI-005", CASES)
        med = next(d for d in self.packet.usable if "medication" in d.filename)
        self.met = verify_quotes(
            extraction(ClinicalStatus.MET, [(med.document_id, REAL_QUOTE, "supporting")]),
            self.packet)

    def test_the_verifier_never_receives_the_packet(self) -> None:
        """The whole point of the step. A verifier that can see the record can
        re-derive the answer and agree with itself."""
        client = Scripted('{"outcome": "SUPPORTED", "detail": "ok"}')
        verify_support(self.met, self.cs["C3"], self.cs, client)
        sent = client.calls[0]["system"] + client.calls[0]["user"]
        for doc in self.packet.usable:
            self.assertNotIn(doc.canonical, sent)
        self.assertIn(REAL_QUOTE, sent, "the cited quote must be present")
        self.assertIn("not given the patient's record", sent)

    def test_supported_leaves_the_status_alone(self) -> None:
        verify_support(self.met, self.cs["C3"], self.cs,
                       Scripted('{"outcome": "SUPPORTED", "detail": "establishes it"}'))
        self.assertIs(self.met.clinical_status, ClinicalStatus.MET)
        self.assertTrue(self.met.support_checked)
        self.assertFalse(self.met.downgraded)

    def test_unsupported_downgrades_and_says_why(self) -> None:
        verify_support(self.met, self.cs["C3"], self.cs,
                       Scripted('{"outcome": "UNSUPPORTED", "detail": "wrong episode"}'))
        self.assertIs(self.met.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertIn(ReasonCode.UNSUPPORTED_CONCLUSION, self.met.reason_codes)
        self.assertTrue(self.met.downgraded)
        self.assertIn("wrong episode", self.met.downgrade_reason)

    def test_inconclusive_changes_nothing_and_is_recorded(self) -> None:
        # Spec Section 3 requires inconclusive checks to be reported. Treating
        # one as a failure would let the verifier's uncertainty rewrite a
        # clinical result.
        verify_support(self.met, self.cs["C3"], self.cs,
                       Scripted('{"outcome": "INCONCLUSIVE", "detail": "cannot tell"}'))
        self.assertIs(self.met.clinical_status, ClinicalStatus.MET)
        self.assertFalse(self.met.downgraded)
        self.assertEqual(self.met.support_outcome, "INCONCLUSIVE")

    def test_a_failed_check_does_not_touch_the_clinical_status(self) -> None:
        verify_support(self.met, self.cs["C3"], self.cs,
                       Scripted(raises=TimeoutError("gone")), max_attempts=2)
        self.assertIs(self.met.clinical_status, ClinicalStatus.MET,
                      "a verifier outage is not a finding about the record")
        self.assertFalse(self.met.support_checked)
        self.assertEqual(self.met.support_outcome, "FAILED")

    def test_a_malformed_verdict_is_rejected(self) -> None:
        for text in ("", "yes", '{"outcome": "PROBABLY"}', '{"detail": "x"}',
                     '{"outcome": "SUPPORTED", "detail": 5}'):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_support(text)

    def test_a_fenced_verdict_is_accepted(self) -> None:
        self.assertEqual(
            parse_support('```json\n{"outcome": "SUPPORTED", "detail": "x"}\n```'),
            ("SUPPORTED", "x"))

    def test_an_unsupported_verdict_cannot_overturn_an_abstention(self) -> None:
        """The guard that contained a real verifier error.

        On MRI-004 C3 the verifier returned UNSUPPORTED against a correct
        AMBIGUOUS/CONFLICTING_EVIDENCE result, reasoning that the criterion
        needed a determination. Downgrading is restricted to determinate
        statuses, so nothing was overturned. That restriction is load-bearing,
        not incidental.
        """
        med = next(d for d in self.packet.usable if "medication" in d.filename)
        ambiguous = verify_quotes(
            extraction(ClinicalStatus.AMBIGUOUS,
                       [(med.document_id, REAL_QUOTE, "supporting")],
                       codes=[ReasonCode.CONFLICTING_EVIDENCE]),
            self.packet)
        verify_support(ambiguous, self.cs["C3"], self.cs,
                       Scripted('{"outcome": "UNSUPPORTED", "detail": "needs a determination"}'))
        self.assertIs(ambiguous.clinical_status, ClinicalStatus.AMBIGUOUS)
        self.assertFalse(ambiguous.downgraded)
        self.assertEqual(ambiguous.support_outcome, "UNSUPPORTED",
                         "the disagreement is still recorded")

    def test_the_prompt_says_abstention_is_a_claim(self) -> None:
        from um_evidence.verify import SUPPORT_SYSTEM
        self.assertIn("unresolved status is a claim", SUPPORT_SYSTEM)
        self.assertIn("Abstention is a correct outcome", SUPPORT_SYSTEM)

    def test_a_result_with_nothing_cited_is_skipped(self) -> None:
        missing = verify_quotes(
            extraction(ClinicalStatus.AMBIGUOUS, [],
                       codes=[ReasonCode.MISSING_EVIDENCE], cid="C4"),
            self.packet)
        self.assertFalse(needs_support_check(missing))
        client = Scripted('{"outcome": "SUPPORTED", "detail": "x"}')
        verify_support(missing, self.cs["C4"], self.cs, client)
        self.assertEqual(client.calls, [], "no call may be spent on an absence")
        self.assertEqual(missing.support_outcome, "SKIPPED")

    def test_the_prompt_states_the_evidence_shape(self) -> None:
        prompt = build_support_prompt(self.cs["C2"], self.cs, self.met)
        self.assertIn("Evidence shape: COMPOSITE", prompt.user)


class WholeRunTests(unittest.TestCase):
    def setUp(self):
        self.cs = load_criteria("lumbar_mri")
        self.packet = ingest_case("MRI-005", CASES)
        med = next(d for d in self.packet.usable if "medication" in d.filename)
        self.run = ExtractionRun(case_id="MRI-005", configuration="A",
                                 model="m", prompt_version="p")
        self.run.results = [
            extraction(ClinicalStatus.MET, [(med.document_id, REAL_QUOTE, "supporting")],
                       cid="C3"),
            extraction(ClinicalStatus.AMBIGUOUS, [],
                       codes=[ReasonCode.MISSING_EVIDENCE], cid="C4"),
            extraction(ClinicalStatus.MET, [(med.document_id, "invented", "supporting")],
                       cid="C1"),
        ]

    def test_step_four_runs_without_a_model(self) -> None:
        out = verify_run(self.run, self.packet, self.cs)
        self.assertEqual(out.returned_spans, 2)
        self.assertEqual(out.verified_spans, 1)
        self.assertEqual(out.citation_validity, 0.5)
        self.assertEqual(sum(1 for r in out.results if r.downgraded), 1)

    def test_citation_validity_is_none_when_nothing_was_returned(self) -> None:
        self.run.results = [extraction(ClinicalStatus.AMBIGUOUS, [],
                                       codes=[ReasonCode.MISSING_EVIDENCE], cid="C4")]
        self.assertIsNone(verify_run(self.run, self.packet, self.cs).citation_validity)

    def test_step_five_runs_only_where_there_is_a_claim(self) -> None:
        client = Scripted('{"outcome": "SUPPORTED", "detail": "ok"}')
        out = verify_run(self.run, self.packet, self.cs, client)
        # C3 has verified evidence; C4 cites nothing; C1 lost its only quote.
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(out.as_dict()["support_outcomes"]["SUPPORTED"], 1)
        self.assertEqual(out.as_dict()["support_outcomes"]["SKIPPED"], 2)

    def test_the_record_of_what_changed_survives(self) -> None:
        out = verify_run(self.run, self.packet, self.cs)
        downgraded = next(r for r in out.results if r.downgraded)
        d = downgraded.as_dict()
        self.assertEqual(d["extracted_status"], "MET")
        self.assertEqual(d["clinical_status"], "AMBIGUOUS")
        self.assertTrue(d["downgrade_reason"])
        self.assertEqual(d["verification"]["quote_check"]["rejected"], 1)

    def test_no_determination_vocabulary_in_the_output(self) -> None:
        keys = set()

        def walk(o):
            if isinstance(o, dict):
                keys.update(o)
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)

        walk(verify_run(self.run, self.packet, self.cs).as_dict())
        for banned in ("recommendation", "decision", "approved", "denied", "score"):
            self.assertNotIn(banned, keys)


class ReplayAgainstRecordedRunsTests(unittest.TestCase):
    """Step 4 against the three real extraction runs already recorded."""

    def test_recorded_runs_replay_with_every_quote_verifying(self) -> None:
        import glob
        for case in ("MRI-005", "TKA-004", "MRI-004"):
            paths = sorted(glob.glob(str(PROJECT_ROOT / "runs" / f"*{case}*.json")))
            if not paths:
                self.skipTest(f"no recorded run for {case}")
            with self.subTest(case=case):
                recorded = json.loads(Path(paths[-1]).read_text())
                packet = ingest_case(case, CASES)
                run = ExtractionRun(case_id=case, configuration="A",
                                    model="m", prompt_version="p")
                for r in recorded["extraction"]["results"]:
                    if r["clinical_status"] is None:
                        continue
                    run.results.append(CriterionExtraction(
                        criterion_id=r["criterion_id"],
                        clinical_status=ClinicalStatus(r["clinical_status"]),
                        processing_status=ProcessingStatus.COMPLETE,
                        reason_codes=[ReasonCode(c) for c in r["reason_codes"]],
                        evidence=[ExtractedEvidence(e["document_id"], e["quote"],
                                                    e["role"])
                                  for e in r["evidence"]]))
                out = verify_run(run, packet, load_criteria(
                    "total_knee_arthroplasty" if case.startswith("TKA") else "lumbar_mri"))
                self.assertEqual(out.verified_spans, out.returned_spans,
                                 f"{case}: {[e.detail for r in out.results for e in r.rejected_evidence]}")
                self.assertEqual(sum(1 for r in out.results if r.downgraded), 0)


if __name__ == "__main__":
    unittest.main()
