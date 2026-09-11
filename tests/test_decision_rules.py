"""Guards for evals/decision_rules.md.

The decision rules are recorded before any experiment runs so the numbers cannot
be adjusted after results are seen. Copying Spec Section 9 into a second file
creates a way for the two to silently diverge, which would defeat the purpose of
recording them. These tests close that gap: the verbatim block is compared
byte-for-byte against the spec on every run.
"""

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = PROJECT_ROOT / "docs" / "PROTOTYPE_SPEC.md"
RULES_PATH = PROJECT_ROOT / "evals" / "decision_rules.md"

BEGIN_MARKER = "<!-- BEGIN VERBATIM: docs/PROTOTYPE_SPEC.md Section 9 -->"
END_MARKER = "<!-- END VERBATIM -->"


def spec_section_9() -> str:
    text = SPEC_PATH.read_text(encoding="utf-8")
    match = re.search(r"^## 9\. Metrics\n(.*?)(?=^## 10\. )", text, re.S | re.M)
    if match is None:
        raise AssertionError("Section 9 not found in the spec")
    return match.group(1).strip("\n")


def recorded_verbatim_block() -> str:
    text = RULES_PATH.read_text(encoding="utf-8")
    start = text.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end = text.index(END_MARKER)
    return text[start:end].strip("\n")


class VerbatimBlockTests(unittest.TestCase):
    def test_file_exists(self) -> None:
        self.assertTrue(RULES_PATH.exists(), "evals/decision_rules.md is missing")

    def test_markers_present(self) -> None:
        text = RULES_PATH.read_text(encoding="utf-8")
        self.assertIn(BEGIN_MARKER, text)
        self.assertIn(END_MARKER, text)

    def test_block_matches_spec_exactly(self) -> None:
        self.assertEqual(
            recorded_verbatim_block(),
            spec_section_9(),
            "evals/decision_rules.md has drifted from Spec Section 9. "
            "Regenerate the verbatim block rather than hand-editing either side.",
        )

    def test_adoption_threshold_numbers_are_present(self) -> None:
        # Cheap tripwire: if the block is ever replaced by a summary that still
        # matches loosely, the specific figures should still be findable.
        block = recorded_verbatim_block()
        for figure in ("48 criterion instances", "10 percentage points", "5 percentage points"):
            with self.subTest(figure=figure):
                self.assertIn(figure, block)


class SupplementTests(unittest.TestCase):
    """The authored sections must keep saying the things they exist to say."""

    def setUp(self) -> None:
        self.text = RULES_PATH.read_text(encoding="utf-8")

    def test_scoring_contract_directs_the_harness_to_instance_values(self) -> None:
        self.assertIn("Read evidence requirements from the instance", self.text)
        self.assertIn("cases[].expected", self.text)

    def test_transfer_scope_is_stated(self) -> None:
        self.assertIn(
            "Transfer tests procedure generalization only, not scenario generalization",
            self.text,
        )

    def test_unmeasurable_direction_is_stated(self) -> None:
        # Not pinned to a phrase. What must hold is that both critical error
        # directions are recorded as counts rather than rates, and that the
        # smaller one is stated as unmeasurable at this corpus size.
        self.assertIn("Counts, with every affected case named", self.text)
        self.assertIn("neither is reported as a rate", self.text)
        self.assertIn("unmeasured rather than", self.text)
        self.assertIn("not measurable", self.text.lower())

    def test_supplements_are_marked_as_authored(self) -> None:
        # Nobody should later read the authored prose as part of the frozen rule.
        self.assertEqual(self.text.count("Authored supplement"), 2)


if __name__ == "__main__":
    unittest.main()
