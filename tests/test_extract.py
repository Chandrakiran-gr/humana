"""Tests for Step 3, evidence extraction.

No test here makes a network call. The behaviour worth testing is what happens
when a response is malformed, invents a criterion, claims NOT_MET with nothing
to show for it, or never arrives — and a real API mostly returns well-formed
JSON, so those paths are only reachable through a substituted client.

The two properties the experiment depends on are asserted mechanically rather
than trusted: that Baseline A and Candidate B send the same prompt, and that
nothing authored into that prompt is quoted from a packet the model is about to
read.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_criteria_contamination import contaminating_phrases  # noqa: E402
from um_evidence import (  # noqa: E402
    EXTRACTION_SYSTEM, EXTRACTOR_REASON_CODES, ClinicalStatus, MalformedResponse,
    ModelResponse, ProcessingStatus, ReasonCode, build_extraction_prompt,
    build_result, extract, ingest_case, load_criteria, parse_response,
)

CASES = PROJECT_ROOT / "corpus" / "cases"


class ScriptedClient:
    """Returns canned text, one response per call, and records what it was sent."""

    def __init__(self, *responses, raises=None):
        self.responses = list(responses)
        self.raises = raises
        self.calls = []

    def complete(self, system, user, **kw):
        self.calls.append({"system": system, "user": user, **kw})
        if self.raises is not None:
            raise self.raises
        text = self.responses[min(len(self.calls) - 1, len(self.responses) - 1)]
        return ModelResponse(text=text, input_tokens=1000, output_tokens=100)


def response_for(ids, status="AMBIGUOUS", codes=("MISSING_EVIDENCE",),
                 evidence=(), explanation="Nothing located."):
    import json
    return json.dumps({"results": [
        {"criterion_id": i, "clinical_status": status,
         "reason_codes": list(codes), "evidence": list(evidence),
         "explanation": explanation}
        for i in ids]})


# ---------------------------------------------------------------------------
# The shared prompt
# ---------------------------------------------------------------------------

class SharedPromptTests(unittest.TestCase):
    def setUp(self):
        self.cs = load_criteria("lumbar_mri")
        self.packet = ingest_case("MRI-005", CASES)

    def test_the_two_configurations_send_the_same_prompt(self) -> None:
        """The experiment is unreadable if the prompts drift apart.

        Spec Section 7: applying a prompt change to one configuration and not
        the other confounds call structure with prompt quality. Asserted here
        rather than left to a convention, because a convention is what someone
        breaks while improving one of the two.
        """
        a = build_extraction_prompt(self.cs, self.packet)
        b = [build_extraction_prompt(self.cs, self.packet, (cid,))
             for cid in self.cs.criterion_ids]

        for one in b:
            self.assertEqual(one.system, a.system)
            self.assertEqual(one.record_block, a.record_block)
            self.assertEqual(one.prompt_version, a.prompt_version)

        # The criteria block differs only by which criteria it lists: strip the
        # per-criterion text and the remainder must be byte-identical. Blank
        # runs are collapsed because removing five criteria leaves five gaps
        # where removing one leaves one, which is the stripping and not a
        # difference in the prompt.
        def scaffold(prompt):
            body = prompt.criteria_block
            for criterion in self.cs.criteria:
                body = body.replace(criterion.as_prompt_block(), "")
            return "\n".join(line for line in body.splitlines() if line.strip())

        for one in b:
            self.assertEqual(scaffold(one), scaffold(a),
                             "the criteria block differs by more than its criteria")

    def test_every_criterion_reaches_the_model_exactly_once_across_b(self) -> None:
        b = [build_extraction_prompt(self.cs, self.packet, (cid,))
             for cid in self.cs.criterion_ids]
        self.assertEqual(len(b), len(self.cs.criteria))
        for one, cid in zip(b, self.cs.criterion_ids):
            self.assertEqual(one.criterion_ids, (cid,))
            self.assertIn(self.cs[cid].text, one.criteria_block)

    def test_documents_are_structurally_separated_from_instructions(self) -> None:
        prompt = build_extraction_prompt(self.cs, self.packet)
        # The system prompt names the tag, which is how the separation is
        # explained to the model. What must not leak is document content.
        for doc in self.packet.usable:
            self.assertNotIn(doc.canonical, prompt.authored_text)
        self.assertEqual(prompt.record_block.count("<document "),
                         len(self.packet.usable))
        for doc in self.packet.usable:
            self.assertIn(f'id="{doc.document_id}"', prompt.record_block)
            self.assertIn(doc.canonical, prompt.record_block)

    def test_an_unreadable_document_contributes_no_text(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        packet.documents[0].text = None
        packet.documents[0].outcome = type(packet.documents[0].outcome).EMPTY
        prompt = build_extraction_prompt(self.cs, packet)
        self.assertEqual(prompt.record_block.count("<document "),
                         len(packet.usable))

    def test_unknown_criterion_id_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            build_extraction_prompt(self.cs, self.packet, ("C99",))

    def test_the_prompt_asks_for_no_determination(self) -> None:
        text = EXTRACTION_SYSTEM.lower()
        for banned in ("approve", "deny", "recommend"):
            self.assertIn(banned, text, "the prohibition should be stated")
        self.assertIn("you do not decide coverage", text)

    def test_the_prompt_forbids_adjusting_capitalisation(self) -> None:
        """Two of three unverifiable citations in the first run were one
        letter's case. The matcher was kept strict and the instruction made
        explicit; see docs/SPAN_REPRESENTATION.md."""
        self.assertIn("Do not adjust capitalisation", EXTRACTION_SYSTEM)
        self.assertIn("copy the letter that is there", EXTRACTION_SYSTEM)

    def test_runtime_only_reason_codes_are_withheld(self) -> None:
        for code in ("UNVERIFIABLE_QUOTE", "UNSUPPORTED_CONCLUSION", "PROCESSING_ERROR"):
            self.assertNotIn(code, EXTRACTOR_REASON_CODES)
            self.assertNotIn(code, EXTRACTION_SYSTEM)


class PromptContaminationTests(unittest.TestCase):
    def test_no_authored_prompt_text_appears_in_any_packet(self) -> None:
        """Checked against the assembled string, not against the file on disk.

        What reaches the model is a prompt built at runtime. An assembly step
        can introduce wording that no check of criteria_sets.json would see, so
        the comparison runs against exactly what would be sent, minus the
        packet itself.
        """
        for procedure in ("lumbar_mri", "total_knee_arthroplasty", "lumbar_fusion"):
            with self.subTest(procedure=procedure):
                cs = load_criteria(procedure)
                case = {"lumbar_mri": "MRI-005",
                        "total_knee_arthroplasty": "TKA-004",
                        "lumbar_fusion": "LF-201"}[procedure]
                prompt = build_extraction_prompt(cs, ingest_case(case, CASES))
                hits = contaminating_phrases(prompt.contamination_scope, CASES)
                self.assertEqual(
                    hits, {},
                    f"authored prompt text also appears in packets: "
                    f"{sorted(hits)[:5]}")

    def test_the_checked_scope_is_not_empty(self) -> None:
        """A scope that exempted everything would pass the check above vacuously.

        The exemption removes criterion vocabulary. It must leave the system
        prompt, the rule prose and the task block, which is where assembly
        could introduce a phrase the on-disk check never sees.
        """
        cs = load_criteria("lumbar_fusion")
        prompt = build_extraction_prompt(cs, ingest_case("LF-201", CASES))
        scope = prompt.contamination_scope

        self.assertIn("Failing to find something", scope, "system prompt gone")
        self.assertIn("ROUTE A", scope, "rule prose gone")
        self.assertIn("Return one result object", scope, "task block gone")
        self.assertNotIn(cs["C1"].text, scope, "criterion text should be exempt")
        self.assertGreater(len(scope.split()), 1000, "the scope has been gutted")

    def test_the_contamination_check_can_actually_fail(self) -> None:
        """Shown to fail on a planted collision, per the Stage 1 rule."""
        planted = ("She points to the right lower lumbar area and says it "
                   "catches when she gets up from the couch.")
        hits = contaminating_phrases(planted, CASES)
        self.assertTrue(hits, "a verbatim packet sentence was not detected")


# ---------------------------------------------------------------------------
# Parsing and validation
# ---------------------------------------------------------------------------

class ParseTests(unittest.TestCase):
    IDS = ("C1", "C2")

    def test_accepts_a_well_formed_response_and_strips_a_fence(self) -> None:
        body = response_for(self.IDS)
        for text in (body, f"```json\n{body}\n```"):
            parsed = parse_response(text, self.IDS)
            self.assertEqual(set(parsed), {"C1", "C2"})

    def test_rejects_malformed_input_rather_than_repairing_it(self) -> None:
        for text, why in [
            ("", "empty"),
            ("I am unable to help with this request.", "prose"),
            ('{"results": {}}', "results not a list"),
            ('{"other": []}', "no results key"),
            ('{"results": [{"criterion_id": "C9"}]}', "criterion not asked about"),
            ('{"results": [{"criterion_id": "C1"}, {"criterion_id": "C1"}]}', "duplicate"),
            ('{"results": ["C1"]}', "entry not an object"),
            ('{"results": [{"criterion_id": "C1"},', "truncated JSON"),
        ]:
            with self.subTest(why=why):
                with self.assertRaises(MalformedResponse):
                    parse_response(text, self.IDS)

    def test_a_valid_entry_becomes_a_clinical_result(self) -> None:
        result = build_result("C1", {
            "criterion_id": "C1", "clinical_status": "MET", "reason_codes": [],
            "evidence": [{"document_id": "doc_a", "quote": "meloxicam 15 mg",
                          "role": "supporting"}],
            "explanation": "An NSAID trial is recorded."})
        self.assertIs(result.clinical_status, ClinicalStatus.MET)
        self.assertIs(result.processing_status, ProcessingStatus.COMPLETE)
        self.assertEqual(len(result.evidence), 1)

    def test_invalid_content_fails_without_inventing_a_status(self) -> None:
        cases = {
            "status outside the four": {"clinical_status": "APPROVED"},
            "status is a recommendation": {"clinical_status": "MET_WITH_EXCEPTION"},
            "reason code reserved for step 4": {
                "clinical_status": "AMBIGUOUS",
                "reason_codes": ["UNVERIFIABLE_QUOTE"]},
            "reason code reserved for the runtime": {
                "clinical_status": "AMBIGUOUS",
                "reason_codes": ["PROCESSING_ERROR"]},
            "ambiguous with no reason": {
                "clinical_status": "AMBIGUOUS", "reason_codes": []},
            "not_met with no evidence": {
                "clinical_status": "NOT_MET", "reason_codes": [], "evidence": []},
            "missing_evidence alongside evidence": {
                "clinical_status": "AMBIGUOUS",
                "reason_codes": ["MISSING_EVIDENCE"],
                "evidence": [{"document_id": "d", "quote": "q", "role": "supporting"}]},
            "evidence with no quote": {
                "clinical_status": "MET",
                "evidence": [{"document_id": "d", "role": "supporting"}]},
            "evidence with no document": {
                "clinical_status": "MET",
                "evidence": [{"quote": "q", "role": "supporting"}]},
            "invented evidence role": {
                "clinical_status": "MET",
                "evidence": [{"document_id": "d", "quote": "q", "role": "decisive"}]},
            "evidence not a list": {"clinical_status": "MET", "evidence": "lots"},
        }
        for why, entry in cases.items():
            with self.subTest(why=why):
                result = build_result("C1", entry)
                self.assertIsNone(result.clinical_status,
                                  "a rejected entry must carry no clinical status")
                self.assertIs(result.processing_status, ProcessingStatus.FAILED)
                self.assertIn(ReasonCode.PROCESSING_ERROR, result.reason_codes)

    def test_a_rejected_result_is_not_ambiguous(self) -> None:
        # None and AMBIGUOUS are different findings. AMBIGUOUS says the record
        # was read and did not settle it; None says nothing was concluded.
        result = build_result("C1", {"clinical_status": "APPROVED"})
        self.assertIsNone(result.clinical_status)
        self.assertIsNot(result.clinical_status, ClinicalStatus.AMBIGUOUS)


# ---------------------------------------------------------------------------
# End to end, with a scripted client
# ---------------------------------------------------------------------------

class ExtractionRunTests(unittest.TestCase):
    def setUp(self):
        self.cs = load_criteria("lumbar_mri")
        self.packet = ingest_case("MRI-005", CASES)
        self.ids = self.cs.criterion_ids

    def test_baseline_a_makes_one_call_and_candidate_b_makes_one_per_criterion(self):
        a_client = ScriptedClient(response_for(self.ids))
        a = extract(self.cs, self.packet, a_client, configuration="A")
        self.assertEqual(a.calls, 1)
        self.assertEqual(len(a.results), len(self.ids))

        b_client = ScriptedClient(*[response_for((c,)) for c in self.ids])
        b = extract(self.cs, self.packet, b_client, configuration="B")
        self.assertEqual(b.calls, len(self.ids))
        self.assertEqual(len(b.results), len(self.ids))
        self.assertEqual([r.criterion_id for r in b.results], list(self.ids))

    def test_each_b_call_carries_the_whole_packet(self) -> None:
        client = ScriptedClient(*[response_for((c,)) for c in self.ids])
        extract(self.cs, self.packet, client, configuration="B")
        for call in client.calls:
            for doc in self.packet.usable:
                self.assertIn(doc.canonical, call["user"])

    def test_a_malformed_response_never_becomes_a_clinical_finding(self) -> None:
        client = ScriptedClient("not json at all")
        run = extract(self.cs, self.packet, client, configuration="A")
        self.assertIs(run.processing_status, ProcessingStatus.FAILED)
        for result in run.results:
            self.assertIsNone(result.clinical_status)
            self.assertIn(ReasonCode.PROCESSING_ERROR, result.reason_codes)

    def test_a_transport_failure_never_becomes_a_clinical_finding(self) -> None:
        client = ScriptedClient(raises=TimeoutError("read timed out"))
        run = extract(self.cs, self.packet, client, configuration="A")
        self.assertIs(run.processing_status, ProcessingStatus.FAILED)
        self.assertTrue(all(r.clinical_status is None for r in run.results))
        self.assertIn("TimeoutError", run.attempts[-1].error)

    def test_retries_are_finite_and_every_attempt_is_recorded(self) -> None:
        client = ScriptedClient("still not json")
        run = extract(self.cs, self.packet, client, configuration="A", max_attempts=3)
        self.assertEqual(run.calls, 3)
        self.assertEqual(len(run.attempts), 3)
        for attempt in run.attempts:
            self.assertEqual(attempt.raw_text, "still not json")
            self.assertTrue(attempt.parse_error)

    def test_a_request_the_server_refuses_is_not_retried(self) -> None:
        """The first live run made three identical calls and got three 400s.

        A retry budget is for transient failure. Repeating a request the
        server has already rejected cannot succeed and spends the budget
        proving it.
        """
        class Refused(Exception):
            status_code = 400

        client = ScriptedClient(raises=Refused("`temperature` is deprecated"))
        run = extract(self.cs, self.packet, client, configuration="A",
                      max_attempts=3)
        self.assertEqual(run.calls, 1, "a 400 must not be retried")
        self.assertFalse(run.attempts[0].retryable)
        self.assertIs(run.processing_status, ProcessingStatus.FAILED)
        self.assertTrue(all(r.clinical_status is None for r in run.results))
        self.assertIn("not retried", run.results[0].detail)

    def test_a_truncated_response_says_so_and_is_not_retried(self) -> None:
        """The first development run's real failure, hidden as "empty response".

        Three of fifteen cases exhausted max_tokens exactly. The response was
        reported as empty or as invalid JSON, both of which name the symptom
        and hide the cause, and each was retried twice at full cost to
        truncate at the same place.
        """
        class Truncating:
            def __init__(self):
                self.calls = 0

            def complete(self, system, user, **kw):
                self.calls += 1
                return ModelResponse(text='{"results": [{"criterion_id": "C1"',
                                     output_tokens=kw["max_tokens"],
                                     stop_reason="max_tokens")

        client = Truncating()
        run = extract(self.cs, self.packet, client, configuration="A",
                      max_attempts=3)
        self.assertEqual(client.calls, 1, "a truncation must not be retried")
        self.assertIn("truncated", run.attempts[0].parse_error)
        self.assertIn("raise max_tokens", run.results[0].detail)
        self.assertEqual(run.attempts[0].stop_reason, "max_tokens")
        self.assertTrue(all(r.clinical_status is None for r in run.results))

    def test_a_transient_failure_is_retried(self) -> None:
        class Overloaded(Exception):
            status_code = 529

        for exc in (Overloaded("overloaded"), TimeoutError("read timed out")):
            with self.subTest(exc=type(exc).__name__):
                client = ScriptedClient(raises=exc)
                run = extract(self.cs, self.packet, client, configuration="A",
                              max_attempts=3)
                self.assertEqual(run.calls, 3)
                self.assertTrue(run.attempts[0].retryable)

    def test_temperature_is_not_sent_unless_asked_for(self) -> None:
        # The live 400 came from sending a default the model no longer accepts.
        client = ScriptedClient(response_for(self.ids))
        extract(self.cs, self.packet, client, configuration="A")
        self.assertIsNone(client.calls[0]["temperature"])

    def test_a_recovered_retry_stops_retrying(self) -> None:
        client = ScriptedClient("garbage", response_for(self.ids))
        run = extract(self.cs, self.packet, client, configuration="A")
        self.assertEqual(run.calls, 2)
        self.assertIs(run.processing_status, ProcessingStatus.COMPLETE)
        self.assertTrue(run.attempts[0].parse_error)

    def test_raw_output_is_retained_even_when_rejected(self) -> None:
        # Spec Section 3: rejected raw results are preserved in the run log.
        client = ScriptedClient("I cannot assist with that.")
        run = extract(self.cs, self.packet, client, configuration="A")
        self.assertTrue(all(a.raw_text == "I cannot assist with that."
                            for a in run.attempts))
        self.assertIn("I cannot assist with that.",
                      str(run.as_dict()["attempts"]))

    def test_a_criterion_omitted_by_the_model_is_not_silently_dropped(self) -> None:
        client = ScriptedClient(response_for(self.ids[:-1]))
        run = extract(self.cs, self.packet, client, configuration="A")
        self.assertEqual(len(run.results), len(self.ids))
        missing = run.results[-1]
        self.assertEqual(missing.criterion_id, self.ids[-1])
        self.assertIsNone(missing.clinical_status)
        self.assertIs(run.processing_status, ProcessingStatus.PARTIAL)

    def test_a_failed_packet_is_never_sent_to_the_model(self) -> None:
        packet = ingest_case("MRI-005", CASES)
        for doc in packet.documents:
            doc.text = None
            doc.outcome = type(doc.outcome).UNREADABLE
        self.assertIs(packet.processing_status, ProcessingStatus.FAILED)

        client = ScriptedClient(response_for(self.ids, status="MET", codes=()))
        run = extract(self.cs, packet, client, configuration="A")
        self.assertEqual(client.calls, [], "no call may be made on a failed packet")
        self.assertIs(run.processing_status, ProcessingStatus.FAILED)
        for result in run.results:
            self.assertIsNone(result.clinical_status,
                              "a processing failure must not surface as a status")

    def test_the_run_log_carries_what_section_11_requires(self) -> None:
        client = ScriptedClient(response_for(self.ids))
        run = extract(self.cs, self.packet, client, configuration="A")
        logged = run.as_dict()
        for key in ("case_id", "configuration", "model", "prompt_version",
                    "processing_status", "calls", "input_tokens",
                    "output_tokens", "seconds", "results", "attempts", "prompts"):
            self.assertIn(key, logged)
        self.assertEqual(logged["input_tokens"], 1000)

    def test_no_output_field_carries_a_determination(self) -> None:
        client = ScriptedClient(response_for(self.ids))
        run = extract(self.cs, self.packet, client, configuration="A")
        keys = set()

        def walk(obj):
            if isinstance(obj, dict):
                keys.update(obj)
                for v in obj.values():
                    walk(v)
            elif isinstance(obj, list):
                for v in obj:
                    walk(v)

        walk(run.as_dict())
        for banned in ("recommendation", "decision", "approved", "denied",
                       "score", "confidence"):
            self.assertNotIn(banned, keys)

    def test_configuration_must_be_a_or_b(self) -> None:
        with self.assertRaises(ValueError):
            extract(self.cs, self.packet, ScriptedClient("{}"), configuration="C")


if __name__ == "__main__":
    unittest.main()
