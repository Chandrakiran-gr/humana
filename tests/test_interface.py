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
        self.assertIn("What happened", code)
        self.assertIn("processing_sentence(result)", code)
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
        self.assertIn("What happened", window)
        self.assertIn("processing_sentence(result)", window,
                      "the row must say what happened, in words")
        # The raw pipeline string must not be back on the row.
        self.assertNotIn("result.get('detail')", window,
                         "attempt counts, token limits, stop reasons and "
                         "remediation notes belong under run details")

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
        loop = code[code.index("for index, result in enumerate"):]
        self.assertIn("lead = evidence[0]", loop)
        self.assertIn("further passage", loop)
        self.assertLess(loop.index("lead = evidence[0]"),
                        loop.index("st.expander"),
                        "the inline passage must precede the expanders")

    def test_a_row_opens_one_expander_not_one_per_passage(self) -> None:
        """Nine passages used to mean nine collapsed bars stacked under one
        requirement, which is a wall whether or not it is collapsed."""
        code = code_only(APP)
        loop = code[code.index("for index, result in enumerate"):]
        inner = loop[loop.index("for item in items:"):]
        self.assertNotIn("st.expander", inner.split("elif")[0],
                         "passages must not each open their own expander")
        self.assertIn("View all {n} passage", loop)

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
        # The raw handle stays reachable in the passage card's provenance
        # disclosure. Found through `render_calls`, which skips the
        # stylesheet: indexing the source for "cite-prov" lands on the CSS
        # rule that defines the class, which is not evidence that anything
        # renders it. That mistake has now been made four times in this
        # file, once per class name introduced.
        calls = render_calls("cite-prov")
        self.assertTrue(calls, "nothing renders the passage provenance")
        for handle in ("doc.filename", "doc_id", "sha"):
            self.assertIn(handle, calls[0],
                          f"{handle} must remain in the passage provenance")

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

    def test_the_header_names_the_application_in_the_main_column(self) -> None:
        """A reviewer looking at a screenshot or a shared window should not
        have to find the sidebar to know what they are looking at.

        `st.title` stays out: it dominated the rows, which are the thing
        being read. The masthead is a restrained 22px instead.
        """
        code = code_only(APP)
        self.assertNotIn("st.title(", code)
        tree = ast.parse(APP.read_text())
        fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                   and n.name == "header_bar"), None)
        self.assertIsNotNone(fn, "no header_bar function")
        body = ast.unparse(fn)
        self.assertIn("APP_NAME", body)
        self.assertIn("APP_SUBTITLE", body)
        self.assertIn("cite-pill", body, "the mode belongs in the header")
        css = APP.read_text()
        i = css.index(".cite-brand-name {{")
        size = re.search(r"font-size:(\d+(?:\.\d+)?)px", css[i:i + 120])
        self.assertIsNotNone(size)
        self.assertLessEqual(float(size.group(1)), 22,
                             "the name must not dominate the rows")

    def test_the_name_is_rendered_once_not_in_both_columns(self) -> None:
        """The wordmark used to appear in the sidebar as well, so the name and
        tagline were on screen twice."""
        tree = ast.parse(APP.read_text())
        uses = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
                and n.id == "APP_NAME" and isinstance(n.ctx, ast.Load)]
        self.assertEqual(len(uses), 2,
                         f"APP_NAME is used {len(uses)} times; expected the "
                         f"page title and the header, and nothing else")
        sidebar = [ast.unparse(n) for n in ast.walk(tree)
                   if isinstance(n, ast.With)
                   and "st.sidebar" in ast.unparse(n.items[0])]
        self.assertTrue(sidebar, "no sidebar block found")
        self.assertNotIn("APP_NAME", sidebar[0])
        self.assertNotIn("cite-wordmark", sidebar[0])

    def test_the_case_is_labelled_fields_not_a_metadata_string(self) -> None:
        """The case and procedure are what the reviewer is looking at.

        Criteria version, configuration and document count read as debug
        output beside them, so they moved into the provenance expander.
        """
        code = code_only(APP)
        band = render_calls("cite-band")
        self.assertTrue(band, "the case band is not rendered")
        head = band[0]
        for label in ("'Case'", "'Requested procedure'", "'Reviewing against'"):
            self.assertIn(label, head, f"{label} must be a labelled field")
        self.assertIn("procedure_name", head,
                      "the procedure's proper name, not its id")
        for provenance in ("criteria_set.version", "criteria_set.cpt",
                           "configuration"):
            self.assertNotIn(provenance, head,
                             f"{provenance} belongs behind run details, not "
                             f"on the case band")

    def test_the_procedure_uses_its_proper_name_not_its_id(self) -> None:
        code = code_only(APP)
        self.assertIn("criteria_set.procedure_name", code)
        self.assertNotIn("procedure_id.replace", code,
                         "derive nothing from the id; the set carries a name")

    def test_the_header_is_the_first_thing_in_the_main_column(self) -> None:
        """It must precede the case band, the summary and the rows."""
        # Positions are taken after the stylesheet, which mentions every
        # class name and would otherwise "precede" everything.
        code = code_only(APP)
        body = code[code.index("st.markdown(header_bar("):]
        for later in ("cite-band", "summary_strip(verification",
                      "for index, result in enumerate"):
            self.assertIn(later, body,
                          f"the header must come before {later}")

    def test_no_full_width_mode_bar_remains(self) -> None:
        """The mode is a pill in the header, not a band of its own."""
        code = code_only(APP)
        self.assertNotIn("cite-bar'><span>", code)
        # Through the function that renders it. `assertIn("cite-pill", code)`
        # passed on the stylesheet rule that defines the class, so the pill
        # could have stopped rendering entirely and this would not have
        # noticed.
        tree = ast.parse(APP.read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "header_bar")
        self.assertIn("cite-pill", ast.unparse(fn))

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
        self.assertTrue(render_calls("cite-strip"),
                        "nothing renders the notice strip")
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

    def test_every_early_exit_renders_the_notice_first(self) -> None:
        """`st.stop()` ends the script, so every path that stops must render
        the notice immediately before it.

        Checked as the preceding sibling statement, not by line order. Two
        earlier versions of this test were satisfied by any `notice_footer()`
        call anywhere above the stop, which meant the first one vouched for
        all three paths; and before that, by the stylesheet, because it
        defines `.cite-footer` and is itself an `st.markdown` call. Being
        earlier in the file is not being on the path.
        """
        tree = ast.parse(APP.read_text())

        def is_stop(node):
            return (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "stop")

        def is_notice(node):
            return (isinstance(node, ast.Expr)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == "notice_footer")

        found = 0
        for parent in ast.walk(tree):
            body = getattr(parent, "body", None)
            for block in (body, getattr(parent, "orelse", None)):
                if not isinstance(block, list):
                    continue
                for i, node in enumerate(block):
                    if not is_stop(node):
                        continue
                    found += 1
                    self.assertTrue(
                        i > 0 and is_notice(block[i - 1]),
                        f"st.stop() at line {node.lineno} is not immediately "
                        f"preceded by notice_footer(); that path exits with "
                        f"no constraint notice on screen")
        self.assertGreaterEqual(found, 3,
                                f"expected at least 3 early exits, found "
                                f"{found}; the scan is missing some")

    def test_the_notice_no_longer_occupies_the_top_of_the_column(self) -> None:
        """Six lines of legal text was the first thing a reviewer read, in
        the most valuable space on the page. A one-line strip stands in for
        it; the full text sits in run details and in the footer."""
        code = code_only(APP)
        self.assertLess(code.index("st.markdown(header_bar("),
                        code.index("cite-strip'><span>"),
                        "the header must precede the notice strip")
        # The full text must not be rendered above the evidence map.
        first_full = code.index("FULL_NOTICE =")
        rendered = [i for i in range(len(code))
                    if code.startswith("cite-footer", i)]
        self.assertTrue(rendered)
        self.assertGreater(rendered[-1],
                           code.index("for index, result in enumerate"),
                           "the full notice belongs below the rows")

    def test_the_mode_pill_states_every_mode(self) -> None:
        code = code_only(APP)
        for kind in ("Recorded run", "Live run · in progress", "Live run"):
            self.assertIn(kind, code)

    def test_the_header_is_one_line(self) -> None:
        code = APP.read_text()
        i = code.index(".cite-bar {{")
        self.assertIn("justify-content:space-between", code[i:i + 260])
        self.assertIn("align-items:center", code[i:i + 260])

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
        tree = ast.parse(code)
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "header_bar")
        body = ast.unparse(fn)
        self.assertIn("NAVY", body,
                      "the recorded pill must take the chrome colour")
        # The live pill uses the MET colour from the palette, which is a deep
        # teal at hue 165 rather than a success green. That is the reference
        # design's choice and it clears the green band below.
        colours = [re.search(r'NAVY = "(#[0-9a-fA-F]{6})"', code).group(1),
                   re.search(r'"MET": \([^)]*?"(#[0-9a-fA-F]{6})"',
                             code).group(1)]
        self.assertTrue(colours, "no colours found; the test would be a no-op")
        judged = 0
        for colour in colours:
            hue, sat, _ = hsv(colour)
            if sat < 0.12:
                continue
            judged += 1
            # One definition of the green band, shared with the status
            # palette. Two copies is how the numbers drift: this one still
            # read 75-165 after the palette narrowed it to 90-155, and
            # rejected the reference design's own teal at hue 165.
            low, high = StatusPaletteTests.GREEN_BAND
            self.assertFalse(low <= hue <= high,
                             f"the mode pill uses {colour} at hue {hue:.0f}, "
                             f"inside the {low}-{high} green band")
        self.assertTrue(judged, "every bar colour was grey; nothing was checked")

    def test_the_live_bar_reports_progress(self) -> None:
        code = code_only(APP)
        self.assertIn("requirements complete", code)
        self.assertIn("progress=(done, len(state))", code,
                      "the live bar must show how far the run has got")

    def test_the_standing_summary_precedes_the_rows(self) -> None:
        code = code_only(APP)
        self.assertIn("def summary_strip", code)
        self.assertLess(code.index("summary_strip(verification"),
                        code.index("for index, result in enumerate"),
                        "the summary must come before the rows it summarises")

    def test_the_standing_summary_is_labelled_and_counts_requirements(self) -> None:
        """A row of numbers with no heading makes a reviewer guess what is
        being counted."""
        code = code_only(APP)
        self.assertIn("Where the", code)
        self.assertIn("requirement", code)

    def test_the_summary_and_the_rows_use_the_same_wording(self) -> None:
        """Short forms here and Section 4 wording on the chips left the two
        describing one status in two vocabularies."""
        code = code_only(APP)
        self.assertNotIn("TALLY_LABEL", code,
                         "the summary must use the Section 4 wording that "
                         "the chips use")
        tree = ast.parse(APP.read_text())
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "summary_strip")
        self.assertIn("DISPLAY[key]", ast.unparse(fn))

    def test_the_summary_strip_shows_no_aggregate(self) -> None:
        """Counts by status, never a single number over a case. One number
        summarising a case is the score this system does not produce."""
        # Located through the AST. A string slice from one `def` to the next
        # broke the moment a function was inserted between them, and swept a
        # neighbour's parameter named `total` into the range.
        tree = ast.parse(code_only(APP))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == "summary_strip")
        block = ast.unparse(fn).lower()
        for banned in ("total", "sum(", "score", "overall"):
            self.assertNotIn(banned, block,
                             f"summary_strip computes {banned!r}; one number "
                             f"over a case is the score this system does not "
                             f"produce")

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
        loop = code[code.index("for index, result in enumerate"):]
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
        # The header is unconditional: rendered at module scope before the
        # mode branch, so no path can produce a page without it. It used to
        # render after the branch, which left live mode before a run — the
        # first state a viewer sees after switching — with no application
        # name and no mode anywhere on screen.
        tree = ast.parse(APP.read_text())
        top_level = [n for n in tree.body
                     if isinstance(n, ast.Expr) and "header_bar(" in ast.unparse(n)]
        self.assertEqual(len(top_level), 1,
                         "the header must render exactly once, at module "
                         "scope, outside every branch")
        code = code_only(APP)
        self.assertIn("'Live run' if live_mode else 'Recorded run'", code,
                      "the header must state which mode it is in")

    def test_recorded_mode_says_nothing_is_being_executed(self) -> None:
        """The error this prevents is a recorded run read as a live one, in
        front of people who cannot check. The pill names the mode; the run
        note under `run details` says what that means."""
        code = code_only(APP)
        self.assertIn("Recorded run", code)
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
        "cite-brand-name",    # header: name, tagline, mode pill
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

        header = [b for b in blocks if "cite-brand-name" in b]
        self.assertTrue(header, "no header rendered")
        self.assertIn("cite-pill", header[0], "the header must state the mode")

        # The artifact filename is an identifier a reviewer may need to
        # quote, so it stays verbatim. It used to sit in a full-width mode
        # bar; with the mode reduced to a pill it lives under run details,
        # which is where the rest of the run's provenance is.
        runs = [b for b in blocks if "procedure id" in b]
        self.assertTrue(runs, "no run details block rendered")
        self.assertRegex(" ".join(runs), r"\d{8}T\d{6}Z.*\.json",
                         "run details must still carry the artifact filename "
                         "verbatim")

        # The passage detail is a card in markdown now, not a caption. It
        # carries the raw filename, the document id and the hash behind a
        # disclosure in its footer, and the character range beside them.
        detail = [b for b in blocks + captions if "sha256" in b]
        self.assertTrue(detail, "no passage detail rendered")
        self.assertTrue(any(self.ISO_FILE.search(c) for c in detail),
                        "the passage detail must still carry the raw filename")
        self.assertTrue(any("Characters " in c for c in detail),
                        "the passage detail must still carry the offsets")

        self.assertTrue(any(self.SNAKE.search(b) for b in runs),
                        "run details must still carry the procedure id")

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


