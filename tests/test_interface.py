"""The interface, checked for the constraints it must never violate.

Streamlit apps are hard to test end to end and easy to test for the two things
that matter here: that no decision vocabulary reaches the screen, and that the
clinical and processing fields stay separate. Both are hard constraints in
CLAUDE.md and Spec Sections 3 and 10, and both are the kind of thing that
erodes through a well-meaning label change rather than a deliberate one.
"""

import ast
import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

APP = PROJECT_ROOT / "app.py"
APP_SUBTITLE_TEXT = "Evidence mapping for utilization management"


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


def render_calls(needle: str) -> list[str]:
    """Unparsed `st.markdown(...)` calls that mention `needle`.

    Searching the whole file for a class name finds the stylesheet rule that
    defines it, which is not evidence that anything renders with it. Two
    mutations — deleting the masthead, and dropping the notice out of the
    footer — both survived tests that did exactly that. These assertions look
    at render calls only.
    """
    tree = ast.parse(APP.read_text())
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "markdown"):
            text = ast.unparse(node)
            if "<style>" in text:
                continue          # the stylesheet, not a render
            if needle in text:
                out.append(text)
    return out


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

    def test_the_masthead_names_the_application_in_the_main_column(self) -> None:
        """A reviewer looking at a screenshot or a shared window should not
        have to find the sidebar to know what they are looking at.

        `st.title` stays out: it dominated the rows, which are the thing
        being read. The masthead is a restrained 22px instead.
        """
        code = code_only(APP)
        self.assertNotIn("st.title(", code)
        calls = render_calls("cite-title")
        self.assertTrue(calls,
                        "cite-title appears only in the stylesheet; nothing "
                        "renders the masthead")
        self.assertIn("APP_NAME", calls[0])
        self.assertIn("APP_SUBTITLE", " ".join(calls))
        css = APP.read_text()
        i = css.index(".cite-title {{")
        size = re.search(r"font-size:(\d+(?:\.\d+)?)px", css[i:i + 120])
        self.assertIsNotNone(size)
        self.assertLessEqual(float(size.group(1)), 24,
                             "the masthead must not dominate the rows")
        self.assertGreaterEqual(float(size.group(1)), 20)

    def test_the_name_is_rendered_once_not_in_both_columns(self) -> None:
        """The wordmark used to appear in the sidebar as well, so the name and
        tagline were on screen twice."""
        calls = render_calls("APP_NAME")
        self.assertEqual(len(calls), 1,
                         f"APP_NAME is rendered {len(calls)} times; it belongs "
                         f"in the masthead only")
        tree = ast.parse(APP.read_text())
        sidebar = [ast.unparse(n) for n in ast.walk(tree)
                   if isinstance(n, ast.With)
                   and "st.sidebar" in ast.unparse(n.items[0])]
        self.assertTrue(sidebar, "no sidebar block found")
        self.assertNotIn("APP_NAME", sidebar[0])
        self.assertNotIn("cite-wordmark", sidebar[0])

    def test_the_case_is_a_heading_not_a_metadata_string(self) -> None:
        """The case and procedure are what the reviewer is looking at.

        Criteria version, configuration and document count read as debug
        output beside them, so they moved into the provenance expander.
        """
        code = code_only(APP)
        heading = render_calls("cite-case")
        self.assertTrue(heading, "the case heading is not rendered")
        head = heading[0]
        self.assertIn("case_id", head)
        self.assertIn("procedure_name", head,
                      "the procedure's proper name, not its id")
        for provenance in ("criteria_set.version", "configuration",
                           "documents read"):
            self.assertNotIn(provenance, head,
                             f"{provenance} belongs in the provenance "
                             f"expander, not the case heading")

    def test_the_procedure_uses_its_proper_name_not_its_id(self) -> None:
        code = code_only(APP)
        self.assertIn("criteria_set.procedure_name", code)
        self.assertNotIn("procedure_id.replace", code,
                         "derive nothing from the id; the set carries a name")

    def test_the_masthead_is_the_first_thing_in_the_main_column(self) -> None:
        """It must precede the mode bar, the tallies and the rows."""
        code = code_only(APP)
        first = code.index("cite-title")
        for later in ("cite-bar", "cite-tallies", "summary_strip",
                      "for result in verification['results']:"):
            self.assertLess(first, code.index(later),
                            f"the masthead must come before {later}")

    def test_the_synthetic_notice_is_permanently_visible(self) -> None:
        """Spec Section 10 requires it on screen. Not on request.

        It appears three ways: a one-line summary under the masthead, an
        expander carrying the full text, and a footer rendered
        unconditionally. The footer is the one that satisfies the
        requirement, because an expander can be left closed and would make a
        mandatory notice opt-in.
        """
        code = code_only(APP)
        self.assertIn("Synthetic demonstration", code)
        self.assertIn("not Humana coverage policies", code)
        self.assertTrue(render_calls("cite-notice"),
                        "nothing renders the short notice line")
        footer = render_calls("cite-footer")
        self.assertTrue(footer, "nothing renders the footer")
        self.assertIn("FULL_NOTICE", footer[0],
                      "the footer renders but does not carry the constraint "
                      "notice, which is the only reason it exists")

        # The footer must not sit inside a conditional or an expander.
        tree = ast.parse(APP.read_text())
        footer = [n for n in tree.body
                  if isinstance(n, ast.Expr) and "cite-footer" in ast.unparse(n)]
        self.assertTrue(footer,
                        "the footer must be at module scope, not nested in a "
                        "branch or a `with st.expander` block")

    def test_the_notice_no_longer_occupies_the_top_of_the_column(self) -> None:
        """Six lines of legal text was the first thing a reviewer read, in
        the most valuable space on the page. The short line stands in for it
        there; the full text sits below the fold."""
        code = code_only(APP)
        self.assertLess(code.index("cite-title"), code.index("FULL_NOTICE"),
                        "the masthead must precede the full notice")
        # The full text must not be rendered above the evidence map.
        first_full = code.index("FULL_NOTICE =")
        rendered = [i for i in range(len(code))
                    if code.startswith("cite-footer", i)]
        self.assertTrue(rendered)
        self.assertGreater(rendered[-1],
                           code.index("for result in verification['results']:"),
                           "the full notice belongs below the rows")

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


