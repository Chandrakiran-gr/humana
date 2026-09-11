"""Tests for Steps 1 and 2.

The failure paths get the most attention here. Spec Section 13 requires a
processing failure to surface as a visible incomplete state rather than as a
clinical result, so an unreadable document, a scan, an empty file and an
oversized input are behaviours to assert, not exceptions to tolerate.

Every fixture is built in the test rather than committed, so the assertions run
against a real three-page PDF with no text layer and a real invalid-UTF-8 file
rather than against something that merely stands for one.
"""

import logging
import shutil
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path

# The truncated-PDF fixture makes pypdf log "EOF marker not found". That is the
# fixture working, so it is silenced rather than left to look like a test error.
logging.getLogger("pypdf").setLevel(logging.CRITICAL)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from um_evidence import (  # noqa: E402
    DocumentOutcome, ProcessingStatus, UnsupportedProcedure, canonicalize,
    declared_criteria_version, document_id_for, estimate_tokens, ingest_case,
    ingest_document, load_criteria, load_criteria_by_cpt, load_step,
)


def write_fixtures(case_dir: Path) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=595, height=842)
    with open(case_dir / "2026-01-01_scanned.pdf", "wb") as fh:
        writer.write(fh)
    (case_dir / "2026-01-02_empty.txt").write_text("")
    (case_dir / "2026-01-03_whitespace.txt").write_text("\n\n   \t \n")
    (case_dir / "2026-01-04_oversized.txt").write_text("Clinical narrative. " * 40000)
    (case_dir / "2026-01-05_scan.tiff").write_bytes(b"II*\x00not a tiff")
    (case_dir / "2026-01-06_corrupt.txt").write_bytes(b"Note \xff\xfe\x00 broken")
    (case_dir / "2026-01-07_truncated.pdf").write_bytes(b"%PDF-1.4\ntruncated")
    (case_dir / "2026-01-08_good.txt").write_text("CLINIC NOTE\n\nLow back pain for\n10 weeks.\n")


class CanonicalTextTests(unittest.TestCase):
    def test_only_whitespace_is_altered(self) -> None:
        # The guarantee the whole representation rests on. Strip whitespace from
        # both sides and they must be identical: no character that is not
        # whitespace may be added, removed, or changed.
        for raw in [
            "Right ankle dorsiflexion 4+/5.\nGreat toe 3/5.",
            "Temperature 36.6 C\r\nBP 132/78",
            "L4-5 and L5-S1, Modic type 2.",
            "  leading and trailing   ",
            "naïve café résumé",
        ]:
            with self.subTest(raw=raw[:24]):
                c = canonicalize(raw)
                strip = lambda s: "".join(ch for ch in s if not ch.isspace())
                self.assertEqual(strip(c.canonical),
                                 strip(unicodedata.normalize("NFC", raw)))

    def test_offset_map_projects_every_span_back(self) -> None:
        c = canonicalize("Motor 5/5\nbilaterally.\r\n\r\n  Sensation  intact.")
        self.assertEqual(len(c.offsets), len(c.canonical) + 1)
        for i in range(len(c.canonical)):
            a, _ = c.to_raw(i, i + 1)
            ch = c.canonical[i]
            if ch.isspace():
                # A collapsed run maps back to its first raw character, which is
                # whichever whitespace started the run, not necessarily a space.
                self.assertEqual(ch, " ", "canonical whitespace is always a single space")
                self.assertTrue(c.raw[a].isspace(),
                                f"canonical[{i}] maps to non-whitespace {c.raw[a]!r}")
            else:
                self.assertEqual(c.raw[a], ch,
                                 f"canonical[{i}] does not map to its raw character")

    def test_quote_wrapped_across_a_line_break_still_matches(self) -> None:
        # The case the normalization exists for. Without it a correct citation
        # is rejected as unverifiable and a sound conclusion is downgraded.
        c = canonicalize("she reports finishing\nit as directed and says")
        hits = c.find_all("reports finishing it as directed")
        self.assertEqual(len(hits), 1)
        self.assertIn("\n", c.raw_slice(*hits[0]))

    def test_repeated_quote_yields_distinct_spans(self) -> None:
        c = canonicalize("no back pain today.\nLater: no back pain today.")
        hits = c.find_all("no back pain today")
        self.assertEqual(len(hits), 2)
        self.assertNotEqual(hits[0], hits[1])

    def test_empty_and_whitespace_only(self) -> None:
        for raw in ("", "   \n\t "):
            c = canonicalize(raw)
            self.assertEqual(c.canonical, "")
            self.assertEqual(len(c.offsets), 1)


