"""Step 2: ingest a case packet into documents with ids, hashes, and spans.

Deterministic. No model call and no network.

The failure paths here are not edge cases. Spec Section 13 requires the
demonstration to show a processing failure surfaced as a visible incomplete
state rather than as a clinical result, so an unreadable document, a scan with
no text layer, an empty file, and an oversized input are each a named outcome
that ingestion returns, not an exception that something upstream happens to
catch. `DocumentOutcome` enumerates them and every one carries through to the
packet's `ProcessingStatus`.

There is no code path in this module that produces a clinical status.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .results import DocumentOutcome, ProcessingStatus, Span, StepResult
from .spans import CanonicalText, canonicalize

TEXT_SUFFIXES = {".txt", ".md"}
PDF_SUFFIXES = {".pdf"}

# Conservative characters-per-token divisor for the Step 2 input gate.
#
# Spec Section 5 requires the token count to be computed before any model call,
# and CLAUDE.md requires Step 2 to be deterministic and model-free. Those two
# together rule out the API token counter here, which is a network call. So this
# is an estimate, and it is deliberately biased to over-count: a low divisor
# yields a higher token estimate, so the gate trips early rather than late. An
# input wrongly flagged as oversized is a visible, correctable result; an input
# wrongly passed is a truncation or an error at Step 3, which is the outcome the
# spec forbids.
#
# The exact count is taken at the Step 3 boundary where a model call is already
# being made, and both numbers are recorded in the run log so the estimate can
# be checked against reality rather than trusted.
CHARS_PER_TOKEN_CONSERVATIVE = 3.0

DEFAULT_TOKEN_LIMIT = 150_000


def estimate_tokens(text: str) -> int:
    """Deterministic conservative token estimate. Not an exact count.

    Named `estimate` rather than `count` because calling it a count would
    invite someone to report it as one.
    """
    return math.ceil(len(text) / CHARS_PER_TOKEN_CONSERVATIVE)


def document_id_for(case_id: str, filename: str) -> str:
    """Stable identity for a document slot, independent of its content.

    Spec Section 12 aligns evidence to DocumentReference, where an identifier
    and a version are separate things. The id names the slot and survives an
    edit; `content_sha256` is the version and does not. A citation carries both,
    so a span recorded against content that has since changed is detectable
    rather than silently wrong.
    """
    digest = hashlib.sha256(f"{case_id}/{filename}".encode()).hexdigest()
    return f"doc_{digest[:12]}"


@dataclass
class IngestedDocument:
    document_id: str
    case_id: str
    filename: str
    suffix: str
    byte_size: int
    content_sha256: str
    outcome: DocumentOutcome
    detail: str = ""
    text: CanonicalText | None = None
    estimated_tokens: int = 0
    page_count: int | None = None

    @property
    def canonical(self) -> str:
        return self.text.canonical if self.text else ""

    def span(self, start: int, end: int) -> Span:
        if self.text is None:
            raise ValueError(
                f"{self.document_id} has no canonical text ({self.outcome.value}); "
                f"it cannot be cited")
        if end > len(self.text.canonical):
            raise ValueError(f"span [{start}, {end}) exceeds document length")
        return Span(self.document_id, self.content_sha256, start, end)

    def locate(self, quote: str) -> list[Span]:
        """Every span where this quote occurs. Empty if it does not."""
        if self.text is None:
            return []
        return [self.span(a, b) for a, b in self.text.find_all(quote)]

    def as_dict(self) -> dict:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "content_sha256": self.content_sha256,
            "byte_size": self.byte_size,
            "outcome": self.outcome.value,
            "detail": self.detail,
            "canonical_length": len(self.canonical),
            "estimated_tokens": self.estimated_tokens,
            "page_count": self.page_count,
        }


@dataclass
class IngestedPacket:
    case_id: str
    documents: list[IngestedDocument] = field(default_factory=list)
    manifest_check: dict = field(default_factory=dict)
    token_limit: int = DEFAULT_TOKEN_LIMIT

    @property
    def usable(self) -> list[IngestedDocument]:
        return [d for d in self.documents if d.outcome.is_usable]

    @property
    def failed(self) -> list[IngestedDocument]:
        return [d for d in self.documents if not d.outcome.is_usable]

    @property
    def estimated_tokens(self) -> int:
        return sum(d.estimated_tokens for d in self.usable)

    @property
    def processing_status(self) -> ProcessingStatus:
        """Packet-level state. Never converted into a clinical status.

        No usable document, or an input over the limit, is FAILED: there is
        nothing to review, or reviewing it would require truncation. Some
        documents usable and some not is PARTIAL, which is reportable with the
        state visible. Everything usable is COMPLETE.
        """
        if not self.documents:
            return ProcessingStatus.FAILED
        if any(d.outcome is DocumentOutcome.INPUT_LIMIT_EXCEEDED for d in self.documents):
            return ProcessingStatus.FAILED
        if self.estimated_tokens > self.token_limit:
            return ProcessingStatus.FAILED
        if not self.usable:
            return ProcessingStatus.FAILED
        if self.failed:
            return ProcessingStatus.PARTIAL
        return ProcessingStatus.COMPLETE

    def by_id(self, document_id: str) -> IngestedDocument:
        for d in self.documents:
            if d.document_id == document_id:
                return d
        raise KeyError(document_id)

    def locate(self, quote: str) -> list[Span]:
        """Every span in the packet where this quote occurs, across documents.

        Copy-forward means the same sentence legitimately appears in more than
        one note, so a quote alone does not identify a location. MRI-005 carries
        a 299-character block shared verbatim by the June and August notes. A
        citation naming only that text is ambiguous between two encounters nine
        weeks apart, which is exactly the distinction MRI-005 C2 turns on.

        Returning all of them, each carrying its own document_id, is what makes
        the ambiguity visible to Step 4 rather than resolved by accident of
        iteration order.
        """
        return [s for d in self.usable for s in d.locate(quote)]

    def as_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "processing_status": self.processing_status.value,
            "document_count": len(self.documents),
            "usable_documents": len(self.usable),
            "estimated_tokens": self.estimated_tokens,
            "token_limit": self.token_limit,
            "manifest_check": self.manifest_check,
            "documents": [d.as_dict() for d in self.documents],
        }


def _read_text_file(path: Path) -> tuple[str, DocumentOutcome, str]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return "", DocumentOutcome.UNREADABLE, f"could not read file: {exc}"
    if not raw.strip():
        return "", DocumentOutcome.EMPTY, "file contains no content"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        return "", DocumentOutcome.UNREADABLE, f"not valid UTF-8: {exc}"
    if not text.strip():
        return "", DocumentOutcome.EMPTY, "file contains only whitespace"
    return text, DocumentOutcome.OK, ""


def _read_pdf(path: Path) -> tuple[str, DocumentOutcome, str, int | None]:
    """Extract text from a text-based PDF. No OCR, per Spec Section 14.

    A PDF with pages but no extractable text is a scan. That is reported as
    NO_TEXT_LAYER rather than as an empty document, because the two call for
    different things from a reviewer: an empty file is a transmission problem,
    a scan needs a readable copy requesting.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", DocumentOutcome.UNREADABLE, "pypdf is not installed", None
    try:
        reader = PdfReader(str(path))
        pages = len(reader.pages)
        extracted = "\n".join((p.extract_text() or "") for p in reader.pages)
    except Exception as exc:  # pypdf raises a wide variety on malformed input
        return "", DocumentOutcome.UNREADABLE, f"could not parse PDF: {exc}", None
    if pages == 0:
        return "", DocumentOutcome.EMPTY, "PDF has no pages", 0
    if not extracted.strip():
        return ("", DocumentOutcome.NO_TEXT_LAYER,
                f"PDF has {pages} page(s) with no extractable text, which indicates a "
                f"scanned document. OCR is out of scope, so this document cannot be "
                f"cited and the case cannot be reviewed as complete.", pages)
    return extracted, DocumentOutcome.OK, "", pages