class ClinicalLayoutTests(unittest.TestCase):
    """The layout's organising principle: every value carries a label.

    A reviewer should never have to infer what she is looking at. "LF-201" is
    meaningless without "Case" above it, and a row of counts is meaningless
    without "Where the 9 requirements stand".
    """

    def app_ns(self):
        """The module's plain functions, without executing Streamlit calls."""
        tree = ast.parse(APP.read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.Assign, ast.Import)):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<app>", "exec"), ns)
                except Exception:
                    pass
        return ns

    def test_every_row_field_carries_a_label(self) -> None:
        code = code_only(APP)
        loop = code[code.index("for index, result in enumerate"):]
        for label in ("Requirement {position} of", "'Result'",
                      "Evidence located in the record"):
            self.assertIn(label.strip("'"), loop,
                          f"missing row label: {label}")

    def test_the_why_heading_names_the_kind_of_problem(self) -> None:
        """"Why this needs review" and "Why this is unresolved" are different
        questions, and a processing failure is not a clinical question."""
        code = code_only(APP)
        for heading in ("Why this needs review", "Why this is unresolved",
                        "What happened"):
            self.assertIn(heading, code)

    def test_the_position_counts_from_one(self) -> None:
        """"Requirement 0 of 9" would be a bug a reviewer could not explain."""
        code = code_only(APP)
        self.assertIn("position = index + 1", code)

    def test_a_processing_failure_says_it_was_not_assessed(self) -> None:
        """Slate, off the clinical scale, and explicit that the requirement
        carries no result rather than a poor one."""
        code = code_only(APP)
        self.assertIn("was not assessed", code)
        self.assertIn("never assessed", code,
                      "an unread record must say the requirement was never "
                      "assessed, not that a result was cut off")
        display = display_map()
        self.assertIn("No clinical result", display[None][0])

    def test_the_source_line_is_prefixed_and_states_verification(self) -> None:
        code = code_only(APP)
        self.assertIn("Source: ", code)
        self.assertIn("all verified against source", code)
        self.assertIn("could not be verified against", code,
                      "an unverified citation must say so in the same place")

    def test_the_expander_offers_to_view_the_passages(self) -> None:
        code = code_only(APP)
        self.assertIn("View all {n} passage", code)
        self.assertNotIn("and sources", code)

    # --- the alert, both branches -----------------------------------------

    def test_no_alert_when_every_document_was_read(self) -> None:
        self.assertEqual(self.app_ns()["unreadable_notice"](5, 5), "")
        self.assertEqual(self.app_ns()["unreadable_notice"](1, 1), "")

    def test_an_alert_when_a_document_could_not_be_read(self) -> None:
        notice = self.app_ns()["unreadable_notice"](5, 4)
        self.assertIn("1 of 5 submitted document could not be read", notice)
        self.assertIn("not a complete evidence review", notice)
        self.assertIn("cite-alert", notice)

    def test_the_alert_agrees_in_number(self) -> None:
        ns = self.app_ns()
        self.assertIn("2 of 5 submitted documents", ns["unreadable_notice"](5, 3))
        self.assertIn("1 of 5 submitted document could", ns["unreadable_notice"](5, 4))

    def test_the_alert_is_a_statement_not_a_count_in_a_metadata_line(self) -> None:
        """The readable-document count used to sit in the case metadata
        string, where it read as a number about the run rather than a warning
        about the review. It is now only rendered when it is a problem."""
        code = code_only(APP)
        band = render_calls("cite-band")
        self.assertTrue(band)
        self.assertNotIn("documents read", band[0],
                         "the document count belongs behind run details")
        self.assertIn("if notice:", code,
                      "the alert must be conditional")

    def test_cpt_and_criteria_version_are_off_the_surface(self) -> None:
        band = render_calls("cite-band")
        self.assertTrue(band)
        for hidden in ("cpt", "criteria_set.version"):
            self.assertNotIn(hidden, band[0].lower().replace("criteria_set.version",
                                                             "criteria_set.version"),
                             f"{hidden} belongs behind run details")


