import io
import unittest
import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.interp import (parse_template, contains_template, TemplateError,
                                 scan, split_path, LITERAL, REF)


class TestScan(unittest.TestCase):
    """Phase 1: the string -> parts list. No pyconf, no Config, plain equality."""

    def test_empty_string_has_no_parts(self):
        self.assertEqual(scan(""), [])

    def test_plain_text_is_one_literal_part(self):
        self.assertEqual(scan("boost"), [(LITERAL, "boost")])

    def test_lone_reference_is_one_ref_part(self):
        self.assertEqual(scan("${name}"), [(REF, "name")])

    def test_reference_content_stays_raw(self):
        self.assertEqual(scan("${APPLICATION.workdir}"),
                         [(REF, "APPLICATION.workdir")])

    def test_bracket_reference_content_stays_raw(self):
        self.assertEqual(scan('${A["x"]}'), [(REF, 'A["x"]')])

    def test_reference_then_literal(self):
        self.assertEqual(scan("${name}.py"),
                         [(REF, "name"), (LITERAL, ".py")])

    def test_literal_between_two_references(self):
        self.assertEqual(scan("${A}/SOURCES/${B}"),
                         [(REF, "A"), (LITERAL, "/SOURCES/"), (REF, "B")])

    def test_adjacent_references_emit_no_empty_literal(self):
        self.assertEqual(scan("${a}${b}"), [(REF, "a"), (REF, "b")])

    def test_dollar_without_brace_is_an_ordinary_character(self):
        self.assertEqual(scan("costs $5"), [(LITERAL, "costs $5")])

    def test_trailing_dollar_is_an_ordinary_character(self):
        self.assertEqual(scan("cost$"), [(LITERAL, "cost$")])

    def test_brace_without_dollar_is_an_ordinary_character(self):
        self.assertEqual(scan("a{b}c"), [(LITERAL, "a{b}c")])

    def test_double_dollar_escapes_the_template_opener(self):
        self.assertEqual(scan("costs $${100}"), [(LITERAL, "costs ${100}")])

    def test_double_dollar_collapses_outside_a_template_too(self):
        self.assertEqual(scan("costs $$5"), [(LITERAL, "costs $5")])

    def test_literals_split_by_an_escape_are_merged(self):
        self.assertEqual(scan("$${a}${b}c"),
                         [(LITERAL, "${a}"), (REF, "b"), (LITERAL, "c")])

    def test_unterminated_reference_raises(self):
        with self.assertRaises(TemplateError):
            scan("${unterminated")

    def test_unterminated_reference_reports_its_position(self):
        with self.assertRaises(TemplateError) as caught:
            scan("a/${b")
        self.assertIn("position 2", str(caught.exception))

    def test_empty_reference_raises(self):
        with self.assertRaises(TemplateError):
            scan("${}")


class TestSplitPath(unittest.TestCase):
    """The second, smaller grammar: reference text -> (head, steps).

    Shaped to feed Reference(config, DOLLAR, head) then one addElement per step.
    """

    def test_bare_name_has_no_steps(self):
        self.assertEqual(split_path("name"), ("name", []))

    def test_dotted_name_yields_one_step(self):
        self.assertEqual(split_path("APPLICATION.workdir"),
                         ("APPLICATION", [(PYF.DOT, "workdir")]))

    def test_several_dots_yield_several_steps(self):
        self.assertEqual(split_path("A.b.c"),
                         ("A", [(PYF.DOT, "b"), (PYF.DOT, "c")]))

    def test_double_quoted_subscript(self):
        self.assertEqual(split_path('A["x"]'), ("A", [(PYF.LBRACK, "x")]))

    def test_single_quoted_subscript(self):
        self.assertEqual(split_path("A['x']"), ("A", [(PYF.LBRACK, "x")]))

    def test_numeric_subscript_stays_an_int(self):
        head, steps = split_path("A[0]")
        self.assertEqual((head, steps), ("A", [(PYF.LBRACK, 0)]))
        self.assertIsInstance(steps[0][1], int)

    def test_dots_and_subscripts_mix_in_order(self):
        self.assertEqual(split_path('A.b["x"].c'),
                         ("A", [(PYF.DOT, "b"), (PYF.LBRACK, "x"), (PYF.DOT, "c")]))

    def test_underscore_and_digits_are_valid_in_names(self):
        self.assertEqual(split_path("_a1.b2"), ("_a1", [(PYF.DOT, "b2")]))

    def test_empty_path_raises(self):
        with self.assertRaises(TemplateError):
            split_path("")

    def test_leading_dot_raises(self):
        with self.assertRaises(TemplateError):
            split_path(".A")

    def test_trailing_dot_raises(self):
        with self.assertRaises(TemplateError):
            split_path("A.")

    def test_doubled_dot_raises(self):
        with self.assertRaises(TemplateError):
            split_path("A..b")

    def test_name_starting_with_a_digit_raises(self):
        with self.assertRaises(TemplateError):
            split_path("1abc")

    def test_unterminated_subscript_raises(self):
        with self.assertRaises(TemplateError):
            split_path('A["x"')

    def test_unquoted_subscript_raises(self):
        with self.assertRaises(TemplateError):
            split_path("A[x]")

    def test_whitespace_in_a_path_raises(self):
        with self.assertRaises(TemplateError):
            split_path("A b")

    def test_error_message_gives_position(self):
        with self.assertRaises(TemplateError) as caught:
            split_path("A.")
        self.assertIn("position 2", str(caught.exception))


