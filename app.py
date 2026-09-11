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
from um_evidence.faults import Fault, corrupt_first_quote, replay_truncation
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

PAPER = "#FBFAF8"
PANEL = "#FFFFFF"
RULE = "#E4E1DB"
INK = "#1A1A18"          # primary text: requirements and quotes
INK_SOFT = "#5E5C57"     # secondary
INK_FAINT = "#8C8A84"    # metadata: filenames, counts, provenance
NAVY = "#1C2B45"         # chrome only, never a status

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

# Short forms for the tally strip only, where a card is too narrow for the
# Section 4 wording. The chips on the rows keep the Section 4 wording in
# full: that table is normative and the reference's shorter chip labels
# would be a spec change, not a restyle.
TALLY_LABEL = {
    "MET": "Evidence found",
    "AMBIGUOUS": "Unresolved",
    "NOT_MET": "Needs review",
    "NOT_APPLICABLE": "Not required",
    None: "No result produced",
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
# provenance belongs, and the artifact filename stays verbatim in the mode bar
# because that is an identifier a reviewer may need to quote.
# ---------------------------------------------------------------------------

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")

# Tokens that are initialisms rather than words. Derived from the corpus
# filenames, not guessed: `scripts/` has no document whose name contains an
# initialism outside this set.
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


def document_label(filename: str) -> str:
    """`2026-07-30_consultant_letter.txt` -> `Consultant letter, 30 July 2026`.

    A leading document code with no date, as the injection documents carry,
    is moved to the end in brackets rather than dropped: it is the only thing
    distinguishing those documents from one another by name.
    """
    import re
    stem = filename.rsplit(".", 1)[0]
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[_-](.+)$", stem)
    if m:
        year, month, day, rest = m.groups()
        try:
            when = f"{int(day)} {MONTHS[int(month) - 1]} {year}"
        except (ValueError, IndexError):
            return humanise(stem)
        return f"{humanise(rest)}, {when}"
    code = re.match(r"^([A-Za-z]{2,4}-\d+)[_-](.+)$", stem)
    if code:
        return f"{humanise(code.group(2))} ({code.group(1).upper()})"
    return humanise(stem)


def reason_label(code: str) -> str:
    """Prose for a reason code, never the code itself.

    The fallback used to be the code, so an unmapped one would put
    `MISSING_EVIDENCE` on screen. It now reads as a sentence either way.
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
  /* Base scale. The reference HTML was authored at chat width and sized for
     that container; in a full browser window the same numbers read small.
     Nothing is below 12px, including the metadata. */
  section[data-testid='stMain'] {{ font-size:15.5px; }}
  section[data-testid='stMain'] p,
  section[data-testid='stMain'] li {{ font-size:15.5px; line-height:1.6; }}
  section[data-testid='stMain'] [data-testid='stCaptionContainer'] p
      {{ font-size:12.5px; }}

  div[class*='st-key-row_'] {{
      background:{PANEL}; border:1px solid {RULE}; border-left:3px solid {RULE};
      border-radius:4px; padding:15px 18px; margin-bottom:10px;
  }}

  /* Masthead: first thing on the page, restrained enough not to dominate. */
  .cite-title {{ font-size:22px; font-weight:600; letter-spacing:-.015em;
      color:{NAVY}; line-height:1.15; }}
  .cite-strap {{ font-size:14px; color:{INK_SOFT}; margin-top:2px; }}
  .cite-notice {{ font-size:12.5px; color:{INK_FAINT}; margin-top:7px; }}

  .cite-wordmark {{ font-size:19px; font-weight:600; letter-spacing:-.015em;
      color:{NAVY}; line-height:1.1; }}
  .cite-tagline {{ font-size:13px; color:{INK_FAINT}; margin-top:3px;
      padding-bottom:16px; border-bottom:1px solid {RULE}; }}
  .cite-quiet {{ font-size:12.5px; color:{INK_FAINT}; line-height:1.55;
      max-width:80ch; }}
  .cite-quiet b {{ color:{INK_SOFT}; font-weight:600; }}
  .cite-bar {{ background:{NAVY}; color:#fff; border-radius:6px;
      padding:10px 15px; font-size:14px; display:flex;
      justify-content:space-between; align-items:center; gap:16px; }}
  .cite-bar .sub {{ opacity:.75; font-size:12.5px; white-space:nowrap; }}
  .cite-case {{ font-size:18px; font-weight:600; color:{INK};
      margin:14px 0 0; line-height:1.3; }}
  .cite-case-sub {{ font-size:14px; color:{INK_SOFT}; margin:1px 0 4px; }}
  .cite-prov {{ font-size:12.5px; color:{INK_FAINT}; margin:11px 2px 17px; }}
  .cite-tallies {{ display:flex; gap:10px; margin-bottom:17px; }}
  .cite-tally {{ flex:1; background:{PANEL}; border:1px solid {RULE};
      border-left:3px solid {RULE}; border-radius:4px; padding:10px 14px; }}
  .cite-tally .n {{ font-size:23px; font-weight:600; line-height:1.2; }}
  .cite-tally .k {{ font-size:12.5px; color:{INK_SOFT}; }}

  /* The row. Requirement and quote are the primary text of the page. */
  .cite-head {{ display:flex; justify-content:space-between;
      align-items:flex-start; gap:20px; }}
  .cite-req {{ font-size:16px; font-weight:500; color:{INK};
      line-height:1.45; }}
  .cite-req .id {{ color:{INK_FAINT}; font-weight:400; margin-right:8px; }}
  .cite-chip {{ flex:none; font-size:12px; font-weight:500; padding:3px 11px;
      border-radius:3px; white-space:nowrap; margin-top:2px; }}
  .cite-why {{ font-size:13.5px; margin-top:6px; line-height:1.5; }}
  .cite-quote {{ margin-top:10px; padding-left:12px; border-left:2px solid
      {RULE}; font-size:15px; color:{INK}; line-height:1.55; }}
  .cite-source {{ margin-top:6px; font-size:12px; color:{INK_FAINT}; }}
  .cite-source b {{ color:{INK_SOFT}; font-weight:500; }}
  .cite-label {{ font-size:12px; color:{INK_FAINT}; font-weight:600;
      text-transform:uppercase; letter-spacing:.05em; }}
  .cite-demo {{ font-size:12.5px; font-weight:600; color:{INK_SOFT}; }}

  /* Footer notice: always present, never the first thing read. */
  .cite-footer {{ border-top:1px solid {RULE}; margin-top:34px;
      padding-top:14px; font-size:12.5px; color:{INK_FAINT}; line-height:1.55;
      max-width:80ch; }}
  .cite-footer b {{ color:{INK_SOFT}; font-weight:600; }}

  /* The row expander is a quiet inline affordance, not a panel. */
  div[class*='st-key-row_'] details {{ border:none !important;
      background:transparent !important; }}
  div[class*='st-key-row_'] summary {{ font-size:13.5px; color:{NAVY};
      padding-left:0 !important; }}
  div[class*='st-key-row_'] summary p {{ font-size:13.5px !important; }}
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


def summary_strip(results: list[dict], running: int = 0) -> str:
    """Counts by status, so the shape of the case is visible before any row.

    A reviewer working a queue wants to know whether this is four clean
    requirements and one problem, or five problems, before reading a word.
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
        edge = DISPLAY[key][3]
        fg = DISPLAY[key][1]
        cells.append(
            f"<div class='cite-tally' style='border-left-color:{edge}'>"
            f"<div class='n' style='color:{fg}'>{counts[key]}</div>"
            f"<div class='k'>{TALLY_LABEL[key]}</div></div>")
    if running:
        cells.append(f"<div class='cite-tally'><div class='n'>{running}</div>"
                     f"<div class='k'>Running</div></div>")
    return f"<div class='cite-tallies'>{''.join(cells)}</div>"


def mode_bar(label: str, detail: str) -> str:
    """One compact line. It was a two-line block that pushed the rows down."""
    return (f"<div class='cite-bar'><span>{label}</span>"
            f"<span class='sub'>{detail}</span></div>")


# ---------------------------------------------------------------------------

# The masthead. The application names itself at the top of the content, not
# only in the sidebar, because a reviewer looking at a screenshot or a shared
# window should not have to find the rail to know what they are looking at.
# Restrained at 22px: the old `st.title` dominated the rows, which are the
# thing being read.
st.markdown(
    f"<div class='cite-title'>{APP_NAME}</div>"
    f"<div class='cite-strap'>{APP_SUBTITLE}</div>"
    f"<div class='cite-notice'>Synthetic demonstration · no coverage "
    f"determination produced</div>", unsafe_allow_html=True)

# The full constraint notice was six lines of body text here, at the top of
# the main column. Spec Section 10 requires it on screen; it does not require
# it to occupy the most valuable space on the page, and as the loudest element
# it was also the easiest to stop seeing. It now appears three ways: the line
# above, always visible; the expander below; and a footer on every screen.
FULL_NOTICE = (
    "<b>Synthetic demonstration.</b> All criteria are synthetic demonstration "
    "criteria modelled on published coverage determination patterns; they are "
    "<b>not Humana coverage policies</b>. All clinical records are synthetic — "
    "no real or de-identified patient data is used. This system produces no "
    "coverage determination, recommendation, or score. A licensed clinician "
    "reviews the evidence and makes any decision.")

with st.expander("about this demonstration"):
    st.markdown(f"<div class='cite-quiet'>{FULL_NOTICE}</div>",
                unsafe_allow_html=True)

available = saved_runs()
if not available:
    st.error("No recorded runs found in `runs/`. Run `scripts/run_eval.py` first.")
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
        case_id = st.selectbox("Case", all_cases)
        run_path = None
    else:
        case_id = st.selectbox("Case", sorted(available))
        run_paths = available[case_id]
        labels = {p.name: p for p in run_paths}
        chosen = st.selectbox("Recorded run", list(labels), index=0)
        run_path = labels[chosen]

    # Secondary by placement as well as by label. Mode and case are the
    # working controls; this is a demonstration aid and is separated from
    # them so it does not read as part of the review workflow.
    st.markdown(
        f"<div style='margin-top:22px;padding-top:14px;border-top:1px solid "
        f"{RULE}'><div class='cite-demo'>Demo control</div>"
        f"<div class='cite-quiet' style='margin:3px 0 8px'>Injected faults "
        f"show how failures are handled. Spec Section 13 requires them to be "
        f"labelled as injected. <b>Not an observed error rate.</b></div></div>",
        unsafe_allow_html=True)
    fault = st.radio(
        "Inject",
        [Fault.NONE, Fault.UNVERIFIABLE_QUOTE, Fault.OUTPUT_TRUNCATION],
        format_func=lambda f: {
            Fault.NONE: "No fault",
            Fault.UNVERIFIABLE_QUOTE: "Unverifiable quote",
            Fault.OUTPUT_TRUNCATION: "Model output truncated",
        }[f],
        key="fault")

criteria_set = load_criteria(
    next(c["procedure_id"] for c in
         json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())["cases"]
         if c["case_id"] == case_id))
