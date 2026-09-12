"""Reviewer interface. Task 3.3.

    streamlit run app.py

Two modes, and the interface always says which one it is in.

**Saved run** reads a recorded artifact from `runs/`. Citations resolve against
the packet exactly as they did when the run was made, so click-through works
with no API key. This is the default and it is what makes the repository
reviewable by someone who has not been given a key.

**Live run** executes Steps 1 to 5 against the selected case now. Spec
Section 13 requires a case run end to end rather than a recording, and this
provides it. It needs a key, costs money and can fail, so recorded is the
default: nobody should spend a call by opening the page.

A live run shows its work while it happens. All rows appear pending before
anything starts, then move through named stages — reading the record,
checking the quote, checking the quote supports the claim, done — so the
two-check design is visible rather than described, and a rejected quote
surfaces at the moment Step 4 rejects it.

**The extraction display is honest about Baseline A.** A is one call for all
criteria, so every row waits on it together and they resolve together. Rows
do not fill in one at a time until verification, which genuinely is per
criterion. Animating extraction row by row would depict the per-criterion
call structure of Candidate B, which the held-out comparison rejected. The
shared wait is the visible signature of the configuration that was adopted.

Live artifacts are written to `runs/live/`. The evaluation harness and the
recorded-run picker both read `runs/*.json`, a non-recursive glob, so a
demonstration cannot drop a file where a scored run is looked for.

The mode is displayed, never inferred silently. A saved run presented as though
it were live would be the same class of error as a stale status presented as
current, and in front of an audience it is the one nobody can catch.

What this interface does not have, deliberately:

- **No decision control.** No approve, deny, recommend, score, or aggregate.
  The output vocabulary is evidence status only. `tests/test_interface.py`
  asserts this file contains none of that vocabulary.
- **No add-document and no re-run.** Recorded as a scope decision in
  BUILD_SEQUENCE.md: a second run for one case requires a supersession model,
  and without one an interface shows stale clinical statuses as current.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from um_evidence import corrections, ingest_case, load_criteria
from um_evidence.faults import (
    Fault, NOT_A_RATE, corrupt_first_quote, replay_truncation,
)
from um_evidence.live import (
    LIVE_RUNS, STAGE_DONE, STAGE_FAILED, STAGE_PENDING, STAGE_QUOTE_CHECK,
    STAGE_READING, STAGE_SUPPORT_CHECK, run_live,
)

PROJECT_ROOT = Path(__file__).resolve().parent
RUNS = PROJECT_ROOT / "runs"
CASES = PROJECT_ROOT / "corpus" / "cases"

APP_NAME = "Cite"
APP_SUBTITLE = "Evidence mapping for utilization management"

# What a viewer sees while a live run is going. Plain words, because the
# audience for the processing display is not the person who wrote the
# pipeline. The two verification stages are named separately and deliberately:
# the two-check design is the architecture, and a single "verifying" would
# hide it behind a word.
STAGE_TEXT = {
    STAGE_PENDING: ("pending", "#8C8A84"),              # --ink-faint
    STAGE_READING: ("reading the record", "#1C2B45"),   # --navy
    STAGE_QUOTE_CHECK: ("checking the quote", "#8A5B0C"),          # --open
    STAGE_SUPPORT_CHECK: ("checking the quote supports the claim", "#8A5B0C"),
    STAGE_DONE: ("done", "#0F6E56"),                    # --found
    STAGE_FAILED: ("failed", "#4A4370"),                # --system
}

# ---------------------------------------------------------------------------
# Palette. Taken from the UI reference's CSS variables, not approximated.
# ---------------------------------------------------------------------------

PAPER = "#FAFAF8"
PANEL = "#FFFFFF"
RULE = "#E4E1DB"
RULE_SOFT = "#EFEDE8"    # divider inside a panel, lighter than its border
INK = "#16181A"          # primary text: requirements and quotes
INK_SOFT = "#4E5257"     # secondary
INK_FAINT = "#8B8F94"    # metadata: labels, counts, provenance
NAVY = "#1C2B45"         # chrome only, never a status
MARK = "#FFE89A"         # citation highlight in a source excerpt

# Clinical status is presented in the display wording of Spec Section 4, never
# as a bare enum and never as a determination.
#
# **No green and no red anywhere on a status.** Green reads as approved and
# red as denied, and this system produces neither. Humana's brand is green,
# which is the further reason a brand colour may appear in chrome and never
# here.
#
# `found` is a deep teal at hue 165, on the teal side of the green boundary
# and ΔE 24 from the nearest canonical success green. `mismatch` is a rust at
# hue 16, ΔE 22 from the nearest canonical alert red. Both clear the
# conventional ΔE 20 "clearly different" mark, the second of them not by
# much, and `tests/test_interface.py` records both margins rather than
# rounding them off.
#
# The processing-failure colour is slate and is not on the clinical scale at
# all: a failure is the absence of a clinical result, not a poor one.
#
# (label, foreground, background, edge)
DISPLAY = {
    "MET": ("Supporting evidence identified", "#0F6E56", "#E6F4EF", "#0F6E56"),
    "NOT_MET": ("Potential mismatch requiring review", "#9A3E1E", "#FAEDE8", "#9A3E1E"),
    "AMBIGUOUS": ("Insufficient or conflicting evidence", "#8A5B0C", "#FBF1DE", "#8A5B0C"),
    "NOT_APPLICABLE": ("Not required, waived by exception", "#5E5C57", "#F2F1EE", "#B9B5AD"),
    None: ("No clinical result produced", "#4A4370", "#EEEDF6", "#4A4370"),
}

# ---------------------------------------------------------------------------
# Presentation of internal identifiers.
#
# Filenames, procedure ids and reason codes are machine handles. They are how
# the pipeline addresses things and they belong in an artifact, not on a
# reviewer's screen: `2026-07-30_consultant_letter.txt` and `lumbar_fusion`
# read as debug output, and a screen full of debug output invites the reader
# to treat the whole thing as a developer tool rather than a record they are
# accountable for.
#
# The raw handle stays reachable. It is printed in the expanded passage
# detail beside the document hash and the character offsets, which is where
# provenance belongs, and the artifact filename stays verbatim under run
# details because that is an identifier a reviewer may need to quote.
# ---------------------------------------------------------------------------

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# Tokens that are initialisms rather than words, derived from the corpus
# filenames rather than guessed.
INITIALISMS = {"mri", "ct", "pt", "gp", "pcp", "hie", "mdt", "cpt", "nsaid",
               "xr", "emg", "esi", "adl", "odi", "mdm", "ed", "or"}


def humanise(token_string: str) -> str:
    """`consultant_letter` -> `Consultant letter`, preserving initialisms."""
    words = [w for w in token_string.replace("-", " ").split("_") if w]
    out = []
    for i, w in enumerate(words):
        if w.lower() in INITIALISMS:
            out.append(w.upper())
        elif w.isdigit():
            out.append(w)
        elif i == 0:
            out.append(w[:1].upper() + w[1:].lower())
        else:
            out.append(w.lower())
    return " ".join(out)


def document_parts(filename: str) -> tuple[str, str]:
    """`2026-07-30_consultant_letter.txt` -> `("Consultant letter", "30 July 2026")`.

    Name and date are returned separately because the passage cards show
    them in different places: the name is the card's heading and the date
    sits beside it as context. A leading document code with no date, as the
    injection documents carry, becomes the second element instead, since it
    is the only thing distinguishing those documents from one another.
    """
    import re
    stem = filename.rsplit(".", 1)[0]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[_-](.+)$", stem)
    if m:
        year, month, day, rest = m.groups()
        try:
            return humanise(rest), f"{int(day)} {MONTHS[int(month) - 1]} {year}"
        except (ValueError, IndexError):
            return humanise(stem), ""
    code = re.match(r"^([A-Za-z]{2,4}-\d+)[_-](.+)$", stem)
    if code:
        return humanise(code.group(2)), code.group(1).upper()
    return humanise(stem), ""


def document_label(filename: str) -> str:
    """One-line form, for the source line under a quote.

    A date is appended after a comma; a document code is bracketed, because
    "Patient portal message, INJ-01" reads as though INJ-01 were a date.
    """
    name, when = document_parts(filename)
    if not when:
        return name
    return f"{name}, {when}" if " " in when else f"{name} ({when})"


def reason_label(code: str) -> str:
    """Prose for a reason code, never the code itself.

    The fallback used to be the code, so an unmapped one would put
    `MISSING_EVIDENCE` on screen. It reads as a sentence either way now.
    """
    return REASON_TEXT.get(code, humanise(code.lower()) + ".")


# What a reviewer picks from when recording a disagreement. The store's own
# keys are snake_case; these are the same five choices in words.
DISAGREEMENT_LABEL = {
    "status_wrong": "The clinical result does not match the record",
    "evidence_wrong": "A cited passage does not support the row",
    "evidence_missing": "The record contains support that was not found",
    "citation_unusable": "The citation does not resolve to a readable place",
    "other": "Something else",
}

REASON_TEXT = {
    "MISSING_EVIDENCE": "Nothing in the record addresses this requirement.",
    "CONFLICTING_EVIDENCE": "Passages in the record disagree. Both sides shown.",
    "VAGUE_DURATION": "A time element is referenced without enough precision.",
    "INSUFFICIENT_CONTEXT": "Addressed but not settled by what is in the record.",
    "UNVERIFIABLE_QUOTE": "A returned quote did not match its cited source.",
    "UNSUPPORTED_CONCLUSION": "Support verification did not uphold the conclusion.",
    "PROCESSING_ERROR": "The system failed to produce a result. Not a clinical finding.",
}

st.set_page_config(page_title=APP_NAME, layout="wide",
                   initial_sidebar_state="expanded")

# Rows are styled by container key rather than wrapped in raw HTML, so their
# contents stay real Streamlit widgets and the expanders, text areas and
# buttons inside them keep working. The per-status edge is emitted per row in
# the loop below, because the colour is not known until the row is.
st.markdown(f"""<style>
  /* Base scale. The reference was authored for a narrow container; in a full
     browser window the same numbers read small. Nothing below 12px. */
  section[data-testid='stMain'] {{ font-size:16px; }}
  section[data-testid='stMain'] p,
  section[data-testid='stMain'] li {{ font-size:16px; line-height:1.6; }}
  section[data-testid='stMain'] [data-testid='stCaptionContainer'] p
      {{ font-size:12px; }}
  /* ---- Streamlit chrome -------------------------------------------
     The Deploy button and the three-dot menu are development
     affordances. `client.toolbarMode = "minimal"` in config.toml removes
     most of them; it still renders the toolbar container, which leaves an
     empty strip across the top, so the container is collapsed here too.

     The header is *not* removed outright. `stExpandSidebarButton` lives
     inside it, and a viewer who collapses the sidebar with no way to
     reopen it is stuck. The header keeps zero height with visible
     overflow, so that button still renders while the strip does not. */
  [data-testid='stToolbar'], [data-testid='stAppDeployButton'],
  [data-testid='stMainMenu'], [data-testid='stStatusWidget'],
  [data-testid='stDecoration'], footer {{ display:none !important; }}
  [data-testid='stHeader'] {{ height:0 !important; min-height:0 !important;
      background:transparent !important; overflow:visible !important; }}
  [data-testid='stExpandSidebarButton'] {{ display:flex !important; }}

  /* With the header collapsed, this padding is the only thing between the
     first line of text and the top of the viewport. It was 2.2rem while
     the header still reserved its own space, which is why the opening
     line of live mode rendered underneath it and was cut off. */
  section[data-testid='stMain'] .block-container {{ padding-top:1.15rem; }}
  /* The stylesheet is injected through `st.markdown`, so Streamlit wraps it
     in an element container that contributes its own height and a flex gap
     before the first visible element. That was the remaining whitespace
     above the masthead: the padding was already small, but an invisible
     element sat in front of it. */
  [data-testid='stElementContainer']:has(> [data-testid='stMarkdown'] style),
  [data-testid='stElementContainer']:has(> div > [data-testid='stMarkdown'] style)
      {{ display:none !important; }}

  /* Every value carries a label. The reviewer should never have to infer
     what she is looking at, so this class appears above each one. */
  .cite-label {{ font-size:12px; text-transform:uppercase; color:{INK_FAINT}; letter-spacing:.04em;
      margin-bottom:2px; }}

  /* Header: one line. Name, tagline, mode pill. */
  .cite-bar {{ display:flex; justify-content:space-between;
      align-items:center; gap:20px; background:{PANEL};
      border:1px solid {RULE}; border-radius:3px 3px 0 0;
      padding:13px 18px; }}
  .cite-brand {{ display:flex; align-items:baseline; gap:11px;
      flex-wrap:wrap; }}
  .cite-brand-name {{ font-size:22px; font-weight:600; color:{NAVY};
      letter-spacing:-.01em; }}
  .cite-brand-tag {{ font-size:14px; color:{INK_FAINT}; }}
  .cite-pill {{ background:{NAVY}; color:#fff; font-size:13px;
      padding:4px 13px; border-radius:3px; white-space:nowrap; }}

  /* Case band: three labelled fields, then the standing summary. */
  .cite-band {{ background:{PANEL}; border:1px solid {RULE};
      border-top:none; padding:17px 18px; }}
  .cite-fields {{ display:flex; gap:44px; flex-wrap:wrap;
      margin-bottom:16px; }}
  .cite-value {{ font-size:19px; font-weight:500; line-height:1.3;
      color:{INK}; }}
  .cite-value.strong {{ font-weight:600; }}
  .cite-standing {{ border-top:1px solid {RULE}; padding-top:13px; }}
  .cite-tallies {{ display:flex; gap:9px; flex-wrap:wrap; }}
  .cite-tally {{ flex:1; min-width:170px; padding:9px 12px;
      border-left:3px solid; }}
  .cite-tally .n {{ font-size:22px; font-weight:600; line-height:1.2; }}
  .cite-tally .k {{ font-size:13px; }}

  /* Notice strip: the constraint notice and the way into run details. */
  .cite-strip {{ display:flex; justify-content:space-between; gap:20px;
      flex-wrap:wrap; background:{PAPER}; border:1px solid {RULE};
      border-top:none; border-radius:0 0 3px 3px; padding:11px 22px;
      font-size:13px; color:{INK_FAINT}; }}

  /* Alert: shown only when documents failed to parse. */
  .cite-alert {{ margin:15px 0 0; padding:9px 13px; background:#FBF1DE;
      border-left:3px solid #8A5B0C; font-size:13.5px; color:#8A5B0C; }}

  /* Rows. */
  div[class*='st-key-row_'] {{
      background:{PANEL}; border:1px solid {RULE}; border-left:3px solid {RULE};
      border-radius:3px; padding:14px 17px; margin-bottom:10px;
  }}
  .cite-head {{ display:flex; justify-content:space-between; gap:22px;
      align-items:flex-start; margin-bottom:11px; }}
  .cite-req {{ font-size:17px; font-weight:500; line-height:1.4;
      margin-top:2px; color:{INK}; }}
  .cite-result {{ text-align:right; flex:none; }}
  .cite-chip {{ display:inline-block; font-size:13px; font-weight:500;
      padding:4px 12px; border-radius:3px; white-space:nowrap; }}
  .cite-why {{ font-size:15px; line-height:1.5; margin-bottom:12px; }}
  .cite-quote {{ padding:2px 0 2px 15px; border-left:3px solid {RULE};
      font-size:16.5px; line-height:1.6; color:{INK}; }}
  .cite-source {{ margin-top:7px; font-size:13px; color:{INK_FAINT}; }}
  .cite-source b {{ color:{INK_SOFT}; font-weight:500; }}

  /* ---- passage cards ----------------------------------------------
     Each cited passage is a card: the document as a heading, the excerpt
     in proportional type with its surroundings dimmed, and the machine
     detail in a footer. This replaced a monospace block with a header line
     that crammed the document name, filename, id, character range and hash
     into one string — a log dump, not a clinical record. No monospace on
     clinical prose. */
  .cite-passages {{ margin-top:16px; border-top:1px solid {RULE_SOFT};
      padding-top:16px; }}
  .cite-doc {{ border:1px solid {RULE}; border-radius:5px; overflow:hidden;
      margin-bottom:14px; }}
  .cite-doc-head {{ display:flex; justify-content:space-between;
      align-items:baseline; gap:16px; padding:11px 17px; background:#F6F5F2;
      border-bottom:1px solid {RULE}; }}
  .cite-doc-name {{ font-size:15px; font-weight:600; color:{INK}; }}
  .cite-doc-date {{ font-size:13px; color:{INK_FAINT}; white-space:nowrap; }}
  .cite-excerpt {{ padding:16px 19px; font-size:15.5px; line-height:1.75;
      color:{INK_FAINT}; white-space:pre-wrap; }}
  .cite-excerpt mark {{ background:{MARK}; color:{INK}; font-weight:500;
      padding:1px 2px; border-radius:2px; }}
  .cite-ell {{ color:#C2C5C8; }}
  .cite-doc-foot {{ display:flex; justify-content:space-between;
      align-items:center; gap:16px; padding:9px 17px;
      border-top:1px solid {RULE_SOFT}; background:#FCFCFA; font-size:12.5px;
      color:{INK_FAINT}; }}
  .cite-ok {{ color:{DISPLAY["MET"][1]}; }}
  .cite-bad {{ color:{DISPLAY["NOT_MET"][1]}; }}
  .cite-doc-foot details {{ display:inline; }}
  .cite-doc-foot summary {{ display:inline; cursor:pointer; color:{NAVY};
      font-size:12.5px; list-style:none; }}
  .cite-doc-foot summary::-webkit-details-marker {{ display:none; }}
  .cite-prov {{ margin-top:7px; font-size:12px; color:{INK_FAINT};
      word-break:break-all; }}

  .cite-quiet {{ font-size:13px; color:{INK_FAINT}; line-height:1.55;
      max-width:88ch; }}
  .cite-quiet b {{ color:{INK_SOFT}; font-weight:600; }}
  .cite-footer {{ border-top:1px solid {RULE}; margin-top:40px;
      padding-top:18px; font-size:13px; color:{INK_FAINT}; line-height:1.55;
      max-width:88ch; }}
  .cite-footer b {{ color:{INK_SOFT}; font-weight:600; }}
  .cite-demo {{ font-size:13px; font-weight:600; color:{INK_SOFT}; }}

  /* The row expander is a quiet inline affordance, not a panel. */
  div[class*='st-key-row_'] details {{ border:none !important;
      background:transparent !important; }}
  div[class*='st-key-row_'] summary {{ font-size:14px; color:{NAVY};
      padding-left:0 !important; }}
  div[class*='st-key-row_'] summary p {{ font-size:14px !important; }}
</style>""", unsafe_allow_html=True)


# ---------------------------------------------------------------------------

def saved_runs() -> dict[str, list[Path]]:
    """Recorded runs that carry per-case verification results, by case."""
    out: dict[str, list[Path]] = {}
    for path in sorted(RUNS.glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for case in data.get("cases", []):
            if case.get("verification"):
                out.setdefault(case["case_id"], []).append(path)
    return out


def load_case(path: Path, case_id: str) -> tuple[dict, dict]:
    data = json.loads(path.read_text())
    case = next(c for c in data["cases"] if c["case_id"] == case_id)
    return data, case


def status_chip(status: str | None) -> str:
    """The display wording, on its own.

    The raw enum used to sit beside it. Spec Section 4 supplies the wording
    precisely so `MET` does not have to be on screen, and printing both said
    the same thing twice in two vocabularies — one of which reads as a
    verdict. The enum stays in the artifact, where it belongs.
    """
    label, fg, bg, _ = DISPLAY.get(status, DISPLAY[None])
    return (f"<div class='cite-chip' style='background:{bg};color:{fg}'>"
            f"{label}</div>")


def summary_strip(results: list[dict]) -> str:
    """Counts by status, under a label that says what is being counted.

    The wording is Spec Section 4's, in full, the same as the chips on the
    rows. Short forms were used here while the cards were narrow, which left
    the summary and the rows describing the same status in two vocabularies —
    a reviewer had to work out that "Needs review" and "Potential mismatch
    requiring review" were one thing.

    There is deliberately no total and no aggregate: one number over a case
    is the score this system does not produce.
    """
    order = ["MET", "AMBIGUOUS", "NOT_MET", "NOT_APPLICABLE", None]
    counts = {k: 0 for k in order}
    for r in results:
        key = r["clinical_status"] if r["clinical_status"] in counts else None
        counts[key] += 1
    cells = []
    for key in order:
        if not counts[key]:
            continue
        label, fg, bg, edge = DISPLAY[key]
        cells.append(
            f"<div class='cite-tally' style='background:{bg};"
            f"border-left-color:{edge}'>"
            f"<div class='n' style='color:{fg}'>{counts[key]}</div>"
            f"<div class='k' style='color:{fg}'>{label}</div></div>")
    n = len(results)
    return (f"<div class='cite-standing'>"
            f"<div class='cite-label'>Where the {n} requirement"
            f"{'s' if n != 1 else ''} stand</div>"
            f"<div class='cite-tallies'>{''.join(cells)}</div></div>")


def processing_sentence(result: dict) -> str:
    """What a reviewer is told when a requirement produced no result.

    The row used to print the pipeline's own `detail` string, which is
    written for whoever is debugging the run:

        1 attempt(s) failed; last: response truncated at the 16000
        output-token limit (stop_reason max_tokens); raise max_tokens
        rather than retrying

    An attempt count, a token limit, a stop reason and a remediation
    instruction. A reviewer acts on none of it, and the sentence that
    followed ran into it with no separator. The raw string is still written
    to the artifact and shown under run details, where someone diagnosing
    the run will look for it.
    """
    kind = result.get("failure_kind") or ""
    detail = (result.get("detail") or "").lower()
    if kind == "NOT_ATTEMPTED":
        # Already says everything; appending "not assessed" repeats itself.
        return ("The record could not be read, so this requirement was "
                "never assessed.")
    if kind == "CONTRACT_REJECTION":
        cause = ("The model's result failed an internal consistency check "
                 "and was not used.")
    if "truncated" in detail:
        cause = ("The model's response was cut off before it produced a "
                 "result.")
    else:
        cause = "The model did not return a usable result."
    return f"{cause} This requirement was not assessed."


def unreadable_notice(total: int, usable: int) -> str:
    """An alert when part of the packet could not be read, otherwise nothing.

    A count of readable documents buried in a metadata line is not a warning.
    If some of the packet could not be read then the review is incomplete,
    and that is a statement about the review rather than a number about the
    run, so it is said in those words and only when it is true.

    No case in the corpus currently has an unreadable document, so this is
    reached only under a packet that fails ingestion. That is exactly why it
    is a function: `tests/test_interface.py` exercises both branches rather
    than leaving the alert as code nothing has ever run.
    """
    missing = total - usable
    if missing <= 0:
        return ""
    return (f"<div class='cite-alert'>{missing} of {total} submitted "
            f"document{'s' if missing != 1 else ''} could not be read. "
            f"This case is not a complete evidence review.</div>")


def field(label: str, value: str, strong: bool = False) -> str:
    """One labelled value. Nothing on this screen appears without a label."""
    return (f"<div><div class='cite-label'>{label}</div>"
            f"<div class='cite-value{' strong' if strong else ''}'>{value}"
            f"</div></div>")


def header_bar(mode_label: str, live: bool = False) -> str:
    """Name, tagline and mode, on one line.

    The mode was a full-width bar of its own. It is now a pill in the header:
    still the only saturated block of colour above the content, and still
    impossible to read a recorded run as a live one, without spending a band
    of vertical space on it.
    """
    colour = DISPLAY["MET"][3] if live else NAVY
    return (f"<div class='cite-bar'><div class='cite-brand'>"
            f"<span class='cite-brand-name'>{APP_NAME}</span>"
            f"<span class='cite-brand-tag'>{APP_SUBTITLE}</span></div>"
            f"<span class='cite-pill' style='background:{colour}'>"
            f"{mode_label}</span></div>")


# ---------------------------------------------------------------------------

# The constraint notice, defined here and rendered in three places below:
# the strip under the case band, the run-details expander, and a footer on
# every screen. Spec Section 10 requires it on screen; it does not require it
# to occupy the top of the column, and as the loudest element it was also the
# easiest to stop seeing.
FULL_NOTICE = (
    "<b>Synthetic demonstration.</b> All criteria are synthetic demonstration "
    "criteria modelled on published coverage determination patterns; they are "
    "<b>not Humana coverage policies</b>. All clinical records are synthetic — "
    "no real or de-identified patient data is used. This system produces no "
    "coverage determination, recommendation, or score. A licensed clinician "
    "reviews the evidence and makes any decision.")

def notice_footer() -> None:
    """The constraint notice, rendered wherever the page ends early.

    `st.stop()` ends the script, so a path that stops has to have put the
    notice on screen already. Three paths stop: no recorded runs found, no
    API key in live mode, and live mode before a run. All three used to exit
    with no notice anywhere on the page.
    """
    st.markdown(f"<div class='cite-footer'>{FULL_NOTICE}</div>",
                unsafe_allow_html=True)


# The header, case band and strip render after the mode branch below, because
# they report the mode and the case's standing and cannot be drawn before
# those are known.

available = saved_runs()
if not available:
    st.error("No recorded runs found in `runs/`. Run `scripts/run_eval.py` first.")
    notice_footer()
    st.stop()

with st.sidebar:
    # No wordmark here. It is the masthead's job, and having both meant the
    # name and tagline appeared twice on every screen.
    st.subheader("Mode")
    # Recorded is the default. A live run costs money, takes half a minute and
    # can fail in front of an audience; none of that should happen because
    # someone opened the page.
    mode = st.radio(
        "Mode", ["Recorded run", "Live run"], index=0, key="mode",
        label_visibility="collapsed",
        captions=["Reads a saved artifact. No API key needed.",
                  "Executes Steps 1–5 now. Needs a key. Costs money."])
    live_mode = mode == "Live run"

    st.subheader("Case")
    if live_mode:
        # Any case in the corpus can be run live, not only those that happen
        # to appear in a recorded artifact.
        all_cases = sorted(
            c["case_id"] for c in
            json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())["cases"])
        case_id = st.selectbox("Case", all_cases,
                               label_visibility="collapsed")
        run_path = None
    else:
        case_id = st.selectbox("Case", sorted(available),
                               label_visibility="collapsed")
        run_paths = available[case_id]
        labels = {p.name: p for p in run_paths}
        chosen = st.selectbox("Recorded run", list(labels), index=0)
        run_path = labels[chosen]

    # Secondary by placement as well as by label. Mode and case are the
    # working controls; this is a demonstration aid and is separated from
    # them so it does not read as part of the review workflow.
    st.markdown(
        f"<div style='margin-top:22px;padding-top:14px;border-top:1px solid "
        f"{RULE}'><div class='cite-demo'>Show a failure</div>"
        f"<div class='cite-quiet' style='margin:3px 0 8px'>These deliberately "
        f"break the system so you can see how failures are handled. They are "
        f"<b>not an observed error rate.</b></div></div>",
        unsafe_allow_html=True)
    fault = st.radio(
        "Inject",
        [Fault.NONE, Fault.UNVERIFIABLE_QUOTE, Fault.OUTPUT_TRUNCATION],
        label_visibility="collapsed",
        format_func=lambda f: {
            Fault.NONE: "Nothing broken",
            Fault.UNVERIFIABLE_QUOTE: "Quote that cannot be verified",
            Fault.OUTPUT_TRUNCATION: "Model response cut off",
        }[f],
        key="fault")

criteria_set = load_criteria(
    next(c["procedure_id"] for c in
         json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())["cases"]
         if c["case_id"] == case_id))
packet = ingest_case(case_id, CASES)


MODE_LABEL = {
    "recorded": "Recorded run",
    "live": "Live run · in progress",
    "live-done": "Live run",
}


MODE_LABEL = {
    "recorded": "Recorded run",
    "live": "Live run · in progress",
    "live-done": "Live run",
}


def mode_banner(kind: str, detail: str, progress=None) -> None:
    """Progress during a live run, under the header that is already drawn.

    This used to draw the header too, which meant the header's existence
    depended on reaching this call. It does not any more: the header is
    unconditional and this reports only how far the run has got.
    """
    if progress is not None:
        done, total = progress
        detail = f"{done} of {total} requirements complete"
    if detail:
        st.markdown(f"<div class='cite-strip'>{detail}</div>",
                    unsafe_allow_html=True)


def stage_row(criterion_id: str, stage: str, result=None) -> str:
    """One line of the processing display.

    Rows that have not finished are dimmed. This is the only place in the
    interface where a row is genuinely mid-flight: the evidence map below
    renders from a completed verification payload, which carries no stage
    field, so a "still running" branch down there would be unreachable code
    pretending to be a feature.
    """
    text, colour = STAGE_TEXT.get(stage, (stage, "#888"))
    mark = {STAGE_DONE: "●", STAGE_FAILED: "●"}.get(stage, "○")
    dim = "" if stage in (STAGE_DONE, STAGE_FAILED) else "opacity:.55;"
    note = ""
    if result is not None:
        rejected = len(getattr(result, "rejected_evidence", []) or [])
        if rejected:
            # Visible at the moment Step 4 rejects it, not only at the end.
            note = (f" <span style='color:#9A3E1E;font-weight:600'>"
                    f"· {rejected} quote(s) failed verification</span>")
    return (f"<div style='font-family:ui-monospace,monospace;font-size:13.5px;"
            f"padding:3px 0;{dim}'><span style='color:{colour}'>{mark}</span> "
            f"<b>{criterion_id}</b> <span style='color:{colour}'>{text}</span>"
            f"{note}</div>")


# The header renders here, before anything can exit early. It used to be
# drawn after the mode branch, so live mode before a run — the first state a
# viewer sees after switching — showed no application name and no mode at
# all. Nothing below this line can produce a page without a header.
st.markdown(header_bar("Live run" if live_mode else "Recorded run",
                       live=live_mode), unsafe_allow_html=True)

live_payload = st.session_state.get("live_payload")

if live_mode:
    st.caption(
        "A live run makes **one extraction call for all criteria** — this is "
        "Baseline A, the configuration the held-out comparison retained — then "
        "**one support-verification call per criterion**, with a deterministic "
        "quote check in between. Rows therefore resolve together at extraction "
        "and one at a time through verification. That shared wait is what "
        "distinguishes Baseline A from the per-criterion configuration.")
    n = len(criteria_set.criterion_ids)
    go = st.button(f"Run {case_id} live · {1 + n} model calls",
                   type="primary")

    if go:
        import os
        try:
            from dotenv import load_dotenv
            load_dotenv(PROJECT_ROOT / ".env")
        except ImportError:
            pass
        if not os.environ.get("ANTHROPIC_API_KEY"):
            st.error(
                "**No API key.** `ANTHROPIC_API_KEY` is not set, so no live "
                "run was attempted. Recorded mode needs no key.",
                icon=":material/key_off:")
            notice_footer()
            st.stop()

        # The bar owns a placeholder so it can carry progress while the run
        # is going. It stays the most prominent element on the page
        # throughout, which is the point: nobody should be able to glance at
        # a screen mid-run and not know it is live.
        banner = st.empty()
        board = st.container(border=True)
        with board:
            st.markdown(
                f"<div class='cite-label' style='margin-bottom:7px'>"
                f"Processing</div>", unsafe_allow_html=True)
            slots = {cid: st.empty() for cid in criteria_set.criterion_ids}
        state = {cid: (STAGE_PENDING, None) for cid in criteria_set.criterion_ids}

        def draw():
            done = sum(1 for s, _ in state.values() if s == STAGE_DONE)
            with banner.container():
                mode_banner("live", "", progress=(done, len(state)))
            for cid, slot in slots.items():
                slot.markdown(stage_row(cid, *state[cid]),
                              unsafe_allow_html=True)

        draw()  # every row visible before any work begins

        def on_progress(criterion_ids, stage, result=None):
            for cid in criterion_ids:
                if cid in state:
                    state[cid] = (stage, result)
            draw()

        from um_evidence import AnthropicClient
        live_payload = run_live(case_id, criteria_set, packet,
                                AnthropicClient(), on_progress=on_progress)
        st.session_state["live_payload"] = live_payload

    if not live_payload:
        # No prompt here. The button above already reads "Run LF-201 live ·
        # 10 model calls", which says both what will happen and what it
        # costs; a banner repeating it is one more thing to read past.
        notice_footer()
        st.stop()

    case = live_payload["cases"][0]
    if case["case_id"] != case_id:
        st.warning(
            f"Showing the last live run, which was **{case['case_id']}**, not "
            f"the selected case. Press the button to run {case_id}.",
            icon=":material/warning:")
    data = live_payload
    extraction = case["extraction"]
    verification = case["verification"]
    run_path = Path(live_payload.get("artifact", "live"))
    run_note = (f"Executed {live_payload.get('generated')}. Artifact "
                f"{run_path.name}, written to runs/live/, outside the "
                f"evaluation path.")
else:
    data, case = load_case(run_path, case_id)
    extraction = case["extraction"]
    verification = case["verification"]
    run_note = (f"Artifact {run_path.name}, generated "
                f"{data.get('generated', 'unknown')}. Citations resolve "
                f"against the packet as it stood then. Nothing is being "
                f"executed.")

# --- fault injection, applied before rendering and always announced -------
injection = None
if fault is Fault.UNVERIFIABLE_QUOTE:
    mutated, injection = corrupt_first_quote(verification["results"], packet)
    # Re-run the real Step 4 over the corrupted input. The rejection, the
    # preserved reason and any downgrade come from verify.py, not from here.
    from um_evidence import verify_quotes
    from um_evidence.extract import CriterionExtraction, ExtractedEvidence
    from um_evidence.results import ClinicalStatus, ProcessingStatus, ReasonCode
    rebuilt = []
    for r in mutated:
        status = (ClinicalStatus(r["clinical_status"])
                  if r["clinical_status"] else None)
        checked = verify_quotes(CriterionExtraction(
            criterion_id=r["criterion_id"], clinical_status=status,
            processing_status=ProcessingStatus.COMPLETE,
            reason_codes=[ReasonCode(c) for c in r.get("reason_codes", [])],
            evidence=[ExtractedEvidence(e["document_id"], e["quote"], e["role"])
                      for e in r.get("evidence", [])],
            explanation=r.get("explanation", "")), packet)
        rebuilt.append(checked.as_dict())
    verification = {**verification, "results": rebuilt}

elif fault is Fault.OUTPUT_TRUNCATION:
    replayed, injection = replay_truncation(
        [r["criterion_id"] for r in verification["results"]])
    verification = {**verification,
                    "results": [{**r.as_dict(), "verification": {
                        "quote_check": {"returned": 0, "verified": 0,
                                        "rejected": 0},
                        "support_check": {"ran": False, "outcome": "SKIPPED",
                                          "detail": ""}},
                        "extracted_status": None, "downgraded": False,
                        "downgrade_reason": ""} for r in replayed]}
    extraction = {**extraction, "processing_status": "FAILED"}

if injection is not None:
    # Two lines. What broke and what it did, then the standing caveat.
    # The enum, the artifact the truncation was replayed from, the date it
    # was observed and the case it came from were all here; none of them is
    # something a reviewer acts on, and they now sit in run details.
    st.error(f"**{injection.headline}.** {injection.detail}\n\n"
             f"{NOT_A_RATE}", icon=":material/science:")

# criteria_set and packet are loaded above, before the mode branch, because a
# live run needs both to draw its row list before any call is made.

# --- case band: three labelled fields, then where the case stands ---------
# Every value carries a label. A reviewer should not have to infer that
# "LF-201" is the case and "9" is a count of requirements. CPT and the
# criteria set version are off the surface: they are provenance, and beside
# the case name they turned it into one undifferentiated grey string.
n_req = len(criteria_set.criterion_ids)
st.markdown(
    "<div class='cite-band'><div class='cite-fields'>"
    + field("Case", case_id, strong=True)
    + field("Requested procedure", criteria_set.procedure_name)
    + field("Reviewing against",
            f"{n_req} policy requirement{'s' if n_req != 1 else ''}")
    + "</div>"
    + summary_strip(verification["results"])
    + "</div>", unsafe_allow_html=True)

# --- strip: the notice, and the way into run details ----------------------
st.markdown(
    f"<div class='cite-strip'><span>Synthetic demonstration · this system "
    f"produces no coverage determination</span></div>",
    unsafe_allow_html=True)

with st.expander("run details"):
    st.markdown(
        f"<div class='cite-quiet'>{run_note}</div>"
        f"<div class='cite-quiet' style='margin-top:8px'>"
        f"criteria set <code>{criteria_set.version}</code> · CPT "
        f"<code>{criteria_set.cpt}</code> · configuration "
        f"<code>{extraction.get('configuration', '?')}</code> · "
        f"{len(packet.usable)} of {len(packet.documents)} documents read"
        f"<br>model <code>{extraction.get('model')}</code> · prompt "
        f"<code>{extraction.get('prompt_version')}</code> · settings "
        f"<code>{extraction.get('settings_version', 'unversioned')}</code> · "
        f"parser <code>{extraction.get('parser_version', 'unversioned')}</code>"
        f" · packet processing <code>{extraction.get('processing_status')}"
        f"</code>"
        + (f" · split <code>{data['score']['split']}</code>"
           if data.get("score", {}).get("split") else "")
        + f"<br>procedure id <code>{criteria_set.procedure_id}</code>"
        + f"</div>"
        # The pipeline's own failure strings: attempt counts, token limits,
        # stop reasons, remediation notes. Off the rows, kept here for
        # whoever is diagnosing the run rather than reviewing the case.
        + ("".join(
            f"<div class='cite-quiet' style='margin-top:8px'>"
            f"<b>{r['criterion_id']}</b> {r.get('failure_kind') or ''} · "
            f"<code>{r.get('detail')}</code></div>"
            for r in verification["results"]
            if r.get("processing_status") != "COMPLETE" and r.get("detail")))
        + (f"<div class='cite-quiet' style='margin-top:8px'>"
           f"{injection.provenance or injection.detail} "
           f"Target: {injection.target}.</div>"
           if injection is not None else "")
        + f"<div class='cite-quiet' style='margin-top:12px'>{FULL_NOTICE}</div>",
        unsafe_allow_html=True)

# --- alert: only when documents failed to parse ---------------------------
notice = unreadable_notice(len(packet.documents), len(packet.usable))
if notice:
    st.markdown(notice, unsafe_allow_html=True)

existing = corrections.for_run(run_path.name)

def preview(text: str, width: int = 78) -> str:
    """A collapsed row has to be readable without opening it.

    A label reading "contradicting, doc_7aa97b3c60db, verified" tells a
    reviewer nothing and makes her open every row to find the one she wants.
    """
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[:width].rstrip() + "…"


def filename_for(document_id: str) -> str:
    """A readable document name. The raw filename and id stay in the detail.

    A document id is the last resort: it means the cited document is not in
    this packet, which is itself the finding worth showing.
    """
    try:
        return document_label(packet.by_id(document_id).filename)
    except KeyError:
        return document_id


# The standing summary is part of the case band above, not a second strip.
for index, result in enumerate(verification["results"]):
    criterion_id = result["criterion_id"]
    criterion = criteria_set[criterion_id]
    clinical = result["clinical_status"]
    processing = result["processing_status"]
    edge = DISPLAY.get(clinical, DISPLAY[None])[3]

    # The evidence map always renders a finished payload, so there is no
    # "still running" state here. Progress during a live run is the board
    # above, drawn by `stage_row`.
    key = f"row_{criterion_id}"
    st.markdown(f"<style>.st-key-{key}{{border-left-color:{edge} "
                f"!important}}</style>", unsafe_allow_html=True)

    with st.container(border=False, key=key):
        # --- head: requirement left, result right, both labelled ----------
        # "Requirement 3 of 9" tells a reviewer where she is in the list
        # without counting rows.
        position = index + 1
        total = len(verification["results"])
        st.markdown(
            f"<div class='cite-head'>"
            f"<div><div class='cite-label'>Requirement {position} of "
            f"{total}</div>"
            f"<div class='cite-req'>{criterion.text}</div></div>"
            f"<div class='cite-result'><div class='cite-label'>Result</div>"
            f"{status_chip(clinical)}</div></div>",
            unsafe_allow_html=True)

        # --- why, under a label naming what kind of problem this is -------
        # The heading differs by state. "Why this needs review" and "Why this
        # is unresolved" are different questions, and a processing failure is
        # not a clinical question at all.
        fg = DISPLAY.get(clinical, DISPLAY[None])[1]
        if processing != "COMPLETE":
            st.markdown(
                f"<div class='cite-label'>What happened</div>"
                f"<div class='cite-why' style='color:{DISPLAY[None][1]}'>"
                f"{processing_sentence(result)}</div>",
                unsafe_allow_html=True)
        elif result["reason_codes"] and clinical != "MET":
            heading = ("Why this needs review" if clinical == "NOT_MET"
                       else "Why this is unresolved")
            codes = " ".join(reason_label(c) for c in result["reason_codes"])
            if result.get("downgraded"):
                codes += (f" Downgraded from {result.get('extracted_status')} "
                          f"during verification.")
            st.markdown(
                f"<div class='cite-label'>{heading}</div>"
                f"<div class='cite-why' style='color:{fg}'>{codes}</div>",
                unsafe_allow_html=True)

        # --- the located evidence, labelled as such -----------------------
        evidence = result["evidence"]
        if evidence:
            by_role: dict[str, list[dict]] = {}
            for item in evidence:
                by_role.setdefault(item["role"], []).append(item)
            lead = evidence[0]
            more = len(evidence) - 1
            unverified = sum(1 for e in evidence if not e["verified"])
            # "all verified against source" says what the check actually did:
            # each quote resolved to one span in the document it named.
            state = ("all verified against source" if not unverified
                     else f"<span style='color:{DISPLAY['NOT_MET'][1]}'>"
                          f"{unverified} could not be verified against "
                          f"source</span>")
            further = ("" if not more else
                       f" · {more} further passage"
                       f"{'s' if more > 1 else ''} located")
            st.markdown(
                f"<div class='cite-label'>Evidence located in the record"
                f"</div>"
                f"<div class='cite-quote'>“{preview(lead['quote'], 170)}”"
                f"</div>"
                f"<div class='cite-source'>Source: "
                f"{filename_for(lead['document_id'])}{further} · {state}"
                f"</div>", unsafe_allow_html=True)

        # --- everything else behind one expander --------------------------
        if evidence:
            n = len(evidence)
            with st.expander(f"View all {n} passage{'s' if n > 1 else ''}"):
                st.markdown(
                    f"<div class='cite-label'>All {n} passage"
                    f"{'s' if n > 1 else ''}, shown in their source context"
                    f"</div>", unsafe_allow_html=True)

                # Where several passages come from one document, number them
                # against that document. Four cards all headed "Flexion
                # extension series" tell a reviewer nothing about which is
                # which.
                per_doc: dict[str, int] = {}
                for e in evidence:
                    per_doc[e["document_id"]] = per_doc.get(e["document_id"], 0) + 1
                seen: dict[str, int] = {}

                for role in ("supporting", "contradicting"):
                    items = by_role.get(role, [])
                    if not items:
                        continue
                    # Grouping matters once a requirement carries several
                    # passages per side: five contradicting quotes in a flat
                    # list is a wall.
                    if len(by_role) > 1:
                        st.markdown(
                            f"<div class='cite-label' "
                            f"style='margin:14px 0 6px'>"
                            f"{role} · {len(items)}</div>",
                            unsafe_allow_html=True)
                    for item in items:
                        doc_id = item["document_id"]
                        try:
                            doc = packet.by_id(doc_id)
                        except KeyError:
                            st.markdown(
                                f"<div class='cite-doc'><div class='cite-doc-"
                                f"foot'><span class='cite-bad'>The cited "
                                f"document is not in this packet.</span>"
                                f"<span>{doc_id}</span></div></div>",
                                unsafe_allow_html=True)
                            continue

                        name, when = document_parts(doc.filename)
                        seen[doc_id] = seen.get(doc_id, 0) + 1
                        if per_doc[doc_id] > 1:
                            when = (f"{when} · " if when else "") + (
                                f"passage {seen[doc_id]} of {per_doc[doc_id]} "
                                f"from this document")

                        if not item["verified"]:
                            # An unverifiable quote has no span to show in
                            # context, because it resolved to no place in the
                            # source. The card says that rather than showing
                            # an excerpt that would imply it did.
                            st.markdown(
                                f"<div class='cite-doc'>"
                                f"<div class='cite-doc-head'>"
                                f"<span class='cite-doc-name'>{name}</span>"
                                f"<span class='cite-doc-date'>{when}</span>"
                                f"</div>"
                                f"<div class='cite-excerpt'>“{item['quote']}”"
                                f"</div>"
                                f"<div class='cite-doc-foot'>"
                                f"<span>No matching span in this document"
                                f"</span><span class='cite-bad'>"
                                f"could not be verified against source</span>"
                                f"</div></div>", unsafe_allow_html=True)
                            continue

                        span = item.get("span") or {}
                        start, end = span.get("start", 0), span.get("end", 0)
                        pad = 420
                        before = doc.canonical[max(0, start - pad):start]
                        cited = doc.canonical[start:end]
                        after = doc.canonical[end:end + pad]
                        sha = span.get("content_sha256", "")

                        # File, id and hash sit behind a disclosure in the
                        # footer. Native HTML, so it nests inside the card;
                        # a Streamlit widget cannot.
                        st.markdown(
                            f"<div class='cite-doc'>"
                            f"<div class='cite-doc-head'>"
                            f"<span class='cite-doc-name'>{name}</span>"
                            f"<span class='cite-doc-date'>{when}</span></div>"
                            f"<div class='cite-excerpt'>"
                            f"<span class='cite-ell'>…</span>{before}"
                            f"<mark>{cited}</mark>{after}"
                            f"<span class='cite-ell'>…</span></div>"
                            f"<div class='cite-doc-foot'>"
                            f"<span>Characters {start} to {end}</span>"
                            f"<span><span class='cite-ok'>✓ verified against "
                            f"source</span> · <details><summary>file and hash"
                            f"</summary><div class='cite-prov'>"
                            f"{doc.filename}<br>{doc_id}<br>sha256 {sha}"
                            f"</div></details></span>"
                            f"</div></div>", unsafe_allow_html=True)

                if result["explanation"]:
                    st.markdown(
                        f"<div class='cite-label' "
                        f"style='margin:16px 0 5px'>Explanation</div>", unsafe_allow_html=True)
                    st.markdown(result["explanation"])
                    st.caption(f"Satisfied by: {criterion.satisfied_by}")

        elif result["explanation"]:
            # No passages to hang the expander on, so the explanation keeps
            # its own. A requirement with nothing located is exactly where a
            # reviewer wants to know what the system was looking for.
            with st.expander("explanation"):
                st.markdown(result["explanation"])
                st.caption(f"Satisfied by: {criterion.satisfied_by}")

        # --- reviewer correction ------------------------------------------
        prior = existing.get((case_id, criterion_id), [])
        for c in prior:
            st.markdown(
                f":small[:blue[Reviewer note · {c.recorded_at} · "
                f"**{DISAGREEMENT_LABEL.get(c.kind, humanise(c.kind))}**] "
                f"— {c.reason}]")

        with st.expander("record a disagreement"):
            st.caption(
                "Stored separately from the system's output and from the "
                "reference labels. Nothing here overwrites either, and the "
                "evaluation cannot read it.")
            kind = st.selectbox(
                "What is wrong", corrections.DISAGREEMENT_KINDS,
                format_func=lambda k: DISAGREEMENT_LABEL.get(k, humanise(k)),
                key=f"k{criterion_id}")
            reason = st.text_area("Why", key=f"r{criterion_id}",
                                  placeholder="What a colleague would need to "
                                              "understand the disagreement.")
            who = st.text_input("Reviewer", key=f"w{criterion_id}")
            if st.button("Record", key=f"b{criterion_id}"):
                try:
                    corrections.record(run_path.name, case_id, criterion_id,
                                       kind, reason, who, result)
                    st.success("Recorded.")
                    st.rerun()
                except ValueError as exc:
                    st.error(str(exc))

# --- footer: the constraint notice, on every screen, unconditionally ------
# Not behind the expander alone. An expander can be left closed, and Spec
# Section 10 requires the notice on screen rather than available on request.
totals = corrections.summary()
st.markdown(
    f"<div class='cite-footer'>{FULL_NOTICE}<br><br>"
    f"Correction store: {totals['total']} recorded across "
    f"{len(totals['cases'])} case(s). Written to <code>corrections/</code>, "
    f"append only, never read by the scorer.</div>",
    unsafe_allow_html=True)