class TestBuild(unittest.TestCase):
    """Phase 2: parts list -> pyconf objects. The cases the plan's set misses."""

    def setUp(self):
        self.cfg = PYF.Config()

    def test_empty_string_stays_an_empty_string(self):
        self.assertEqual(parse_template("", self.cfg), "")

    def test_dollar_without_brace_stays_plain_text(self):
        self.assertEqual(parse_template("costs $5", self.cfg), "costs $5")

    def test_bracket_reference_becomes_a_Reference(self):
        rv = parse_template('${A["x"]}', self.cfg)
        self.assertIsInstance(rv, PYF.Reference)
        self.assertEqual(str(rv), "$A['x']")

    def test_expression_chain_is_left_associative(self):
        rv = parse_template("${A}/SOURCES/${B}", self.cfg)
        self.assertIsInstance(rv, PYF.Expression)
        self.assertIsInstance(rv.lhs, PYF.Expression)      # (A + '/SOURCES/')
        self.assertIsInstance(rv.rhs, PYF.Reference)       # ... + B
        self.assertEqual(rv.op, PYF.PLUS)
        self.assertIsInstance(rv.lhs.lhs, PYF.Reference)
        self.assertEqual(rv.lhs.rhs, "/SOURCES/")

    def test_bad_path_inside_a_reference_raises(self):
        with self.assertRaises(TemplateError):
            parse_template("${A..b}", self.cfg)

    def test_built_objects_really_evaluate_against_a_config(self):
        cfg = PYF.Config(io.StringIO('name : "boost"\nvers : "1.2"\n'))
        rv = parse_template("${name}-${vers}.tgz", cfg)
        self.assertEqual(rv.evaluate(cfg), "boost-1.2.tgz")


class TestContainsTemplate(unittest.TestCase):

    def test_plain_text_is_not_a_template(self):
        self.assertFalse(contains_template("boost"))

    def test_a_dot_alone_is_not_a_template(self):
        self.assertFalse(contains_template("boost.py"))

    def test_a_bracket_alone_is_not_a_template(self):
        self.assertFalse(contains_template("site-packages[old]"))

    def test_a_bare_dollar_is_not_a_template(self):
        self.assertFalse(contains_template("costs $5"))

    def test_an_escaped_opener_is_not_a_template(self):
        self.assertFalse(contains_template("costs $${100}"))

    def test_a_reference_is_a_template(self):
        self.assertTrue(contains_template("${a}"))

    def test_a_reference_next_to_text_is_a_template(self):
        self.assertTrue(contains_template("${a}b"))


class TestInterp(unittest.TestCase):

    def setUp(self):
        self.cfg = PYF.Config()

    def test_plain_string_passes_through_unchanged(self):
        print(self.cfg)
        self.assertEqual(parse_template("boost", self.cfg), "boost")
        self.assertFalse(contains_template("boost"))

    def test_lone_reference_becomes_Reference(self):
        rv = parse_template("${name}", self.cfg)
        self.assertIsInstance(rv, PYF.Reference)
        self.assertEqual(str(rv), "$name")

    def test_dotted_reference_keeps_full_path(self):
        rv = parse_template("${APPLICATION.workdir}", self.cfg)
        self.assertEqual(str(rv), "$APPLICATION.workdir")

    def test_mixed_literal_and_reference_becomes_Expression(self):
        rv = parse_template("${APPLICATION.workdir}/SOURCES", self.cfg)
        self.assertIsInstance(rv, PYF.Expression)

    def test_adjacent_references_become_Expression(self):
        rv = parse_template("${name}${VARS.sep}", self.cfg)
        self.assertIsInstance(rv, PYF.Expression)

    def test_double_dollar_escapes_to_literal(self):
        self.assertEqual(parse_template("costs $${100}", self.cfg), "costs ${100}")

    def test_unterminated_brace_raises(self):
        with self.assertRaises(TemplateError):
            parse_template("${unterminated", self.cfg)


if __name__ == '__main__':
    unittest.main()