packet = ingest_case(case_id, CASES)


def mode_banner(kind: str, detail: str, progress=None) -> None:
    """The mode, stated so it cannot be missed, on one line.

    This was a two-line block with a progress track under it, which pushed
    the rows down the page on every screen. It is now a single bar: the
    mode on the left, its detail on the right. Prominence comes from being
    the only navy block above the content, not from height.

    A recorded run read as live is the same class of error as a stale status
    read as current, and in a demonstration it is the one a viewer has no
    way to detect for themselves. Never green: the bar is the largest block
    of colour on the page and a green one teaches "green means fine", which
    is the association the status palette exists to avoid.
    """
    label = {
        "recorded": "Recorded run · not live",
        "live": "Live run · in progress",
        "live-done": "Live run · complete",
    }[kind]
    if progress is not None:
        done, total = progress
        detail = f"{done} of {total} requirements complete"
    st.markdown(mode_bar(label, detail), unsafe_allow_html=True)


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
        st.info("Press the button to execute the pipeline against this case.",
                icon=":material/play_circle:")
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
    mode_banner("live-done", f"{case['case_id']} · {run_path.name}")
    st.markdown(
        f"<div class='cite-quiet' style='margin:6px 2px 0'>Executed "
        f"{live_payload.get('generated')}. Artifact written to "
        f"<code>runs/live/</code>, outside the evaluation path.</div>",
        unsafe_allow_html=True)