class StreamlitChromeTests(unittest.TestCase):
    """Streamlit's own controls are development affordances.

    The Deploy button and the three-dot menu invite a click that does
    something nobody intended, in front of an audience. `toolbarMode` in
    config.toml removes most of them; it still renders the toolbar
    container, which leaves an empty strip across the top of the page, so
    the CSS collapses that too.

    Verified in a real browser as well as here: the rendered page was
    measured with Playwright in all four states — recorded, recorded with an
    injected fault, live before a run and live after one — and in every one
    the header measured zero height, no toolbar, Deploy or menu element
    existed, and the first line of text sat at y=88 with nothing above it.
    """

    CONFIG = PROJECT_ROOT / ".streamlit" / "config.toml"

    def test_the_toolbar_mode_is_pinned(self) -> None:
        text = self.CONFIG.read_text()
        self.assertIn("[client]", text)
        self.assertRegex(text, r'toolbarMode\s*=\s*"(minimal|viewer)"')

    def test_the_development_chrome_is_hidden(self) -> None:
        css = APP.read_text()
        for testid in ("stToolbar", "stAppDeployButton", "stMainMenu",
                       "stStatusWidget"):
            self.assertIn(f"data-testid='{testid}'", css,
                          f"{testid} is not hidden")
        i = css.index("[data-testid='stToolbar']")
        self.assertIn("display:none", css[i:i + 320])

    def test_the_empty_toolbar_strip_is_collapsed(self) -> None:
        """`toolbarMode` removes the buttons and leaves the container, which
        renders as a blank band across the top of every screen."""
        css = APP.read_text()
        i = css.index("[data-testid='stHeader']")
        rule = css[i:i + 260]
        # Declarations, not substrings. `assertIn("height:0", ...)` matched
        # the "height:0" inside `min-height:0`, so a mutation that deleted
        # the actual height declaration and left the strip on screen passed.
        # The block belonging to this selector: the first one after it, not
        # the last in the window, which is a different rule entirely.
        body = rule.split("{{", 1)[1].split("}}", 1)[0]
        decls = {d.split(":", 1)[0].strip(): d.split(":", 1)[1].strip()
                 for d in body.split(";") if ":" in d}
        self.assertIn("height", decls,
                      "the header keeps its default height; the empty "
                      "toolbar strip will still show")
        self.assertTrue(decls["height"].startswith("0"),
                        f"header height is {decls['height']!r}, not zero")
        self.assertIn("background", decls)
        self.assertTrue(decls["background"].startswith("transparent"))

    def test_the_sidebar_can_still_be_reopened(self) -> None:
        """`stExpandSidebarButton` lives inside the header. Collapsing the
        header without exempting it would leave a viewer who hides the
        sidebar with no way to bring it back."""
        css = APP.read_text()
        self.assertIn("[data-testid='stExpandSidebarButton']", css,
                      "the sidebar-expand button is not exempted from the "
                      "collapsed header; a viewer who hides the sidebar "
                      "could not bring it back")
        i = css.index("[data-testid='stExpandSidebarButton']")
        self.assertIn("display:flex", css[i:i + 120])
        # The header must not blanket-hide its children.
        self.assertNotIn("[data-testid='stHeader'] > * {{ display:none", css)

    def test_the_top_padding_matches_whether_the_header_reserves_space(self) -> None:
        """The invariant is the relationship, not a number.

        The overlap this prevents: the opening line of live mode rendered
        underneath the header and was cut off. A fixed minimum was the wrong
        way to express it — once the header collapsed to zero height, a
        3rem floor only reintroduced the gap above the masthead. What has to
        hold is that the padding clears whatever the header actually
        reserves.
        """
        css = APP.read_text()
        i = css.index(".block-container {{")
        m = re.search(r"padding-top:([0-9.]+)rem", css[i:i + 120])
        self.assertIsNotNone(m, "no top padding set on the main container")
        padding = float(m.group(1))
        self.assertGreater(padding, 0, "content would touch the viewport edge")

        j = css.index("[data-testid='stHeader']")
        body = css[j:j + 260].split("{{", 1)[1].split("}}", 1)[0]
        decls = {d.split(":", 1)[0].strip(): d.split(":", 1)[1].strip()
                 for d in body.split(";") if ":" in d}
        collapsed = decls.get("height", "").startswith("0")
        if collapsed:
            self.assertLessEqual(
                padding, 2.0,
                "the header reserves no space, so this padding is the gap "
                "above the masthead rather than clearance")
        else:
            self.assertGreaterEqual(
                padding, 6.0,
                "the header reserves its default height; content will render "
                "underneath it")

    def test_the_sidebar_labels_are_not_doubled(self) -> None:
        """Each sidebar group is named by its subheader. Streamlit's own
        widget label then repeated it directly underneath."""
        code = code_only(APP)
        i = code.index("with st.sidebar:")
        block = code[i:code.index("criteria_set = load_criteria")]
        self.assertEqual(block.count("label_visibility='collapsed'"), 4,
                         "every sidebar widget whose group already carries a "
                         "heading must collapse its own label")