class TypeScaleTests(unittest.TestCase):
    """Sizes are a legibility property, not a preference.

    The reference design was authored at chat width and sized for that
    container. In a full browser window the same numbers read small, and the
    text that suffered most was the criterion title and the quote — the two
    things a reviewer actually has to read.
    """

    FLOOR_PX = 12.0

    def sizes(self):
        """Every font-size in the file, in px, with its context."""
        code = APP.read_text()
        out = []
        for m in re.finditer(r"font-size:\s*([0-9.]+)(px|rem)", code):
            v = float(m.group(1))
            out.append((v if m.group(2) == "px" else v * 16,
                        code[max(0, m.start() - 90):m.start()].splitlines()[-1]))
        return out

    def rule_px(self, selector):
        code = APP.read_text()
        i = code.index(selector)
        m = re.search(r"font-size:\s*([0-9.]+)px", code[i:i + 200])
        self.assertIsNotNone(m, f"no font-size found for {selector}")
        return float(m.group(1))

    def test_nothing_is_smaller_than_twelve_pixels(self) -> None:
        small = [(px, ctx.strip()) for px, ctx in self.sizes()
                 if px < self.FLOOR_PX]
        self.assertEqual(
            small, [],
            "sizes below the 12px floor: "
            + "; ".join(f"{px:g}px near {ctx!r}" for px, ctx in small))

    def test_the_floor_check_reads_rem_as_well_as_px(self) -> None:
        """A `.68rem` slipped past an earlier eye because it is not spelled
        in pixels. The check converts rather than pattern-matching on px."""
        found = [px for px, _ in self.sizes()]
        self.assertTrue(found, "no sizes parsed; the check would be a no-op")

    def test_criterion_titles_are_sixteen_pixels(self) -> None:
        self.assertGreaterEqual(self.rule_px(".cite-req {{"), 16)

    def test_quotes_are_fifteen_pixels(self) -> None:
        self.assertGreaterEqual(self.rule_px(".cite-quote {{"), 15)

    def test_body_text_is_at_least_fifteen_pixels(self) -> None:
        """Base scale, set on the main container rather than per element."""
        code = APP.read_text()
        self.assertIn("section[data-testid='stMain']", code)
        i = code.index("section[data-testid='stMain'] {{")
        m = re.search(r"font-size:\s*([0-9.]+)px", code[i:i + 120])
        self.assertIsNotNone(m, "no base font size set on the main container")
        self.assertGreaterEqual(float(m.group(1)), 15)

    def test_the_requirement_is_larger_than_its_metadata(self) -> None:
        """Hierarchy, not just absolute size: the requirement must outrank
        the filename and passage count beneath it."""
        self.assertGreater(self.rule_px(".cite-req {{"),
                           self.rule_px(".cite-source {{"))
        self.assertGreater(self.rule_px(".cite-quote {{"),
                           self.rule_px(".cite-source {{"))


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