else:
    data, case = load_case(run_path, case_id)
    extraction = case["extraction"]
    verification = case["verification"]
    # The bar carries the mode and the artifact. The sentence explaining
    # what a recorded run means goes under it as quiet text: a one-line bar
    # stops being one line if a sentence is put in it.
    mode_banner("recorded", run_path.name)
    st.markdown(
        f"<div class='cite-quiet' style='margin:6px 2px 0'>Generated "
        f"{data.get('generated', 'unknown')}. Citations resolve against the "
        f"packet as it stood then. Nothing is being executed.</div>",
        unsafe_allow_html=True)

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
    st.error(
        f"**{injection.headline}.** {injection.detail}\n\n"
        f"Target: {injection.target}."
        + (f" {injection.provenance}" if injection.provenance else "")
        + "\n\nThis control demonstrates that failure handling works. "
          "It is **not an observed error rate**.",
        icon=":material/science:")

# criteria_set and packet are loaded above, before the mode branch, because a
# live run needs both to draw its row list before any call is made.

# --- provenance, present and quiet ----------------------------------------
# This was four stat cards and a version line, which occupied the top third
# of the screen before any requirement appeared. Provenance has to be
# recoverable, not prominent: a reviewer reads it once when something looks
# wrong, and never otherwise. One line, with the version strings behind it.
# The case is what the reviewer is looking at, so it is a heading. The
# procedure carries its own proper name in the criteria set — there is no need
# to derive one from `lumbar_fusion`. Criteria version, configuration and
# document count are provenance and have moved into the expander below; on the
# same line as the case name they turned it into one grey debug string.
st.markdown(
    f"<div class='cite-case'>Case {case_id}</div>"
    f"<div class='cite-case-sub'>{criteria_set.procedure_name} · CPT "
    f"{criteria_set.cpt}</div>", unsafe_allow_html=True)