class PassageCardTests(unittest.TestCase):
    """The expanded passage view.

    It was a monospace block under a header line that crammed the document
    name, filename, document id, character range and hash into one string.
    That reads as a log dump, and clinical prose set in monospace reads as
    machine output rather than as a record someone wrote.

    Each passage is now a card: the document as a heading, the excerpt in
    proportional type with its surroundings dimmed, and the machine detail
    in a footer behind a disclosure. Verified in Chrome as well as here —
    thirteen cards rendered, the excerpt computed to a proportional family,
    and the disclosure revealed filename, id and full hash.
    """

    def css(self):
        return APP.read_text()

    def rule_px(self, selector):
        css = self.css()
        i = css.index(selector)
        m = re.search(r"font-size:\s*([0-9.]+)px", css[i:i + 200])
        self.assertIsNotNone(m, f"no font-size for {selector}")
        return float(m.group(1))

    def test_no_monospace_on_clinical_prose(self) -> None:
        """The excerpt is the patient's record, not a stack trace."""
        code = code_only(APP)
        loop = code[code.index("for index, result in enumerate"):]
        self.assertNotIn("monospace", loop,
                         "the passage excerpt must not be set in monospace")
        css = self.css()
        i = css.index(".cite-excerpt {{")
        self.assertNotIn("monospace", css[i:i + 200])

    def test_each_passage_is_a_card(self) -> None:
        calls = render_calls("cite-doc-head")
        self.assertTrue(calls, "nothing renders a passage card")
        card = calls[0]
        for part in ("cite-doc-name", "cite-doc-date", "cite-excerpt",
                     "cite-doc-foot"):
            self.assertIn(part, " ".join(render_calls(part)) or "",
                          f"the card is missing {part}")

    def test_the_document_name_is_a_heading_not_a_metadata_string(self) -> None:
        """The name, the date and the machine detail are three different
        things in three places, not one concatenated line."""
        calls = " ".join(render_calls("cite-doc-head"))
        self.assertIn("document_parts", code_only(APP))
        self.assertIn("cite-doc-name", calls)
        # The filename must not be in the card heading.
        head = calls[calls.index("cite-doc-head"):calls.index("cite-excerpt")]
        self.assertNotIn("doc.filename", head,
                         "the raw filename belongs in the footer disclosure")

    def test_repeated_documents_number_their_passages(self) -> None:
        """Four cards all headed "Flexion extension series" tell a reviewer
        nothing about which is which."""
        code = code_only(APP)
        self.assertIn("passage {seen[doc_id]} of {per_doc[doc_id]}", code)
        self.assertIn("from this document", code)
        self.assertIn("if per_doc[doc_id] > 1:", code,
                      "a document contributing one passage must not be "
                      "numbered")

    def test_file_and_hash_sit_behind_a_disclosure_in_the_footer(self) -> None:
        # Through `render_calls`, not `code.index`: the first "cite-doc-foot"
        # in the file is the CSS rule that defines the class. That mistake
        # has now been made five times in this file, once per class name
        # introduced, which is why the helper exists.
        calls = [c for c in render_calls("cite-doc-foot")
                 if "details" in c]
        self.assertTrue(calls, "nothing renders the footer disclosure")
        foot = calls[0]
        self.assertIn("<details><summary>file and hash", foot)
        for handle in ("doc.filename", "doc_id", "sha"):
            self.assertIn(handle, foot, f"{handle} must be in the disclosure")
        self.assertIn("Characters ", foot, "the offsets stay on the footer")

    def test_an_unverifiable_quote_shows_no_source_context(self) -> None:
        """It resolved to no place in the document, so there is no context
        to show. An excerpt would imply a location it does not have."""
        # Bounded at the `continue` that ends the branch. A fixed character
        # window overran into the verified branch below it, which does read
        # `doc.canonical`, and the test failed on correct code.
        code = code_only(APP)
        i = code.index("if not item['verified']:")
        block = code[i:code.index("continue", i)]
        self.assertIn("No matching span in this document", block)
        self.assertIn("could not be verified against source", block)
        self.assertNotIn("doc.canonical", block,
                         "an unverified quote must not render source context")

    # --- the v3 type scale ------------------------------------------------

    def test_the_type_scale_matches_the_reference(self) -> None:
        for selector, expected in ((".cite-req {{", 17.0),
                                   (".cite-quote {{", 16.5),
                                   (".cite-excerpt {{", 15.5),
                                   (".cite-doc-name {{", 15.0),
                                   (".cite-label {{", 12.0)):
            self.assertEqual(self.rule_px(selector), expected,
                             f"{selector} is not the reference size")

    def test_the_base_is_sixteen_pixels(self) -> None:
        css = self.css()
        i = css.index("section[data-testid='stMain'] {{")
        m = re.search(r"font-size:\s*([0-9.]+)px", css[i:i + 120])
        self.assertEqual(float(m.group(1)), 16.0)

    def test_the_injected_stylesheet_does_not_occupy_space(self) -> None:
        """Streamlit wraps the injected `<style>` in an element container
        that contributes height and a flex gap. That was the whitespace
        above the masthead: the padding was already small, but an invisible
        element sat in front of it."""
        css = self.css()
        self.assertIn("stElementContainer']:has(", css)
        i = css.index("stElementContainer']:has(")
        self.assertIn("display:none", css[i:i + 320])


