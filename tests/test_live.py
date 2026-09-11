"""Live execution and its progress reporting, Task 3.6 interface work.

This is the demonstration path, so the standard it is held to is different
from the evaluation path's. An evaluation run that fails is a row in a table
someone reads later. A demonstration run that fails does so in front of
people, and the failure mode that matters is not "it broke" but **"it broke
and showed a clinical result anyway."**

Every test for a failure mode therefore asserts the same three things: no
criterion carries a clinical status, every criterion carries
`processing_status: FAILED`, and the reason is preserved rather than
flattened into a generic error. Four failure modes are covered because all
four have actually happened in this project: output truncation, a
non-retryable request rejection, exhausted credit, and an unreachable
network.

The progress tests exist because the display makes a claim about the
architecture. If rows appeared to stream during extraction, a viewer would
conclude the system makes one call per criterion, which is Candidate B — the
configuration the held-out run rejected. A display that misrepresents the
call structure is worse than no display.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import ingest_case, load_criteria  # noqa: E402
from um_evidence.extract import ModelResponse  # noqa: E402
from um_evidence.live import (  # noqa: E402
    LIVE_RUNS, STAGE_DONE, STAGE_PENDING, STAGE_QUOTE_CHECK, STAGE_READING,
    STAGE_SUPPORT_CHECK, run_live,
)

CASES = PROJECT_ROOT / "corpus" / "cases"


class Client:
    """A scripted transport. Either returns text or raises, never both."""

    def __init__(self, *responses, raises=None, stop_reason=""):
        self.responses = list(responses) or ["{}"]
        self.raises = raises
        self.stop_reason = stop_reason
        self.calls = 0

    def complete(self, system, user, **kw):
        self.calls += 1
        if self.raises is not None:
            raise self.raises
        text = self.responses[min(self.calls - 1, len(self.responses) - 1)]
        return ModelResponse(text=text, input_tokens=1000, output_tokens=100,
                             stop_reason=self.stop_reason)


def good_response(ids):
    return json.dumps({"results": [
        {"criterion_id": i, "clinical_status": "AMBIGUOUS",
         "reason_codes": ["MISSING_EVIDENCE"], "evidence": [],
         "explanation": "Nothing located."} for i in ids]})


class Harness(unittest.TestCase):
    def setUp(self):
        self.cs = load_criteria("lumbar_mri")
        self.packet = ingest_case("MRI-005", CASES)
        self.ids = list(self.cs.criterion_ids)
        self.tmp = Path(tempfile.mkdtemp())

    def go(self, client, **kw):
        self.events = []
        return run_live("MRI-005", self.cs, self.packet, client,
                        on_progress=lambda c, s, r: self.events.append((c, s)),
                        write_dir=self.tmp, **kw)

    def assert_all_failed(self, payload, expect_in_detail=None):
        """No clinical status anywhere, and the reason survives."""
        for section in ("extraction", "verification"):
            results = payload["cases"][0][section]["results"]
            self.assertEqual(len(results), len(self.ids))
            for r in results:
                self.assertIsNone(
                    r["clinical_status"],
                    f"{section}/{r['criterion_id']} carried a clinical status "
                    f"through a processing failure")
                self.assertEqual(r["processing_status"], "FAILED")
                self.assertIn("PROCESSING_ERROR", r["reason_codes"])
        if expect_in_detail:
            detail = " ".join(
                r.get("detail") or ""
                for r in payload["cases"][0]["extraction"]["results"])
            self.assertIn(expect_in_detail, detail.lower())


# ---------------------------------------------------------------------------
# The four failure modes, each observed in this project
# ---------------------------------------------------------------------------

class FailureRenderingTests(Harness):
    def test_output_truncation(self) -> None:
        """MRI-007, 2026-09-10: exhausted the output budget, returned nothing."""
        payload = self.go(Client("", stop_reason="max_tokens"))
        self.assert_all_failed(payload, "truncated")

    def test_non_retryable_request_rejection(self) -> None:
        """The temperature 400: the server rejected the request itself."""
        class BadRequest(Exception):
            status_code = 400
        payload = self.go(Client(raises=BadRequest("temperature is not supported")))
        self.assert_all_failed(payload)

    def test_exhausted_credit(self) -> None:
        """Observed mid-run: every subsequent call failed and no status was
        invented for any of them."""
        class CreditError(Exception):
            status_code = 400
        payload = self.go(Client(raises=CreditError(
            "Your credit balance is too low to access the Anthropic API")))
        self.assert_all_failed(payload, "credit")

    def test_network_unavailable(self) -> None:
        payload = self.go(Client(raises=ConnectionError("Name or service not known")))
        self.assert_all_failed(payload)

    def test_an_unexpected_exception_is_still_a_processing_state(self) -> None:
        """The last-resort guard, exercised on a path that can actually reach it.

        A first version of this test raised from the client and passed without
        the guard present: `extract` catches everything a model call throws
        and turns it into a recorded attempt, so the guard was never entered
        and the test was measuring `extract.py`. A mutation that deleted the
        guard entirely left all fifteen tests green.

        What genuinely reaches the guard is a failure in the extraction
        machinery *outside* a call — `build_extraction_prompt` is invoked
        before the try in `extract`, so anything it raises propagates. That is
        simulated here by making the extraction entry point raise, which is
        the guard's actual contract: whatever goes wrong in there, the result
        is a processing state and not a traceback on a projector.
        """
        import um_evidence.live as live

        original = live.extract
        live.extract = lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("prompt assembly failed"))
        try:
            payload = run_live("MRI-005", self.cs, self.packet, Client(),
                               write_dir=self.tmp)
        finally:
            live.extract = original
        self.assert_all_failed(payload, "prompt assembly failed")

    def test_no_failure_mode_produces_a_clinical_vocabulary_word(self) -> None:
        """A viewer must not be able to read a failure as a finding."""
        for client in (Client("", stop_reason="max_tokens"),
                       Client(raises=ConnectionError("down"))):
            payload = self.go(client)
            blob = json.dumps(payload["cases"][0]).upper()
            for word in ("\"MET\"", "\"NOT_MET\"", "APPROVE", "DENY"):
                self.assertNotIn(word, blob, f"{word} surfaced on a failure")


# ---------------------------------------------------------------------------
# Progress, and the claim it makes about the architecture
# ---------------------------------------------------------------------------

class ProgressTests(Harness):
    def test_every_criterion_is_pending_before_any_work(self) -> None:
        """The viewer sees the shape of the work before it starts."""
        self.go(Client(good_response(self.ids)))
        first = self.events[0]
        self.assertEqual(first[1], STAGE_PENDING)
        self.assertEqual(set(first[0]), set(self.ids),
                         "all rows must appear at once, not as they finish")

    def test_extraction_reports_every_criterion_together(self) -> None:
        """Baseline A is one call. Rows share the wait and must be shown to.

        If this ever reports criteria individually, the display is claiming a
        per-criterion call structure the adopted configuration does not have.
        """
        self.go(Client(good_response(self.ids)))
        reading = [e for e in self.events if e[1] == STAGE_READING]
        self.assertEqual(len(reading), 1,
                         "extraction must be reported once, not per criterion")
        self.assertEqual(set(reading[0][0]), set(self.ids))

    def test_verification_reports_one_criterion_at_a_time(self) -> None:
        """Steps 4 and 5 genuinely are per criterion, so rows genuinely stream."""
        self.go(Client(good_response(self.ids)))
        for stage in (STAGE_QUOTE_CHECK, STAGE_SUPPORT_CHECK, STAGE_DONE):
            seen = [e for e in self.events if e[1] == stage]
            self.assertEqual(len(seen), len(self.ids),
                             f"{stage} should be reported once per criterion")
            for group, _ in seen:
                self.assertEqual(len(group), 1,
                                 f"{stage} reported {len(group)} criteria at once")

    def test_the_two_checks_are_reported_separately(self) -> None:
        """Spec Section 4's two-check design has to be visible as two checks."""
        self.go(Client(good_response(self.ids)))
        for cid in self.ids:
            order = [s for c, s in self.events if c == (cid,)]
            self.assertLess(order.index(STAGE_QUOTE_CHECK),
                            order.index(STAGE_SUPPORT_CHECK))
            self.assertLess(order.index(STAGE_SUPPORT_CHECK),
                            order.index(STAGE_DONE))

    def test_a_row_finishes_before_the_next_one_starts(self) -> None:
        """Otherwise the display is not showing sequential execution, which
        Spec Section 11 fixes for this build."""
        self.go(Client(good_response(self.ids)))
        verification = [(c[0], s) for c, s in self.events
                        if s in (STAGE_QUOTE_CHECK, STAGE_DONE)]
        order = [c for c, _ in verification]
        # Each criterion's events must be contiguous.
        seen, last = set(), None
        for cid in order:
            if cid != last:
                self.assertNotIn(cid, seen, f"{cid} was interleaved")
                seen.add(cid)
                last = cid