with st.expander("run provenance"):
    st.markdown(
        f"<div class='cite-quiet'>"
        f"criteria set <code>{criteria_set.version}</code> · configuration "
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
        + f"</div>", unsafe_allow_html=True)

# --- the evidence map ------------------------------------------------------
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


st.markdown(summary_strip(verification["results"]), unsafe_allow_html=True)

for result in verification["results"]:
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
        # --- head: requirement left, status chip inline right -------------
        fg = DISPLAY.get(clinical, DISPLAY[None])[1]
        head = (
            f"<div class='cite-head'>"
            f"<div class='cite-req'><span class='id'>{criterion_id}</span>"
            f"{criterion.text}</div>"
            f"{status_chip(clinical)}</div>")

        # --- a reason line only where the requirement did not resolve -----
        # MET rows carry no why line: there is nothing unresolved to explain
        # and a line there is one more thing to read past on a clean row.
        why = ""
        if processing != "COMPLETE":
            # Off the clinical scale. A processing failure is the absence of
            # a result, not a poor one, so it says so in its own words and
            # its own colour rather than borrowing clinical vocabulary.
            detail = result.get("detail") or ""
            why = (f"<div class='cite-why' style='color:{DISPLAY[None][1]}'>"
                   f"Processing incomplete — {processing.lower()}"
                   f"{'. ' + detail if detail else ''} No clinical result was "
                   f"reached.</div>")
        elif result["reason_codes"] and clinical != "MET":
            codes = " ".join(reason_label(c) for c in result["reason_codes"])
            if result.get("downgraded"):
                codes += (f" Downgraded from {result.get('extracted_status')} "
                          f"during verification.")
            why = f"<div class='cite-why' style='color:{fg}'>{codes}</div>"

        # --- one quote, then its source -----------------------------------
        evidence = result["evidence"]
        body = ""
        if evidence:
            by_role: dict[str, list[dict]] = {}
            for item in evidence:
                by_role.setdefault(item["role"], []).append(item)
            lead = evidence[0]
            more = len(evidence) - 1
            unverified = sum(1 for e in evidence if not e["verified"])
            state = (f"<span style='color:{DISPLAY['NOT_MET'][1]}'>"
                     f"{unverified} unverifiable</span>" if unverified
                     else "all verified")
            roles = ", ".join(f"{len(v)} {k}" for k, v in by_role.items())
            body = (
                f"<div class='cite-quote'>“{preview(lead['quote'], 170)}”</div>"
                f"<div class='cite-source'>"
                f"<b>{filename_for(lead['document_id'])}</b>"
                f"{f' · {more} more passage' + ('s' if more > 1 else '') if more else ''}"
                f" · {roles} · {state}</div>")

        st.markdown(head + why + body, unsafe_allow_html=True)

        # --- everything else behind one expander --------------------------
        if evidence:
            n = len(evidence)
            with st.expander(f"{n} passage{'s' if n > 1 else ''} and sources"):
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
                            f"style='margin:12px 0 5px'>"
                            f"{role} · {len(items)}</div>",
                            unsafe_allow_html=True)
                    for item in items:
                        if not item["verified"]:
                            st.markdown(
                                f"<div style='color:{DISPLAY['NOT_MET'][1]};"
                                f"font-size:12.5px'><b>Unverifiable.</b> "
                                f"{item.get('detail', '')}</div>",
                                unsafe_allow_html=True)
                            st.markdown(f"> {item['quote']}")
                            continue
                        span = item.get("span") or {}
                        try:
                            doc = packet.by_id(item["document_id"])
                        except KeyError:
                            st.caption("The cited document is not in this packet.")
                            continue
                        start, end = span.get("start", 0), span.get("end", 0)
                        pad = 420
                        before = doc.canonical[max(0, start - pad):start]
                        cited = doc.canonical[start:end]
                        after = doc.canonical[end:end + pad]
                        # Provenance, in full. The readable name is above;
                        # this is where the raw handle belongs.
                        st.caption(
                            f"{document_label(doc.filename)} · file "
                            f"`{doc.filename}` · `{item['document_id']}` · "
                            f"characters {start} to {end} · sha256 "
                            f"{span.get('content_sha256', '')[:12]}")
                        # The surrounding density is realistic and stays. The
                        # highlight is what makes it survivable, so it is loud.
                        st.markdown(
                            f"<div style='background:{PAPER};border:1px solid "
                            f"{RULE};padding:14px;border-radius:4px;"
                            f"white-space:pre-wrap;font-family:ui-monospace,"
                            f"monospace;font-size:12.5px;line-height:1.6;"
                            f"color:{INK_SOFT}'>"
                            f"<span style='color:{INK_FAINT}'>…{before}</span>"
                            f"<mark style='background:#FFD84D;color:{INK};"
                            f"font-weight:600;padding:2px 3px;border-radius:2px'>"
                            f"{cited}</mark>"
                            f"<span style='color:{INK_FAINT}'>{after}…</span>"
                            f"</div>", unsafe_allow_html=True)

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