class TestsAboutTheseTestsTests(unittest.TestCase):
    """A check on this file, because one mistake keeps recurring in it.

    Five times now a test has looked up a CSS class name in the whole source
    and matched the stylesheet rule that *defines* the class rather than
    anything that *renders* it. Every time, the test passed while the thing
    it described was absent — deleting the masthead, dropping the notice out
    of the footer, leaving the toolbar strip on screen, and twice more.

    The failure is invisible by construction: the assertion is true, just
    not about what the author meant. Attention has not stopped it, so this
    check does.

    **What counts as ambiguous.** A needle that is a bare class name, with
    or without a leading dot, can match both a CSS rule and a render. Those
    must go through `render_calls`, which skips the stylesheet, or search a
    narrowed scope such as an unparsed function body. A needle carrying
    markup (`cite-bar'><span>`) can only match a render, and one carrying
    `{{` can only match a rule; both are unambiguous and are allowed.
    """

    # Names that hold the entire source of app.py.
    WHOLE_FILE_NAMES = {"code", "css", "source", "src"}
    BARE_CLASS = re.compile(r"^\.?cite-[a-z0-9_-]+$")
    SEARCHES = {"index", "count", "find"}
    ASSERTIONS = {"assertIn", "assertNotIn"}

    def _is_whole_file(self, node) -> bool:
        if isinstance(node, ast.Name) and node.id in self.WHOLE_FILE_NAMES:
            return True
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name) and f.id == "code_only":
                return True
            if isinstance(f, ast.Attribute) and f.attr == "read_text":
                return True
        return False

    def violations(self, tree) -> list:
        out = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not isinstance(f, ast.Attribute):
                continue
            needle = haystack = None
            if f.attr in self.SEARCHES and node.args:
                needle, haystack = node.args[0], f.value
            elif f.attr in self.ASSERTIONS and len(node.args) >= 2:
                needle, haystack = node.args[0], node.args[1]
            if needle is None:
                continue
            if not (isinstance(needle, ast.Constant)
                    and isinstance(needle.value, str)):
                continue
            if not self.BARE_CLASS.match(needle.value.strip()):
                continue
            if self._is_whole_file(haystack):
                out.append((node.lineno, f.attr, needle.value))
        return out

    def test_no_test_searches_the_whole_source_for_a_bare_class_name(self) -> None:
        tree = ast.parse(Path(__file__).read_text())
        found = self.violations(tree)
        self.assertEqual(
            found, [],
            "these lookups will match the stylesheet rule that defines the "
            "class, not the code that renders it — use render_calls() or "
            "narrow the scope: "
            + "; ".join(f"line {ln}: {call}({needle!r})"
                        for ln, call, needle in found))

    def test_the_check_catches_the_mistake_it_describes(self) -> None:
        """The check must fail on a real instance of the defect.

        Both shapes it has actually taken are exercised: an `assertIn`
        against the whole source, and an `index` lookup used to slice a
        window out of it.
        """
        bad = ast.parse(
            "def t(self):\n"
            "    code = code_only(APP)\n"
            "    self.assertIn('cite-title', code)\n"
            "    i = code.index('cite-doc-foot')\n"
            "    css = APP.read_text()\n"
            "    j = css.index('.cite-band')\n")
        found = self.violations(bad)
        self.assertEqual(len(found), 3,
                         f"the check missed a known instance: {found}")

    def test_the_check_permits_the_unambiguous_forms(self) -> None:
        """It must not flag lookups that cannot hit the stylesheet, or CSS
        rule lookups that are meant to. A check that forbids the correct
        form too would just be turned off."""
        fine = ast.parse(
            "def t(self):\n"
            "    code = code_only(APP)\n"
            "    css = APP.read_text()\n"
            "    self.assertNotIn(\"cite-bar'><span>\", code)\n"      # markup
            "    i = css.index('.cite-req {{')\n"                     # a rule
            "    calls = render_calls('cite-band')\n"                 # helper
            "    self.assertIn('cite-pill', body)\n"                  # narrowed
            "    self.assertIn('cite-chip', ast.unparse(fn))\n")      # narrowed
        self.assertEqual(self.violations(fine), [])

    def test_render_calls_still_skips_the_stylesheet(self) -> None:
        """The helper this check points people to has to actually work."""
        self.assertTrue(render_calls("cite-band"),
                        "render_calls finds nothing; the advice is useless")
        for call in render_calls("cite-band"):
            self.assertNotIn("<style>", call)


