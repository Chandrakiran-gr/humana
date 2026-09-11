"""Every checker in the battery, shown to fail on the defect it targets.

Five of five checkers written for this project passed on their first run while
the defect they existed to catch was present. The most recent,
`check_unit_counts.py`, was wrong in both directions at once: it flagged seven
instances that were correct and missed six that were not, including the largest
group of the exact defect it was written for.

That is not a run of bad luck. It is a property of writing a check against a
defect you have already failed to see, and the mitigation is mechanical: no
check is trusted until it has been shown to fail on a real instance of what it
targets, **and** to pass on things that merely resemble it.

Each test below copies the real corpus, plants one defect, and asserts the
checker reports it. A checker with no test here is an unverified checker, and
the audit in docs/DATA_CARD.md says which those are.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT_ROOT / "scripts"


def run(script: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                          cwd=PROJECT_ROOT, capture_output=True, text=True)


class CheckerFailureTests(unittest.TestCase):
    """Plant the defect, confirm the checker objects."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def scratch_labels(self, mutate) -> str:
        """Write a mutated copy of labels.json under the project, return its path."""
        labels = json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())
        mutate(labels)
        out = PROJECT_ROOT / "corpus" / ".scratch_labels.json"
        out.write_text(json.dumps(labels))
        self.addCleanup(out.unlink, missing_ok=True)
        return "corpus/.scratch_labels.json"

    def scratch_cases(self, mutate) -> str:
        """Copy corpus/cases under the project, mutate it, return its path."""
        out = PROJECT_ROOT / "corpus" / ".scratch_cases"
        shutil.rmtree(out, ignore_errors=True)
        shutil.copytree(PROJECT_ROOT / "corpus" / "cases", out)
        self.addCleanup(shutil.rmtree, out, ignore_errors=True)
        mutate(out)
        return "corpus/.scratch_cases"

    # -- validate_labels -------------------------------------------------

    def test_validate_labels_catches_a_broken_invariant(self) -> None:
        def plant(labels):
            for case in labels["cases"]:
                for e in case["expected"].values():
                    if isinstance(e, dict) and "MISSING_EVIDENCE" in e["reason_codes"]:
                        e["evidence_units_required"] = 2   # must imply zero units
                        return
            raise AssertionError("no MISSING_EVIDENCE instance to plant into")

        r = run("validate_labels.py", "--labels", self.scratch_labels(plant), "--quiet")
        self.assertEqual(r.returncode, 1, "a broken invariant was not reported")
        self.assertIn("MISSING_EVIDENCE", r.stdout)

    def test_validate_labels_passes_on_the_real_corpus(self) -> None:
        self.assertEqual(run("validate_labels.py", "--quiet").returncode, 0)

    # -- check_unit_counts -----------------------------------------------

    def test_unit_counts_catches_an_undercount(self) -> None:
        def plant(labels):
            for case in labels["cases"]:
                if case["case_id"] == "TKA-004":
                    case["expected"]["C4"]["evidence_units_required"] = 2  # floor is 4
                    return
            raise AssertionError("TKA-004 not found")

        r = run("check_unit_counts.py", "--labels", self.scratch_labels(plant))
        self.assertEqual(r.returncode, 1)
        self.assertIn("TKA-004", r.stdout)

    def test_unit_counts_does_not_flag_a_single_passage_branch(self) -> None:
        """The false-positive direction, which the first version got wrong.

        lumbar_mri C2 is satisfiable either by one explicit duration statement
        or by two dated encounters. An instance taking the one-passage branch
        is correct at one unit and must not be reported.
        """
        r = run("check_unit_counts.py")
        self.assertEqual(r.returncode, 0, r.stdout)
        for explicit_duration in ("MRI-001", "MRI-007", "MRI-008"):
            self.assertNotIn(explicit_duration, r.stdout.split("Checked")[-1])

    # -- acceptable_evidence ---------------------------------------------

    def test_validate_labels_catches_a_missing_acceptable_set(self) -> None:
        def plant(labels):
            labels["cases"][0]["expected"]["C1"].pop("acceptable_evidence")
        r = run("validate_labels.py", "--labels", self.scratch_labels(plant), "--quiet")
        self.assertEqual(r.returncode, 1)
        self.assertIn("recall cannot be scored", r.stdout)

    def test_validate_labels_catches_a_unit_count_disagreement(self) -> None:
        """The acceptable set and evidence_units_required must not drift apart."""
        def plant(labels):
            for case in labels["cases"]:
                for e in case["expected"].values():
                    if isinstance(e, dict) and e.get("evidence_units_required", 0) >= 2:
                        e["acceptable_evidence"]["units"].pop()
                        return
            raise AssertionError("no multi-unit instance found")
        r = run("validate_labels.py", "--labels", self.scratch_labels(plant), "--quiet")
        self.assertEqual(r.returncode, 1)
        self.assertIn("acceptable units against", r.stdout)

    def test_validate_labels_catches_a_one_sided_contradiction(self) -> None:
        """CONFLICTING_EVIDENCE with both units on the same side is not a conflict."""
        def plant(labels):
            for case in labels["cases"]:
                for e in case["expected"].values():
                    if isinstance(e, dict) and "CONFLICTING_EVIDENCE" in e["reason_codes"]:
                        for unit in e["acceptable_evidence"]["units"]:
                            unit["role"] = "supporting"
                        return
            raise AssertionError("no CONFLICTING_EVIDENCE instance found")
        r = run("validate_labels.py", "--labels", self.scratch_labels(plant), "--quiet")
        self.assertEqual(r.returncode, 1)
        self.assertIn("a contradiction needs both sides", r.stdout)

    def test_every_reference_quote_resolves_in_its_document(self) -> None:
        """The reference may not cite what Step 4 would reject.

        Checked directly rather than through a script, because this is a
        property of the data and of the ingestion path together.
        """
        import json as _json
        from um_evidence import canonicalize, ingest_case
        labels = _json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())
        cases = PROJECT_ROOT / "corpus" / "cases"
        checked = 0
        for case in labels["cases"]:
            spec = [e for e in case["expected"].values()
                    if isinstance(e, dict) and e.get("acceptable_evidence")]
            if not any(a["acceptable_evidence"]["units"] or
                       a["acceptable_evidence"]["also_acceptable"] for a in spec):
                continue
            packet = ingest_case(case["case_id"], cases)
            for e in spec:
                entries = [q for u in e["acceptable_evidence"]["units"] for q in u["quotes"]]
                entries += e["acceptable_evidence"]["also_acceptable"]
                for entry in entries:
                    checked += 1
                    doc = packet.by_id(entry["document_id"])
                    spans = doc.locate(entry["quote"])
                    self.assertEqual(
                        len(spans), 1,
                        f"{case['case_id']} {entry['filename']}: quote resolves to "
                        f"{len(spans)} spans in its own document")
                    # The span holds canonical text; the stored quote is as
                    # written, which may carry line breaks and runs of spaces.
                    # Comparing them raw would fail on exactly the passages the
                    # normalization exists to make citable.
                    self.assertEqual(
                        doc.canonical[entry["start"]:entry["end"]],
                        canonicalize(entry["quote"]).canonical,
                        f"{case['case_id']}: recorded span does not contain its quote")
        self.assertGreater(checked, 250, "far fewer quotes than expected")

    # -- check_lexical_constraints ---------------------------------------

    def test_lexical_constraints_catches_a_planted_term(self) -> None:
        """MRI-005 C3 forbids the word NSAID anywhere in its packet.

        Writing it in would destroy the semantic instance silently: the label
        still reads MET and the packet still supports it.
        """
        def plant(cases_dir):
            note = cases_dir / "MRI-005" / "2026-08-17_medication_reconciliation.txt"
            note.write_text(note.read_text().replace(
                "Meloxicam 15 mg", "Meloxicam (an NSAID) 15 mg"))

        r = run("check_lexical_constraints.py",
                "--cases_dir", self.scratch_cases(plant))
        self.assertEqual(r.returncode, 1, "a prohibited term was not reported")
        self.assertIn("NSAID", r.stdout)
        self.assertIn("MRI-005", r.stdout)

    def test_lexical_constraints_passes_on_the_real_corpus(self) -> None:
        self.assertEqual(run("check_lexical_constraints.py").returncode, 0)

    # -- check_packet_dates ----------------------------------------------

    def test_packet_dates_catches_a_forward_reference(self) -> None:
        """A document citing a date later than its own is an authoring error."""
        def plant(cases_dir):
            note = cases_dir / "MRI-005" / "2026-06-15_office_note.txt"
            note.write_text(note.read_text().replace(
                "Follow up 3 months, sooner if sugars run high.",
                "Reviewed the MRI result of 09/20/2026 with her."))

        r = run("check_packet_dates.py", "--cases_dir", self.scratch_cases(plant))
        self.assertIn("09/20/2026", r.stdout)
        self.assertIn("MRI-005", r.stdout)

    # -- check_criteria_contamination ------------------------------------

    def test_contamination_check_is_verified_elsewhere(self) -> None:
        """Covered by tests/test_extract.py, which plants a packet sentence in
        the assembled prompt and asserts the comparison objects. Named here so
        the battery audit is complete in one place."""
        from test_extract import PromptContaminationTests
        self.assertTrue(hasattr(PromptContaminationTests,
                                "test_the_contamination_check_can_actually_fail"))

    # -- the split lock ---------------------------------------------------

    def test_split_lock_is_verified_elsewhere(self) -> None:
        """Covered by tests/test_split_lock.py, and demonstrated for real: the
        lock fired on 2026-09-10 when a locked label changed, and again on the
        manifest when three development labels were amended."""
        from test_split_lock import SplitLockTests
        self.assertTrue(hasattr(SplitLockTests, "test_locked_labels_are_unchanged"))


if __name__ == "__main__":
    unittest.main()
