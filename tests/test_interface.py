"""The interface, checked for the constraints it must never violate.

Streamlit apps are hard to test end to end and easy to test for the two things
that matter here: that no decision vocabulary reaches the screen, and that the
clinical and processing fields stay separate. Both are hard constraints in
CLAUDE.md and Spec Sections 3 and 10, and both are the kind of thing that
erodes through a well-meaning label change rather than a deliberate one.
"""

import ast
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

APP = PROJECT_ROOT / "app.py"


def code_only(path: Path) -> str:
    """Source with docstrings removed, so prose disclaiming a term does not
    read as the violation it disclaims."""
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body.pop(0)
    return ast.unparse(tree)


class NoDecisionControlTests(unittest.TestCase):
    def test_the_app_parses(self) -> None:
        ast.parse(APP.read_text())

    def test_determination_vocabulary_appears_only_under_negation(self) -> None:
        """CLAUDE.md forbids offering a determination, not disclaiming one.

        The interface must state that it produces no coverage determination,
        recommendation, or score, and that sentence necessarily contains the
        words. An earlier version of this test flagged the disclaimer as the
        violation it disclaims. What is checked instead is that every
        occurrence sits inside a negation.
        """
        import re
        code = code_only(APP).lower()
        negations = ("no ", "not ", "never", "without", "makes any decision",
                     "cannot", "nothing")
        for banned in ("approve", "deny", "denied", "authorize", "authorise",
                       "recommendation", "recommend", "aggregate score",
                       "overall score", "confidence"):
            for m in re.finditer(re.escape(banned), code):
                window = code[max(0, m.start() - 70):m.start()]
                self.assertTrue(
                    any(n in window for n in negations),
                    f"{banned!r} appears without a negation before it: "
                    f"...{code[max(0, m.start() - 70):m.end() + 20]}...")

    def test_no_button_or_control_offers_a_decision(self) -> None:
        code = code_only(APP)
        tree = ast.parse(code)
        widgets = {"button", "radio", "selectbox", "checkbox", "toggle",
                   "form_submit_button"}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = getattr(fn, "attr", None)
            if name not in widgets:
                continue
            for arg in list(node.args) + [k.value for k in node.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    low = arg.value.lower()
                    for banned in ("approve", "deny", "authorize", "decision"):
                        self.assertNotIn(
                            banned, low,
                            f"a control labelled {arg.value!r} offers a decision")


class SeparationTests(unittest.TestCase):
    def test_clinical_and_processing_are_rendered_as_separate_fields(self) -> None:
        """Two fields, two renderings — but not two permanent labelled rows.

        This used to require the literal "Clinical result" and "Processing
        state" labels. The first was removed deliberately: with the raw enum
        gone, the chip is the only thing stating the clinical result and a
        label above it repeated itself. Requiring the string would have
        forced a redundant label to keep a test green, which is the test
        driving the interface rather than describing it.

        What has to hold is the separation itself, so that is what is
        asserted: the two fields are read independently, the processing
        state has its own labelled rendering, and it is never routed
        through the clinical chip.
        """
        code = code_only(APP)
        self.assertIn("clinical = result['clinical_status']", code)
        self.assertIn("processing = result['processing_status']", code)
        self.assertIn("Processing incomplete", code)
        # The chip renders the clinical field only. If `processing` were
        # ever passed to it, a system failure would acquire clinical wording.
        self.assertNotIn("status_chip(processing)", code)

    def test_an_incomplete_processing_state_is_always_shown(self) -> None:
        """It may be hidden when COMPLETE — saying so on every row is noise —
        but never when it is not, because that is the case where a reviewer
        must know the pipeline did not finish."""
        code = code_only(APP)
        self.assertIn("if processing != 'COMPLETE':", code)
        i = code.index("if processing != 'COMPLETE':")
        window = code[i:i + 700]
        self.assertIn("Processing incomplete", window)
        self.assertIn("No clinical result was", window,
                      "an incomplete run must say no clinical result was reached")
        self.assertIn("result.get('detail')", window,
                      "the reason for an incomplete state must be shown with it")

    def test_a_failed_run_still_gets_clinical_display_wording(self) -> None:
        """`None` has an entry in DISPLAY, so a failure renders as "no
        clinical result produced" rather than as a blank chip or a status."""
        tree = ast.parse(APP.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", None) == "DISPLAY" for t in node.targets):
                d = {(k.value if isinstance(k, ast.Constant) else None):
                     ast.literal_eval(v)
                     for k, v in zip(node.value.keys, node.value.values)}
                self.assertIn(None, d)
                self.assertIn("No clinical result", d[None][0])
                return
        self.fail("DISPLAY not found")

    def test_the_raw_enum_is_not_printed_beside_the_wording(self) -> None:
        """Spec Section 4 gives display wording so the enum need not be on
        screen. Printing both said the same thing twice, in two
        vocabularies, one of which reads as a verdict."""
        tree = ast.parse(APP.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "status_chip")
        body = ast.unparse(fn)
        self.assertNotIn("<code", body,
                         "the chip must render the wording only")
        self.assertNotIn("status or", body)

    def test_every_status_has_display_wording(self) -> None:
        """Spec Section 4 gives display wording per status; a bare enum on
        screen invites a reviewer to read MET as approved."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("app_probe", APP)
        # Do not execute the module; read the mapping out of the AST instead.
        tree = ast.parse(APP.read_text())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if getattr(t, "id", None) == "DISPLAY":
                        for k in node.value.keys:
                            if isinstance(k, ast.Constant):
                                found.add(k.value)
        for status in ("MET", "NOT_MET", "AMBIGUOUS", "NOT_APPLICABLE", None):
            self.assertIn(status, found, f"no display wording for {status}")

    def test_ambiguous_and_not_met_render_differently(self) -> None:
        """Spec Section 10: AMBIGUOUS renders distinctly from NOT_MET."""
        tree = ast.parse(APP.read_text())
        display = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if getattr(t, "id", None) == "DISPLAY":
                        for k, v in zip(node.value.keys, node.value.values):
                            if isinstance(k, ast.Constant):
                                display[k.value] = ast.literal_eval(v)
        self.assertNotEqual(display["AMBIGUOUS"], display["NOT_MET"])
        self.assertNotEqual(display["AMBIGUOUS"][0], display["NOT_MET"][0])


class ReadingOrderTests(unittest.TestCase):
    """Order is a correctness property here, not a preference.

    A reviewer who reads a justification before learning what the requirement
    resolved to has been led through the reasoning before the conclusion,
    which is the wrong way round for someone scanning twenty rows.
    """

    def test_status_is_rendered_before_the_explanation(self) -> None:
        """Anchored on the chip. The "Clinical result" label it used to key
        on was removed deliberately: with the raw enum gone the chip is the
        only thing saying the clinical result, so a second label above it
        was repeating itself."""
        code = code_only(APP)
        self.assertLess(code.index("status_chip(clinical)"),
                        code.index("result['explanation']"),
                        "the clinical result must come before the explanation")

    def test_evidence_is_rendered_before_the_explanation(self) -> None:
        """Anchored on the evidence binding rather than a heading string.

        This previously keyed on the literal "**Evidence**", which a restyle
        replaced with an inline passage block. The test then raised
        ValueError rather than failing with a message — a test that cannot
        express what went wrong. Reading order is a property of the code's
        structure, so that is what is asserted.
        """
        code = code_only(APP)
        self.assertLess(code.index("evidence = result['evidence']"),
                        code.index("result['explanation']"),
                        "evidence must come before the explanation")

    def test_the_first_passage_is_readable_without_expanding(self) -> None:
        """A reviewer scanning a queue should see what a row rests on
        without opening it.

        Scoped to the row loop. The first version compared against the
        first `st.expander` anywhere in the file, which stopped meaning
        anything the moment a provenance expander was added above the rows:
        it was then measuring the distance to an unrelated widget.
        """
        code = code_only(APP)
        loop = code[code.index("for result in verification['results']:"):]
        self.assertIn("lead = evidence[0]", loop)
        self.assertIn("more passage", loop)
        self.assertLess(loop.index("lead = evidence[0]"),
                        loop.index("st.expander"),
                        "the inline passage must precede the expanders")

    def test_a_row_opens_one_expander_not_one_per_passage(self) -> None:
        """Nine passages used to mean nine collapsed bars stacked under one
        requirement, which is a wall whether or not it is collapsed."""
        code = code_only(APP)
        loop = code[code.index("for result in verification['results']:"):]
        inner = loop[loop.index("for item in items:"):]
        self.assertNotIn("st.expander", inner.split("elif")[0],
                         "passages must not each open their own expander")
        self.assertIn("passage{('s' if n > 1 else '')} and sources", loop)

    def test_collapsed_rows_carry_a_quote_preview(self) -> None:
        """A row must show what it rests on without being opened.

        This used to be satisfied by per-passage expander labels. Those are
        gone — nine passages meant nine collapsed bars under one
        requirement — and the inline lead quote carries the property now.
        """
        code = code_only(APP)
        self.assertIn("def preview", code)
        self.assertIn("preview(lead['quote']", code)

    def test_collapsed_rows_show_a_filename_not_an_id(self) -> None:
        code = code_only(APP)
        self.assertIn("filename_for(lead['document_id'])", code)
        # The id stays available where the hash and offsets already are.
        # Located by the sha256 caption rather than by position, because the
        # first st.caption in the file is the page header.
        detail = next(line for line in code.splitlines() if "sha256" in line)
        i = code.index(detail)
        window = code[max(0, i - 400):i + 200]
        self.assertIn("item['document_id']", window,
                      "the document id must remain in the expanded detail")

    def test_evidence_is_grouped_with_counts(self) -> None:
        code = code_only(APP)
        self.assertIn("by_role", code)
        self.assertIn("counts", code)


def live_branch(tree: ast.AST) -> ast.If:
    """The `if live_mode:` block, as an AST node."""
    for node in ast.walk(tree):
        if (isinstance(node, ast.If) and isinstance(node.test, ast.Name)
                and node.test.id == "live_mode"):
            return node
    raise AssertionError("no `if live_mode:` branch found in app.py")


def live_only_ids(tree: ast.AST) -> set[int]:
    """Nodes in the live branch *body*, excluding its `else`.

    Walking the `If` node itself would include `orelse`, which is the
    recorded path. A first version of these tests did exactly that and
    concluded the recorded path never declared its mode.
    """
    ids: set[int] = set()
    for stmt in live_branch(tree).body:
        ids.update(id(n) for n in ast.walk(stmt))
    return ids


def hsv(hex_colour: str) -> tuple[float, float, float]:
    import colorsys
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hue, s, v = colorsys.rgb_to_hsv(r, g, b)
    return hue * 360, s, v


def _lab(hex_colour: str) -> tuple[float, float, float]:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def inv(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = inv(r), inv(g), inv(b)
    X = r * 0.4124 + g * 0.3576 + b * 0.1805
    Y = r * 0.2126 + g * 0.7152 + b * 0.0722
    Z = r * 0.0193 + g * 0.1192 + b * 0.9505

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(X / 0.95047), f(Y / 1.0), f(Z / 1.08883)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e(a: str, b: str) -> float:
    """CIE76 perceptual distance. Above ~20 reads as clearly different."""
    return sum((x - y) ** 2 for x, y in zip(_lab(a), _lab(b))) ** 0.5


def display_map() -> dict:
    tree = ast.parse(APP.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if getattr(t, "id", None) == "DISPLAY":
                    return {(k.value if isinstance(k, ast.Constant) else None):
                            ast.literal_eval(v)
                            for k, v in zip(node.value.keys, node.value.values)}
    raise AssertionError("DISPLAY not found")


class StatusPaletteTests(unittest.TestCase):
    """Colour carries meaning here, so it is constrained like any other output.

    Two rules, both from the same place as the no-determination rule. Green
    reads as approved and red as denied, and this system produces neither.
    Humana's brand is green, which is the specific reason a brand colour may
    appear in chrome and never on a status.
    """

    # Hues a viewer reads as "success". Canonical success greens cluster at
    # 120-145 (Material Green 600-900 are 122-125, A700 is 145). The band is
    # 90-155, which covers them with margin on both sides.
    #
    # The upper edge was 165 until the reference palette arrived. That
    # excluded the reference's own `found`, a deep teal at 164.8 — a colour
    # on the teal side of the green boundary, 9.8 above the edge now used.
    # The band was widened to the point where it still catches every green
    # anyone would read as "approved" and stops catching teal.
    GREEN_BAND = (90, 155)

    # Colours that unambiguously mean approved or denied. Distance from
    # these is the property the rule is really about; a hue band alone
    # cannot express "not the approve colour".
    VERDICT = {
        "Material Green 600": "#43A047", "Green 700": "#388E3C",
        "Green 800": "#2E7D32", "Green 900": "#1B5E20",
        "Success A700": "#00C853", "Material Red 600": "#E53935",
        "Red 700": "#D32F2F", "Red 800": "#C62828", "Red 900": "#B71C1C",
    }

    def test_no_status_uses_a_green(self) -> None:
        for status, entry in display_map().items():
            for colour in entry[1:]:
                hue, sat, _ = hsv(colour)
                if sat < 0.12:          # greys carry no hue signal
                    continue
                self.assertFalse(
                    self.GREEN_BAND[0] <= hue <= self.GREEN_BAND[1],
                    f"{status} uses {colour} at hue {hue:.0f}, which reads as "
                    f"approved and is Humana's brand family")

    def test_no_status_is_near_an_approve_or_deny_colour(self) -> None:
        """The rule stated as distance rather than as hue.

        Measured margins at the time of writing, so a future reader can see
        how much room there is rather than only that it passed: MET is ΔE 24
        from Green 900 and NOT_MET is ΔE 22 from Red 900. Both clear the
        conventional ΔE 20 "clearly different colours" line, the second of
        them by little. These are deep teal and rust, not signal colours,
        and the wording, the left edge and the reason line all carry the
        status independently of hue.
        """
        for status, entry in display_map().items():
            edge = entry[3]
            if hsv(edge)[1] < 0.12:
                continue
            for name, verdict in self.VERDICT.items():
                gap = delta_e(edge, verdict)
                self.assertGreaterEqual(
                    gap, 20,
                    f"{status} edge {edge} is only ΔE {gap:.0f} from "
                    f"{name} ({verdict}), close enough to read as a verdict")

    def test_the_three_clinical_statuses_are_distinguishable(self) -> None:
        """Amber against coral is the pair most at risk of collapsing.

        Measured as CIE ΔE, not as a hue gap. A hue threshold was tried
        first and was the wrong instrument: amber and coral sit 36° apart,
        which looks alarming, while their actual perceptual distance is ~51
        because they also differ in lightness and saturation. ΔE above 20 is
        the conventional "clearly different colours" mark; 25 is used here
        and the palette clears it with room, so the threshold is not fitted
        to the colours.
        """
        d = display_map()
        pairs = [("MET", "NOT_MET"), ("MET", "AMBIGUOUS"),
                 ("NOT_MET", "AMBIGUOUS")]
        for a, b in pairs:
            gap = delta_e(d[a][3], d[b][3])
            self.assertGreaterEqual(
                gap, 25,
                f"{a} and {b} are only ΔE {gap:.0f} apart, too close to read "
                f"apart at a glance")

    def test_colour_is_never_the_only_signal(self) -> None:
        """A row must be readable by someone who cannot distinguish the
        hues at all, so every status carries distinct wording too."""
        labels = [v[0] for v in display_map().values()]
        self.assertEqual(len(labels), len(set(labels)))

    def test_a_processing_failure_is_off_the_clinical_scale(self) -> None:
        """`None` is the absence of a clinical result, not a bad one, so it
        must not sit on the same warm-to-teal scale as the three statuses."""
        d = display_map()
        for status in ("MET", "NOT_MET", "AMBIGUOUS"):
            self.assertGreaterEqual(
                delta_e(d[None][3], d[status][3]), 25,
                f"the no-result colour reads as {status}")


class ChromeTests(unittest.TestCase):
    def test_the_application_is_named_cite(self) -> None:
        code = code_only(APP)
        self.assertIn('APP_NAME = \'Cite\'', code)
        self.assertIn("Evidence mapping for utilization management", code)
        self.assertNotIn("UM Evidence Map", code)

    def test_the_wordmark_is_in_the_sidebar_not_a_page_heading(self) -> None:
        """A large page title on every screen costs vertical space on the
        rows, which are what is being read."""
        code = code_only(APP)
        self.assertNotIn("st.title(", code)
        i = code.index("with st.sidebar:")
        self.assertIn("cite-wordmark", code[i:i + 600],
                      "the wordmark must sit at the top of the sidebar")

    def test_the_synthetic_notice_is_quiet_but_present(self) -> None:
        """Spec Section 10 requires it on screen, not requiring it to shout.
        It was a warning block, which made it the loudest thing on the page
        and therefore the easiest to stop seeing."""
        code = code_only(APP)
        self.assertIn("Synthetic demonstration", code)
        self.assertIn("not Humana coverage policies", code)
        self.assertNotIn("st.warning(\n    '**Synthetic", code)

    def test_the_mode_bar_states_every_mode(self) -> None:
        for kind in ("Recorded run · not live", "Live run · in progress",
                     "Live run · complete"):
            self.assertIn(kind, code_only(APP))

    def test_the_mode_bar_is_one_line(self) -> None:
        """It was a two-line block with a progress track beneath, which
        pushed the rows down the page on every screen."""
        code = code_only(APP)
        self.assertIn("class='cite-bar'", code)
        self.assertIn("justify-content:space-between", code)

    def test_the_mode_bar_is_not_green(self) -> None:
        """It is the largest block of colour on the page; a green one
        teaches the association the status palette exists to avoid.

        The first version of this test sliced the function body with
        `block.index("def ")`, which matched `def mode_banner` at offset
        zero and left an empty string. It scanned nothing and passed while
        the bar was green. The body is now located through the AST, and the
        test asserts it found colours before judging them.
        """
        import re
        code = APP.read_text()
        i = code.index(".cite-bar {{")
        # The bar's background is the NAVY constant, interpolated into the
        # stylesheet, so both the constant and the rule are checked.
        colours = re.findall(r"#[0-9a-fA-F]{6}", code[i:i + 220])
        colours.append(re.search(r'NAVY = "(#[0-9a-fA-F]{6})"', code).group(1))
        self.assertIn("{NAVY}", code[i:i + 220],
                      "the bar must take its colour from the NAVY constant")
        self.assertTrue(colours, "no colours found; the test would be a no-op")
        judged = 0
        for colour in colours:
            hue, sat, _ = hsv(colour)
            if sat < 0.12:
                continue
            judged += 1
            self.assertFalse(75 <= hue <= 165,
                             f"the mode bar uses {colour}, a green")
        self.assertTrue(judged, "every bar colour was grey; nothing was checked")

    def test_the_live_bar_reports_progress(self) -> None:
        code = code_only(APP)
        self.assertIn("requirements complete", code)
        self.assertIn("progress=(done, len(state))", code,
                      "the live bar must show how far the run has got")

    def test_a_summary_strip_precedes_the_rows(self) -> None:
        code = code_only(APP)
        self.assertIn("def summary_strip", code)
        self.assertLess(code.index("st.markdown(summary_strip"),
                        code.index("for result in verification['results']:"),
                        "the strip must come before the rows it summarises")

    def test_the_summary_strip_shows_no_aggregate(self) -> None:
        """Counts by status, never a single number over a case. One number
        summarising a case is the score this system does not produce."""
        code = code_only(APP)
        block = code[code.index("def summary_strip"):]
        block = block[:block.index("\nst.markdown")]
        for banned in ("total", "sum(", "score", "overall"):
            self.assertNotIn(banned, block.lower())

    def test_rows_still_running_are_dimmed_and_show_their_stage(self) -> None:
        """Checked on the progress board, which is where a row is genuinely
        mid-flight.

        This first asserted on a "still running" branch inside the evidence
        map. That branch was unreachable: the map always renders a finished
        verification payload, which carries no `stage` field, so
        `result.get("stage")` was always None. The test passed on dead code
        dressed as a feature. The dimming now lives in `stage_row`, which
        is the only thing that draws a row while work is outstanding.
        """
        tree = ast.parse(APP.read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "stage_row")
        body = ast.unparse(fn)
        self.assertIn("opacity", body, "unfinished rows must be dimmed")
        self.assertIn("STAGE_DONE", body, "dimming must depend on the stage")
        # And the map must not pretend to have a running state.
        code = code_only(APP)
        loop = code[code.index("for result in verification['results']:"):]
        self.assertNotIn("result.get('stage')", loop,
                         "the evidence map renders finished results only")


class ModeAndScopeTests(unittest.TestCase):
    def test_the_mode_is_stated_not_inferred(self) -> None:
        """Every path that renders results must declare its mode first.

        This replaced a check for one literal banner string. That check
        passed for as long as the interface had a single mode and would have
        gone on passing when a second was added, because the recorded
        string was still in the file. What matters is that *both* paths
        announce themselves, so the assertion is on the branch structure.
        """
        tree = ast.parse(APP.read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "mode_banner"]
        self.assertGreaterEqual(len(calls), 2,
                                "each mode must state itself")
        in_live = live_only_ids(tree)
        self.assertTrue(any(id(c) in in_live for c in calls),
                        "the live path must declare itself")
        self.assertTrue(any(id(c) not in in_live for c in calls),
                        "the recorded path must declare itself")

    def test_the_recorded_banner_says_it_is_not_live(self) -> None:
        """The error this prevents is a recorded run read as a live one, in
        front of people who cannot check."""
        code = code_only(APP)
        self.assertIn("Recorded run · not live", code)
        self.assertIn("Nothing is being executed", code)

    def test_recorded_mode_touches_no_key_and_builds_no_client(self) -> None:
        """The repository is shared without a key, so recorded mode must not
        need one.

        This previously asserted that `ANTHROPIC_API_KEY` and
        `AnthropicClient` appear nowhere in the file, which was a sound test
        while there was no live mode and became impossible once there was.
        Weakening it to a substring check would have tested nothing. What is
        checked instead is stronger than the original: every reference to the
        key and every client construction must be lexically *inside* the live
        branch, so no recorded-mode code path can reach either.
        """
        tree = ast.parse(APP.read_text())
        inside = live_only_ids(tree)

        referenced = [n for n in ast.walk(tree)
                      if isinstance(n, ast.Constant)
                      and n.value == "ANTHROPIC_API_KEY"]
        self.assertTrue(referenced, "the live path must check for a key")
        for node in referenced:
            self.assertIn(id(node), inside,
                          "a key lookup sits outside the live branch, so "
                          "recorded mode would need a key")

        built = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "AnthropicClient"]
        self.assertTrue(built, "the live path must build a client")
        for node in built:
            self.assertIn(id(node), inside,
                          "a client is constructed outside the live branch; "
                          "recorded mode would fail without a key")

    def test_no_client_is_built_at_import_time(self) -> None:
        """A module-level client would break recorded mode on page load even
        if every other guard were correct."""
        tree = ast.parse(APP.read_text())
        for node in tree.body:
            if isinstance(node, (ast.Assign, ast.Expr)):
                for sub in ast.walk(node):
                    self.assertFalse(
                        isinstance(sub, ast.Call)
                        and isinstance(sub.func, ast.Name)
                        and sub.func.id == "AnthropicClient",
                        "a client is constructed at module scope")

    def test_the_live_run_is_wired_to_the_progress_display(self) -> None:
        """`run_live` must be called with `on_progress`.

        Without it the run still works and still writes a correct artifact,
        and the screen shows nothing until everything is finished — which is
        precisely the blank-screen behaviour the display exists to remove,
        and it would not fail any other test in this file.

        What this cannot check is that intermediate frames reach the browser.
        `AppTest` records final state only. What was verified separately is
        that the callback chain fires *during* the run rather than at the
        end: on a five-criterion case with a slowed client, rows reached
        `done` at 1.61s, 2.82s and 4.03s of a 4.03s run. Delivery of each
        placeholder write to the browser is Streamlit's behaviour, not this
        repository's, and is not asserted here.
        """
        tree = ast.parse(APP.read_text())
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                 and n.func.id == "run_live"]
        self.assertEqual(len(calls), 1, "exactly one live entry point")
        kwargs = {k.arg for k in calls[0].keywords}
        self.assertIn("on_progress", kwargs,
                      "the live run must report progress while it runs")

    def test_the_display_names_both_checks_separately(self) -> None:
        """The two-check design is the thing the display exists to show. A
        single 'verifying' would collapse Steps 4 and 5 into one word."""
        code = code_only(APP)
        self.assertIn("checking the quote", code)
        self.assertIn("checking the quote supports the claim", code)

    def test_a_failed_quote_is_surfaced_during_the_run(self) -> None:
        """Not only in the final state."""
        code = code_only(APP)
        self.assertIn("rejected_evidence", code)
        self.assertIn("failed verification", code)

    def test_a_live_run_cannot_write_into_the_scored_run_namespace(self) -> None:
        """`runs/` is where the eval harness and the recorded picker read."""
        from um_evidence.live import LIVE_RUNS
        self.assertEqual((LIVE_RUNS.parent.name, LIVE_RUNS.name),
                         ("runs", "live"))

    def test_the_synthetic_notice_is_present(self) -> None:
        code = code_only(APP)
        self.assertIn("not Humana coverage policies", code)
        self.assertIn("Synthetic demonstration", code)

    def test_add_document_and_rerun_are_absent(self) -> None:
        """Out of scope by decision, recorded in BUILD_SEQUENCE.md. Their
        absence is asserted so a partial version does not appear later
        without the supersession model."""
        code = code_only(APP).lower()
        for absent in ("add_document", "upload", "file_uploader"):
            self.assertNotIn(absent, code)


if __name__ == "__main__":
    unittest.main()