class CriteriaLoadingTests(unittest.TestCase):
    def test_loads_each_procedure(self) -> None:
        for pid, n in (("lumbar_mri", 5), ("total_knee_arthroplasty", 7), ("lumbar_fusion", 9)):
            with self.subTest(procedure=pid):
                cs = load_criteria(pid)
                self.assertEqual(len(cs.criteria), n)
                # Not pinned to a literal: that would be a second source for
                # the version. What matters is that the loader reports what
                # the file declares.
                self.assertEqual(cs.version, declared_criteria_version())

    def test_lookup_by_cpt(self) -> None:
        self.assertEqual(load_criteria_by_cpt("27447").procedure_id, "total_knee_arthroplasty")

    def test_unsupported_procedure_is_explicit_not_a_guess(self) -> None:
        with self.assertRaises(UnsupportedProcedure):
            load_criteria("cervical_fusion")
        result = load_step("cervical_fusion")
        self.assertIs(result.processing_status, ProcessingStatus.FAILED)
        self.assertFalse(result.can_continue)

    def test_rule_prose_travels_with_the_set(self) -> None:
        cs = load_criteria("lumbar_fusion")
        for key in ("not_met_bar", "addresses_rule", "waiver_rule"):
            self.assertIn(key, cs.rules)


class IngestionFailurePathTests(unittest.TestCase):
    """Each named outcome, against a fixture that genuinely produces it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = Path(tempfile.mkdtemp())
        write_fixtures(cls.tmp / "FX-001")

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def outcome_for(self, filename: str, **kw) -> DocumentOutcome:
        return ingest_document(self.tmp / "FX-001" / filename, "FX-001", **kw).outcome

    def test_scanned_pdf_is_no_text_layer_not_empty(self) -> None:
        doc = ingest_document(self.tmp / "FX-001" / "2026-01-01_scanned.pdf", "FX-001")
        self.assertIs(doc.outcome, DocumentOutcome.NO_TEXT_LAYER)
        self.assertEqual(doc.page_count, 3)
        self.assertIn("scanned", doc.detail.lower())

    def test_empty_and_whitespace_only_files(self) -> None:
        self.assertIs(self.outcome_for("2026-01-02_empty.txt"), DocumentOutcome.EMPTY)
        self.assertIs(self.outcome_for("2026-01-03_whitespace.txt"), DocumentOutcome.EMPTY)

    def test_oversized_input_is_flagged_and_not_truncated(self) -> None:
        doc = ingest_document(self.tmp / "FX-001" / "2026-01-04_oversized.txt",
                              "FX-001", per_document_token_limit=100_000)
        self.assertIs(doc.outcome, DocumentOutcome.INPUT_LIMIT_EXCEEDED)
        self.assertIsNone(doc.text, "an over-limit document must not carry partial text")
        self.assertIn("not truncated", doc.detail)

    def test_unsupported_type_and_unreadable(self) -> None:
        self.assertIs(self.outcome_for("2026-01-05_scan.tiff"), DocumentOutcome.UNSUPPORTED_TYPE)
        self.assertIs(self.outcome_for("2026-01-06_corrupt.txt"), DocumentOutcome.UNREADABLE)
        self.assertIs(self.outcome_for("2026-01-07_truncated.pdf"), DocumentOutcome.UNREADABLE)

    def test_a_document_without_text_cannot_be_cited(self) -> None:
        doc = ingest_document(self.tmp / "FX-001" / "2026-01-02_empty.txt", "FX-001")
        with self.assertRaises(ValueError):
            doc.span(0, 1)
        self.assertEqual(doc.locate("anything"), [])

    def test_packet_status_reflects_document_outcomes(self) -> None:
        d = self.tmp / "STATUS"
        d.mkdir(exist_ok=True)
        good = "CLINIC NOTE\nLow back pain.\n"

        (d / "a.txt").write_text(good)
        self.assertIs(ingest_case("STATUS", self.tmp).processing_status,
                      ProcessingStatus.COMPLETE)

        (d / "b.txt").write_text("")
        self.assertIs(ingest_case("STATUS", self.tmp).processing_status,
                      ProcessingStatus.PARTIAL)

        (d / "a.txt").unlink()
        self.assertIs(ingest_case("STATUS", self.tmp).processing_status,
                      ProcessingStatus.FAILED,
                      "no usable document must be FAILED, not PARTIAL")

        (d / "a.txt").write_text(good)
        (d / "c.txt").write_text("word " * 60000)
        self.assertIs(ingest_case("STATUS", self.tmp, per_document_token_limit=1000
                                  ).processing_status, ProcessingStatus.FAILED,
                      "an over-limit document must fail the packet, not degrade it")

    def test_missing_packet_directory_fails(self) -> None:
        self.assertIs(ingest_case("NOPE", self.tmp).processing_status,
                      ProcessingStatus.FAILED)

    def test_token_estimate_is_conservative(self) -> None:
        # Biased to over-count so the gate trips early. A wrongly flagged input
        # is visible and correctable; a wrongly passed one truncates at Step 3.
        text = "The patient reports low back pain radiating into the left leg."
        self.assertGreater(estimate_tokens(text), len(text.split()))


class RealPacketTests(unittest.TestCase):
    CASES = PROJECT_ROOT / "corpus" / "cases"

    def test_every_corpus_packet_ingests_complete(self) -> None:
        for case_dir in sorted(p for p in self.CASES.iterdir() if p.is_dir()):
            with self.subTest(case=case_dir.name):
                packet = ingest_case(case_dir.name, self.CASES)
                self.assertIs(packet.processing_status, ProcessingStatus.COMPLETE)

    def test_ingestion_agrees_with_the_manifest(self) -> None:
        # Independently computed, then compared. Ingestion never reads identity
        # out of the manifest, so a manifest error surfaces instead of being
        # inherited.
        for case_dir in sorted(p for p in self.CASES.iterdir() if p.is_dir()):
            with self.subTest(case=case_dir.name):
                self.assertEqual(
                    ingest_case(case_dir.name, self.CASES).manifest_check["status"],
                    "match")

    def test_document_ids_are_stable_and_unique(self) -> None:
        seen = {}
        for case_dir in sorted(p for p in self.CASES.iterdir() if p.is_dir()):
            for doc in ingest_case(case_dir.name, self.CASES).documents:
                self.assertEqual(doc.document_id,
                                 document_id_for(case_dir.name, doc.filename))
                self.assertNotIn(doc.document_id, seen,
                                 f"id collision with {seen.get(doc.document_id)}")
                seen[doc.document_id] = f"{case_dir.name}/{doc.filename}"

    def test_document_id_is_independent_of_content(self) -> None:
        # Identifier names the slot; content_sha256 is the version.
        self.assertEqual(document_id_for("MRI-005", "a.txt"),
                         document_id_for("MRI-005", "a.txt"))
        self.assertNotEqual(document_id_for("MRI-005", "a.txt"),
                            document_id_for("MRI-006", "a.txt"))

    def test_the_manifest_check_can_actually_fail(self) -> None:
        """The agreement test above is worthless if the checker cannot disagree.

        Four of four checkers written for this corpus passed on their first run
        while the defect they targeted was present, so a check is not trusted
        here until it has been shown to fail on a real instance.
        """
        tmp = Path(tempfile.mkdtemp())
        try:
            work = tmp / "MRI-005"
            shutil.copytree(self.CASES / "MRI-005", work)
            manifest = PROJECT_ROOT / "corpus" / "manifest.json"
            self.assertEqual(
                ingest_case("MRI-005", tmp, manifest_path=manifest).manifest_check["status"],
                "match", "the copy should match before it is altered")

            target = work / "2026-08-17_office_note.txt"
            target.write_text(target.read_text() + "\nAddended.\n")
            check = ingest_case("MRI-005", tmp, manifest_path=manifest).manifest_check
            self.assertEqual(check["status"], "mismatch")
            self.assertIn("2026-08-17_office_note.txt", check["changed"])

            (work / "extra_note.txt").write_text("Unrecorded document.\n")
            check = ingest_case("MRI-005", tmp, manifest_path=manifest).manifest_check
            self.assertIn("extra_note.txt", check["on_disk_not_in_manifest"])

            target.unlink()
            check = ingest_case("MRI-005", tmp, manifest_path=manifest).manifest_check
            self.assertIn("2026-08-17_office_note.txt", check["in_manifest_not_on_disk"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_case_absent_from_the_manifest_says_so(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "ZZ-999").mkdir()
            (tmp / "ZZ-999" / "note.txt").write_text("Unregistered case.\n")
            check = ingest_case("ZZ-999", tmp).manifest_check
            self.assertEqual(check["status"], "absent")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_real_copy_forward_block_resolves_to_two_documents(self) -> None:
        """The case the span representation exists for, in real corpus data.

        MRI-005's August note carries a block forward verbatim from June. The
        quote is genuinely ambiguous: nothing in the text distinguishes the two
        occurrences, and they sit nine weeks apart, which is the interval C2
        derives. A citation carrying only the quote string cannot say which
        encounter it came from; a span carrying a document_id can.
        """
        packet = ingest_case("MRI-005", self.CASES)
        quote = ("She points to the right lower lumbar area and says it catches "
                 "when she gets up from the couch.")

        spans = packet.locate(quote)
        self.assertEqual(len(spans), 2, "the copy-forward duplicate has gone missing")
        self.assertEqual(len({s.document_id for s in spans}), 2,
                         "the two occurrences must be distinguishable by document")

        for span in spans:
            doc = packet.by_id(span.document_id)
            self.assertEqual(doc.canonical[span.start:span.end], quote)
            self.assertEqual(span.content_sha256, doc.content_sha256)

        # Per document it is one hit each, so the ambiguity is only visible at
        # packet level. That is why the packet-level lookup exists.
        self.assertEqual([len(d.locate(quote)) for d in packet.usable].count(1), 2)

    def test_spans_resolve_back_into_the_source(self) -> None:
        packet = ingest_case("MRI-005", self.CASES)
        doc = next(d for d in packet.documents if "medication" in d.filename)
        spans = doc.locate("trial completed, no relief")
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(doc.canonical[span.start:span.end], "trial completed, no relief")
        self.assertIn("trial completed", doc.text.raw_slice(span.start, span.end))
        self.assertEqual(span.content_sha256, doc.content_sha256)


if __name__ == "__main__":
    unittest.main()