def ingest_document(path: Path, case_id: str,
                    per_document_token_limit: int | None = None) -> IngestedDocument:
    """Ingest one file into a document with an id, a hash, and canonical text."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        return IngestedDocument(
            document_id=document_id_for(case_id, path.name), case_id=case_id,
            filename=path.name, suffix=path.suffix.lower(), byte_size=0,
            content_sha256="", outcome=DocumentOutcome.UNREADABLE,
            detail=f"could not read file: {exc}")

    doc = IngestedDocument(
        document_id=document_id_for(case_id, path.name),
        case_id=case_id,
        filename=path.name,
        suffix=path.suffix.lower(),
        byte_size=len(raw_bytes),
        content_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        outcome=DocumentOutcome.OK,
    )

    if doc.suffix in TEXT_SUFFIXES:
        text, outcome, detail = _read_text_file(path)
    elif doc.suffix in PDF_SUFFIXES:
        text, outcome, detail, doc.page_count = _read_pdf(path)
    else:
        text, outcome, detail = "", DocumentOutcome.UNSUPPORTED_TYPE, (
            f"{doc.suffix or 'no extension'} is not a supported document type. "
            f"Supported: {', '.join(sorted(TEXT_SUFFIXES | PDF_SUFFIXES))}.")

    doc.outcome = outcome
    doc.detail = detail
    if outcome is not DocumentOutcome.OK:
        return doc

    doc.text = canonicalize(text)
    doc.estimated_tokens = estimate_tokens(doc.text.canonical)

    if per_document_token_limit is not None and doc.estimated_tokens > per_document_token_limit:
        doc.outcome = DocumentOutcome.INPUT_LIMIT_EXCEEDED
        doc.detail = (
            f"estimated {doc.estimated_tokens} tokens against a per-document limit of "
            f"{per_document_token_limit}. Returned as an explicit input-limit result. "
            f"The document is not truncated and is not partially submitted.")
        doc.text = None
    return doc


def ingest_case(case_id: str, cases_dir: Path | str,
                token_limit: int = DEFAULT_TOKEN_LIMIT,
                per_document_token_limit: int | None = None,
                manifest_path: Path | str | None = None) -> IngestedPacket:
    """Ingest every document in a case directory.

    Hashes and ids are computed here from the files on disk and then compared
    against the manifest. The comparison is one-way on purpose: reading identity
    out of the manifest would let ingestion inherit a manifest error without
    anyone noticing, which is the failure class this project has already hit
    with checkers that could not fail.
    """
    case_dir = Path(cases_dir) / case_id
    packet = IngestedPacket(case_id=case_id, token_limit=token_limit)

    if not case_dir.is_dir():
        packet.manifest_check = {"status": "not_checked",
                                 "detail": f"no packet directory at {case_dir}"}
        return packet

    for path in sorted(p for p in case_dir.iterdir() if p.is_file()):
        packet.documents.append(
            ingest_document(path, case_id, per_document_token_limit))

    packet.manifest_check = _check_against_manifest(packet, manifest_path)
    return packet


def _check_against_manifest(packet: IngestedPacket,
                            manifest_path: Path | str | None) -> dict:
    """Compare independently computed hashes against the recorded manifest."""
    path = Path(manifest_path) if manifest_path else (
        Path(__file__).resolve().parents[1] / "corpus" / "manifest.json")
    if not path.exists():
        return {"status": "not_checked", "detail": f"no manifest at {path}"}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "not_checked", "detail": f"manifest unreadable: {exc}"}

    entry = next((e for e in manifest["cases"] if e["case_id"] == packet.case_id), None)
    if entry is None:
        return {"status": "absent",
                "detail": f"{packet.case_id} is not in the manifest"}

    recorded = {d["filename"]: d["sha256"] for d in entry["documents"]}
    computed = {d.filename: d.content_sha256 for d in packet.documents}
    mismatches = [f for f in recorded.keys() & computed.keys()
                  if recorded[f] != computed[f]]
    missing = sorted(recorded.keys() - computed.keys())
    extra = sorted(computed.keys() - recorded.keys())

    if mismatches or missing or extra:
        return {
            "status": "mismatch",
            "changed": sorted(mismatches),
            "in_manifest_not_on_disk": missing,
            "on_disk_not_in_manifest": extra,
            "detail": ("Ingestion computed hashes that disagree with the manifest. "
                       "Either a packet changed without the manifest being rebuilt, "
                       "or the manifest is wrong. Ingestion has used what is on disk "
                       "and reported the disagreement rather than adopting either as "
                       "authoritative."),
        }
    return {"status": "match", "documents_checked": len(recorded)}


def ingest_step(case_id: str, cases_dir: Path | str, **kwargs) -> StepResult:
    """Step 2 as a pipeline step."""
    packet = ingest_case(case_id, cases_dir, **kwargs)
    status = packet.processing_status
    bits = [f"{len(packet.usable)}/{len(packet.documents)} documents usable",
            f"~{packet.estimated_tokens} tokens (estimate)"]
    for d in packet.failed:
        bits.append(f"{d.filename}: {d.outcome.value}")
    if packet.manifest_check.get("status") == "mismatch":
        bits.append("manifest mismatch")
    return StepResult(step="2_ingest_documents", processing_status=status,
                      detail="; ".join(bits), payload=packet)
