"""The correction store, and the isolation that makes it safe.

The store exists so the reviewer's half of the workflow is demonstrable rather
than described. What makes it safe is that it cannot reach two things: the
reference labels, and the scorer. Both are asserted here rather than left to
convention, because a convention is what gets broken by someone adding a
convenient import.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import corrections  # noqa: E402


class IsolationTests(unittest.TestCase):
    """What the correction store must not be able to touch."""

    def test_the_scorer_does_not_import_corrections(self) -> None:
        """A reviewer disagreeing is not evidence about reference agreement.

        Letting corrections reach the scorer would let the evaluation be
        tuned by the people reading it.
        """
        source = (PROJECT_ROOT / "um_evidence" / "score.py").read_text()
        self.assertNotIn("corrections", source,
                         "score.py must not reference the correction store")

    def test_no_module_writes_corrections_into_labels_or_runs(self) -> None:
        """Corrections are not reference labels and never become them.

        Checked against executable code with docstrings stripped. The module
        names those paths in prose to say it does not touch them, and a naive
        text search reads that as the violation it is disclaiming.
        """
        import ast
        tree = ast.parse(
            (PROJECT_ROOT / "um_evidence" / "corrections.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
                if (node.body and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                        and isinstance(node.body[0].value.value, str)):
                    node.body.pop(0)
        code = ast.unparse(tree)
        for forbidden in ("labels.json", "runs/", "SPLIT_LOCK"):
            self.assertNotIn(forbidden, code,
                             f"corrections.py must not touch {forbidden}")

    def test_there_is_no_promote_to_labels_function(self) -> None:
        names = [n for n in dir(corrections) if not n.startswith("_")]
        for suspicious in ("promote", "apply", "merge", "to_labels", "sync"):
            self.assertFalse(
                any(suspicious in n.lower() for n in names),
                f"a function named like {suspicious!r} would let a reviewer's "
                f"judgement become a reference label")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.path = self.tmp / "corrections.jsonl"
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_a_correction_is_appended_not_overwritten(self) -> None:
        corrections.record("run-1", "MRI-005", "C1", "status_wrong",
                           "The record does document this.", path=self.path)
        corrections.record("run-1", "MRI-005", "C1", "status_wrong",
                           "On reflection the first note was wrong.",
                           path=self.path)
        loaded = corrections.load(self.path)
        self.assertEqual(len(loaded), 2, "a second view must not replace the first")
        self.assertIn("On reflection", loaded[1].reason)

    def test_a_correction_snapshots_what_the_system_said(self) -> None:
        c = corrections.record(
            "run-1", "MRI-005", "C3", "evidence_wrong", "Wrong drug class.",
            result={"clinical_status": "MET", "processing_status": "COMPLETE",
                    "reason_codes": [], "evidence": [{"quote": "x"}]},
            path=self.path)
        self.assertEqual(c.system_clinical_status, "MET")
        self.assertEqual(c.system_evidence_count, 1)

    def test_a_reason_is_required(self) -> None:
        # A bare disagreement is not reviewable by anyone else.
        for blank in ("", "   ", "\n"):
            with self.assertRaises(ValueError):
                corrections.record("run-1", "MRI-005", "C1", "other", blank,
                                   path=self.path)

    def test_an_unknown_kind_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            corrections.record("run-1", "MRI-005", "C1", "DENIED",
                               "reason", path=self.path)

    def test_kinds_carry_no_determination_vocabulary(self) -> None:
        """A reviewer flags a row as unusable; they do not enter a decision."""
        for kind in corrections.DISAGREEMENT_KINDS:
            for banned in ("approve", "deny", "denied", "authorize", "reject"):
                self.assertNotIn(banned, kind.lower())

    def test_corrections_are_retrievable_per_run_and_row(self) -> None:
        corrections.record("run-1", "MRI-005", "C1", "status_wrong", "a",
                           path=self.path)
        corrections.record("run-2", "MRI-005", "C1", "status_wrong", "b",
                           path=self.path)
        one = corrections.for_run("run-1", self.path)
        self.assertEqual(list(one), [("MRI-005", "C1")])
        self.assertEqual(len(one[("MRI-005", "C1")]), 1)

    def test_an_absent_store_is_empty_not_an_error(self) -> None:
        self.assertEqual(corrections.load(self.tmp / "nothing.jsonl"), [])


if __name__ == "__main__":
    unittest.main()