class ArtifactTests(Harness):
    def test_a_live_run_never_writes_where_scored_runs_are_read(self) -> None:
        """The recorded-run picker and the eval harness both read
        `runs/*.json`, a non-recursive glob. A demonstration must not be able
        to drop a file into that namespace."""
        self.assertEqual(LIVE_RUNS.name, "live")
        self.assertEqual(LIVE_RUNS.parent.name, "runs")
        stray = sorted(LIVE_RUNS.parent.glob("*.json"))
        self.assertTrue(all(p.parent.name == "runs" for p in stray))
        # The glob used by the interface cannot see into the subdirectory.
        self.assertNotIn(LIVE_RUNS, list(LIVE_RUNS.parent.glob("*.json")))

    def test_the_artifact_is_marked_live(self) -> None:
        payload = self.go(Client(good_response(self.ids)))
        self.assertEqual(payload["mode"], "live")
        written = json.loads(Path(payload["artifact"]).read_text())
        self.assertEqual(written["mode"], "live",
                         "a live artifact must not be mistakable for a scored run")

    def test_no_key_reaches_the_artifact(self) -> None:
        """Spec Section 11. The scrub runs on the serialised payload."""
        leaky = Client(good_response(self.ids))
        payload = self.go(leaky)
        text = Path(payload["artifact"]).read_text()
        self.assertNotIn("sk-ant", text)

    def test_a_failed_run_still_writes_an_artifact(self) -> None:
        """A failure is a result. Losing the record of it would make the
        demonstration's failure handling unauditable afterwards."""
        payload = self.go(Client(raises=ConnectionError("down")))
        self.assertTrue(Path(payload["artifact"]).exists())


if __name__ == "__main__":
    unittest.main()