class InternalDetailLeakTests(unittest.TestCase):
    """No internal artefact reaches a field a reviewer reads.

    Distinct from `IdentifierLeakTests`, which is about naming — filenames,
    procedure ids, snake_case handles. This is about *provenance and
    plumbing*: specification references, task numbers, raw exception text,
    enum names, run artifacts, and remediation advice addressed to whoever
    is debugging the pipeline.

    All of it was on screen at once. The injected-fault banner cited a spec
    section, named the artifact a truncation was replayed from, gave the
    date it was observed and the case it came from. A failed row printed
    the pipeline's own string: "1 attempt(s) failed; last: response
    truncated at the 16000 output-token limit (stop_reason max_tokens);
    raise max_tokens rather than retrying". A reviewer acts on none of it,
    and a screen carrying it reads as a developer tool rather than a record
    someone is accountable for.

    None of this is deleted. It is in the run artifact, and under `run
    details` where a technical reader will look.
    """

    SPEC = re.compile(r"Spec Section \d+|Section \d+ (?:requires|states)")
    TASK = re.compile(r"\bTask \d+\.\d+\b")
    ENUM = re.compile(r"\b[A-Z][A-Z_]{4,}\b")
    EXCEPTION = re.compile(r"\b\w*Error\b|Error code:|Traceback|stop_reason")
    REMEDIATION = re.compile(r"rather than retrying|raise max_tokens|"
                             r"attempt\(s\) failed")
    ARTIFACT = re.compile(r"\d{8}T\d{6}Z|\.json\b")

    def reviewer_strings(self):
        """String constants that reach a reviewer-facing field.

        Docstrings and comments are excluded: they are for whoever reads the
        source. Blocks that are deliberately technical — `run details`, the
        passage provenance disclosure — are excluded by the same rule that
        exempts them in `IdentifierLeakTests`, and are separately required
        below to still carry what they were exempted for.
        """
        tree = ast.parse(code_only(APP))
        out = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)):
                continue
            text = node.value
            if "<style>" in text or "cite-quiet" in text:
                continue                      # stylesheet, run details block
            if "procedure id" in text or "sha256" in text:
                continue                      # provenance, deliberately raw
            if len(text) < 12:
                continue                      # class names, format fragments
            out.append((node.lineno, text))
        return out

    def test_the_scan_sees_something(self) -> None:
        """Guard against every check below passing on an empty list."""
        found = self.reviewer_strings()
        self.assertGreater(len(found), 80,
                           f"only {len(found)} strings scanned; the sweep is "
                           f"looking at almost nothing")
        self.assertTrue(any("Synthetic demonstration" in t for _, t in found))

    def test_enum_names_are_covered_at_render_time(self) -> None:
        """Enums are not checked here.

        A DISPLAY key or a correction kind appears in this source as a dict
        key without ever reaching a screen, so scanning constants for
        UPPER_SNAKE would flag correct code. `IdentifierLeakTests` catches
        enums in the *rendered* page instead, which is both stricter and
        free of that false positive. This records the division so neither
        check is later assumed to cover the other.
        """
        self.assertTrue(hasattr(IdentifierLeakTests,
                                "test_no_snake_case_identifier_is_displayed"))
        self.assertRegex("MISSING_EVIDENCE", IdentifierLeakTests.SNAKE)

    def test_no_specification_reference_reaches_the_screen(self) -> None:
        bad = [(l, t) for l, t in self.reviewer_strings() if self.SPEC.search(t)]
        self.assertEqual(bad, [], f"specification cited to a reviewer: {bad}")

    def test_no_task_number_reaches_the_screen(self) -> None:
        bad = [(l, t) for l, t in self.reviewer_strings() if self.TASK.search(t)]
        self.assertEqual(bad, [], f"task number on screen: {bad}")

    def test_no_raw_exception_text_reaches_the_screen(self) -> None:
        bad = [(l, t) for l, t in self.reviewer_strings()
               if self.EXCEPTION.search(t)]
        self.assertEqual(bad, [], f"exception text on screen: {bad}")

    def test_no_remediation_advice_reaches_the_screen(self) -> None:
        """"Raise max_tokens rather than retrying" is an instruction to an
        engineer. A reviewer cannot act on it and should not be asked to."""
        bad = [(l, t) for l, t in self.reviewer_strings()
               if self.REMEDIATION.search(t)]
        self.assertEqual(bad, [], f"remediation advice on screen: {bad}")

    def test_no_run_artifact_is_named_outside_run_details(self) -> None:
        bad = [(l, t) for l, t in self.reviewer_strings()
               if self.ARTIFACT.search(t) and "runs/" not in t]
        self.assertEqual(bad, [], f"run artifact named on screen: {bad}")

    # --- the fault banner specifically ------------------------------------

    def test_the_fault_banner_is_two_lines(self) -> None:
        code = code_only(APP)
        i = code.index("if injection is not None:")
        block = code[i:i + 420]
        self.assertIn("injection.headline", block)
        self.assertIn("injection.detail", block)
        self.assertIn("NOT_A_RATE", block)
        for gone in ("injection.target", "injection.provenance"):
            self.assertNotIn(gone, block,
                             f"{gone} is provenance and belongs in run "
                             f"details, not over a clinical screen")

    def test_the_fault_labels_carry_no_internal_detail(self) -> None:
        from um_evidence.faults import LABELS
        for fault, (headline, detail) in LABELS.items():
            text = f"{headline} {detail}"
            for pattern, what in ((self.ENUM, "an enum"),
                                  (self.ARTIFACT, "an artifact"),
                                  (self.EXCEPTION, "exception text"),
                                  (self.SPEC, "a spec reference")):
                self.assertIsNone(pattern.search(text),
                                  f"{fault} label contains {what}: {text!r}")

    def test_the_technical_detail_is_kept_not_deleted(self) -> None:
        """Every exemption above is only defensible because the detail is
        still reachable. If run details stopped carrying it, the interface
        would have lost information rather than tidied it."""
        code = code_only(APP)
        i = code.index("with st.expander('run details')")
        block = code[i:code.index("unreadable_notice(", i)]
        self.assertIn("failure_kind", block,
                      "run details must carry the failure kind")
        # The detail must be *rendered*, not merely tested for. Asserting the
        # bare expression passed on the generator's own filter condition,
        # `if ... and r.get("detail")`, so a mutation that dropped it from
        # the output survived.
        self.assertIn("<code>{r.get('detail')}</code>", block,
                      "run details must render the raw pipeline string, not "
                      "just test for its presence")
        self.assertIn("injection.provenance", block,
                      "run details must record that the fault replays a real "
                      "observed failure")

    def test_the_reviewer_sentence_covers_every_failure_kind(self) -> None:
        """A kind with no sentence would fall through to wording that
        asserts a cause the system did not observe."""
        from um_evidence.results import FailureKind
        tree = ast.parse(APP.read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.Assign, ast.Import)):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<app>", "exec"), ns)
                except Exception:
                    pass
        sentence = ns["processing_sentence"]
        for kind in FailureKind:
            text = sentence({"failure_kind": kind.value, "detail": ""})
            self.assertTrue(text.endswith("."), f"{kind} has no sentence")
            self.assertIsNone(self.ENUM.search(text),
                              f"{kind} sentence leaks an enum: {text!r}")
            self.assertNotIn("assessed. This requirement was not assessed",
                             text, f"{kind} sentence repeats itself")

    def test_the_truncation_sentence_is_the_agreed_wording(self) -> None:
        tree = ast.parse(APP.read_text())
        ns = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.Assign, ast.Import)):
                try:
                    exec(compile(ast.Module(body=[node], type_ignores=[]),
                                 "<app>", "exec"), ns)
                except Exception:
                    pass
        real = ("1 attempt(s) failed; last: response truncated at the 16000 "
                "output-token limit (stop_reason max_tokens); raise "
                "max_tokens rather than retrying")
        self.assertEqual(
            ns["processing_sentence"]({"failure_kind": "NO_RESPONSE",
                                       "detail": real}),
            "The model's response was cut off before it produced a result. "
            "This requirement was not assessed.")