class IdentifierLeakTests(unittest.TestCase):
    """No internal handle reaches a user-facing label.

    Filenames, procedure ids, reason codes and correction kinds are how the
    pipeline addresses things. On screen they read as debug output, and a
    screen of debug output invites a reviewer to treat the record as a
    developer tool rather than something they are accountable for.

    Two things are deliberately exempt, and both are checked to still be
    present rather than merely allowed:

    - the **artifact filename** in the mode bar, which is an identifier a
      reviewer may need to quote
    - the **passage detail**, where the raw filename sits beside the document
      id, the character offsets and the content hash, because that is where
      provenance belongs

    The scan runs over rendered output rather than source, because the defect
    is about what reaches a screen. It renders with no API key, in recorded
    mode, which is the path a reader without credentials sees.
    """

    # Both cases. The first version matched lowercase only, and every enum
    # in this system — reason codes, statuses, failure kinds — is UPPER_SNAKE.
    # A mutation putting raw reason codes on the row survived because of it.
    SNAKE = re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b")
    ISO_FILE = re.compile(r"\b\d{4}-\d{2}-\d{2}[_-][A-Za-z0-9_]+")

    @classmethod
    def model_prose(cls) -> set:
        """Every explanation string in any committed artifact.

        Model-written explanations reference the status vocabulary — one says
        "NOT_MET" in the course of reasoning about it. That is the model's
        own words, and rewriting them to look tidier would misrepresent
        output the rest of this project treats as evidence. It is exempted as
        *content*, matched verbatim, rather than by excluding the region it
        renders in, so a genuine label leaking into the same block is still
        caught.
        """
        import json
        out = set()
        for path in (PROJECT_ROOT / "runs").glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            for case in data.get("cases", []):
                for section in ("extraction", "verification"):
                    for r in case.get(section, {}).get("results", []):
                        if r.get("explanation"):
                            out.add(" ".join(r["explanation"].split()))
        return out

    @classmethod
    def setUpClass(cls):
        import os
        os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            from streamlit.testing.v1 import AppTest
        except ImportError:                                  # pragma: no cover
            raise unittest.SkipTest("streamlit not installed")
        cls.at = AppTest.from_file(str(APP), default_timeout=180).run()
        if cls.at.exception:
            raise AssertionError(f"app raised: {cls.at.exception[0].value}")

    # Regions where an internal handle is the point, not a leak. Each is
    # confirmed to still contain what it was exempted for, by
    # `test_the_exemptions_are_actually_still_present`. An exemption nobody
    # checks is a hole.
    EXEMPT = (
        "class='cite-bar'",   # mode bar: the artifact filename, quotable
        "sha256",             # passage detail: raw filename, id, offsets, hash
        "procedure id",       # run provenance expander
        "<mark",              # the source excerpt is document content
    )

    def visible_labels(self) -> list[str]:
        """Rendered text a reviewer reads, excluding the exempt regions.

        Captions are collected separately from markdown by `AppTest`. An
        earlier version of this scan read only `at.markdown` and therefore
        never looked at the passage detail at all — it excluded a region it
        was not reading, and its exemption check failed for the same reason.
        """
        blocks = [m.value for m in self.at.markdown]
        blocks += [c.value for c in self.at.caption]
        prose = self.model_prose()
        out = []
        for block in blocks:
            if "<style>" in block or any(x in block for x in self.EXEMPT):
                continue
            if " ".join(block.split()) in prose:
                continue
            out.append(re.sub(r"<[^>]+>", " ", block))
        out += [e.label for e in self.at.expander]
        for widget in list(self.at.selectbox) + list(self.at.radio):
            out.append(str(widget.label))
            for opt in (widget.options or []):
                out.append(str(opt))
        return out

    def test_the_scan_sees_something(self) -> None:
        """Guard against the whole check quietly measuring nothing."""
        labels = self.visible_labels()
        self.assertGreater(len(labels), 20, "too few labels; scan is a no-op")
        self.assertTrue(any("Case " in l for l in labels))

    def test_no_snake_case_identifier_is_displayed(self) -> None:
        hits = []
        for label in self.visible_labels():
            for m in self.SNAKE.finditer(label):
                hits.append((m.group(0), label.strip()[:90]))
        self.assertEqual(
            hits, [],
            "snake_case identifiers on screen: "
            + "; ".join(f"{tok!r} in {ctx!r}" for tok, ctx in hits[:6]))

    def test_no_raw_iso_filename_is_displayed(self) -> None:
        hits = []
        for label in self.visible_labels():
            for m in self.ISO_FILE.finditer(label):
                hits.append((m.group(0), label.strip()[:90]))
        self.assertEqual(
            hits, [],
            "ISO-stamped filenames on screen: "
            + "; ".join(f"{tok!r} in {ctx!r}" for tok, ctx in hits[:6]))

    def test_the_exemptions_are_actually_still_present(self) -> None:
        """Excluding a region is only defensible if the thing it was excluded
        for is really there. Otherwise the exclusion hides a gap instead of
        permitting a deliberate choice.

        This failed on its first run for exactly that reason: it looked for
        the passage detail in `at.markdown`, where captions do not appear,
        and concluded nothing was rendered.
        """
        blocks = [m.value for m in self.at.markdown if "<style>" not in m.value]
        captions = [c.value for c in self.at.caption]

        bar = [b for b in blocks if "class='cite-bar'" in b]
        self.assertTrue(bar, "no mode bar rendered")
        self.assertRegex(" ".join(bar), r"\d{8}T\d{6}Z.*\.json",
                         "the mode bar must still carry the artifact filename")

        detail = [c for c in captions if "sha256" in c]
        self.assertTrue(detail, "no passage detail rendered")
        self.assertTrue(any(self.ISO_FILE.search(c) for c in detail),
                        "the passage detail must still carry the raw filename")
        self.assertTrue(any("characters " in c for c in detail),
                        "the passage detail must still carry the offsets")

        prov = [b for b in blocks if "procedure id" in b]
        self.assertTrue(prov, "no run provenance block rendered")
        self.assertTrue(any(self.SNAKE.search(b) for b in prov),
                        "the provenance expander must still carry the "
                        "procedure id")

        self.assertTrue(self.model_prose(),
                        "no explanations found in any artifact; the "
                        "model-prose exemption would be silently empty")

    def test_document_labels_are_readable(self) -> None:
        """The formatter itself, on real corpus filenames."""
        import importlib.util
        spec = importlib.util.spec_from_file_location("cite_app", APP)
        # Read the function out of the AST rather than importing the module,
        # which would execute Streamlit calls.
        tree = ast.parse(APP.read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.Assign, ast.Import)):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<app>", "exec"), ns)
                except Exception:
                    pass
        label = ns["document_label"]
        self.assertEqual(label("2026-07-30_consultant_letter.txt"),
                         "Consultant letter, 30 July 2026")
        self.assertEqual(label("2026-04-22_mri_lumbar_structured_report.txt"),
                         "MRI lumbar structured report, 22 April 2026")
        self.assertEqual(label("INJ-01_patient_portal_message.txt"),
                         "Patient portal message (INJ-01)")
        # Initialisms must not be sentence-cased into words.
        self.assertIn("PT ", label("2026-08-20_pt_progress_note.txt"))

    def test_document_labels_do_not_collide_within_a_packet(self) -> None:
        """Two documents rendering the same name would be worse than the raw
        filenames, because a reviewer could not tell them apart at all."""
        import json
        from collections import Counter
        from um_evidence import ingest_case
        tree = ast.parse(APP.read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.Assign, ast.Import)):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<app>", "exec"), ns)
                except Exception:
                    pass
        label = ns["document_label"]
        cases = json.loads((PROJECT_ROOT / "corpus" / "labels.json").read_text())
        for case in cases["cases"]:
            packet = ingest_case(case["case_id"],
                                 PROJECT_ROOT / "corpus" / "cases")
            names = [label(d.filename) for d in packet.documents]
            dupes = [n for n, c in Counter(names).items() if c > 1]
            self.assertEqual(dupes, [],
                             f"{case['case_id']} has colliding labels: {dupes}")
