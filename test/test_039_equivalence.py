#!/usr/bin/env python
#-*- coding:utf-8 -*-

#  Copyright (C) 2010-2018  CEA/DEN
#
#  This library is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2.1 of the License.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA

"""\
The equivalence oracle: one configuration, two source formats, one result.

Two lanes differing only in their input format converge on a single
comparison, so a reported difference is attributable to a reader rather than
to the harness. The test asserts no expected values of its own; it would stay
meaningful if every value in the fixture changed.
"""

import os
import sys
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.readers import PyconfReader, TomlReader
from configio_compare import (flatten, assert_equivalent,
                              EMPTY_MAPPING, EMPTY_SEQUENCE)

HERE = os.path.dirname(os.path.abspath(__file__))
PYCONF = os.path.join(HERE, "APPLI_TEST", "APPLI_TEST.pyconf")
TOML = os.path.join(HERE, "APPLI_TEST", "APPLI_TEST.toml")

NEEDS_TOMLLIB = unittest.skipIf(sys.version_info[:2] < (3, 11),
                                "tomllib is stdlib from Python 3.11")


def with_context(cfg):
    """\
    Supply the LOCAL and VARS the fixture references, with fixed values.

    Neither fixture declares them, so workdir cannot resolve standalone. The
    values are fixed rather than read from the machine so the test gives the
    same answer everywhere.

    :param cfg: A configuration loaded from one of the fixtures.
    :return: That configuration merged onto a context, as get_config does.
    :rtype: class 'src.pyconf.Config'
    """
    base = PYF.Config()
    base.addMapping("VARS", PYF.Mapping(base), "")
    base.VARS["sep"] = "/"
    base.VARS["dist"] = "UB24.04"
    base.VARS["user"] = "testuser"
    base.addMapping("LOCAL", PYF.Mapping(base), "")
    base.LOCAL["workdir"] = "/work"
    PYF.ConfigMerger().merge(base, cfg)
    return base


@NEEDS_TOMLLIB
class TestEquivalence(unittest.TestCase):
    """The oracle proper: the two lanes must agree on everything."""

    def lanes(self):
        return (with_context(PyconfReader().read(PYCONF)),
                with_context(TomlReader().read(TOML)))

    def test_pyconf_and_toml_produce_identical_trees(self):
        pyconf, toml = self.lanes()
        assert_equivalent(self, pyconf, toml, "pyconf", "toml")

    def test_the_reference_chain_resolves_identically(self):
        pyconf, toml = self.lanes()
        self.assertEqual(pyconf.APPLICATION.workdir, toml.APPLICATION.workdir)
        self.assertEqual(pyconf.APPLICATION.workdir,
                         "/work/APPLI_TEST-UB24.04")

    def test_the_expression_with_a_literal_resolves_identically(self):
        pyconf, toml = self.lanes()
        self.assertEqual(pyconf.APPLICATION.environ.TESTS_ROOT_DIR,
                         toml.APPLICATION.environ.TESTS_ROOT_DIR)

    def test_the_bare_key_shorthand_matches_an_explicit_true(self):
        pyconf, toml = self.lanes()
        self.assertIs(pyconf.APPLICATION.products.CONFIGURATION, True)
        self.assertIs(toml.APPLICATION.products.CONFIGURATION, True)

    def test_the_fixture_exercises_every_construct_it_claims_to(self):
        # guards the oracle's coverage: if the fixture is trimmed, say so here
        flat = flatten(with_context(PyconfReader().read(PYCONF)))
        for path in ("APPLICATION.workdir",                   # Expression
                     "APPLICATION.environ.TESTS_ROOT_DIR",    # Expression + literal
                     "APPLICATION.products.Python",           # pinned string
                     "APPLICATION.products.CONFIGURATION",    # bare-key shorthand
                     "APPLICATION.profile.launcher_name",     # nested table
                     "APPLICATION.test_base.tag"):
            self.assertIn(path, flat)


class TestFlatten(unittest.TestCase):
    """The comparator's own behaviour, tested without either reader."""

    def config(self, build):
        cfg = PYF.Config()
        build(cfg)
        return cfg

    def test_nested_mappings_become_dotted_paths(self):
        def build(cfg):
            cfg.addMapping("A", PYF.Mapping(cfg), "")
            cfg.A["b"] = "c"
        self.assertEqual(flatten(self.config(build)), {"A.b": "c"})

    def test_sequences_become_indexed_paths(self):
        def build(cfg):
            seq = PYF.Sequence(cfg)
            seq.append("x", "")
            seq.append("y", "")
            cfg.addMapping("l", seq, "")
        self.assertEqual(flatten(self.config(build)), {"l[0]": "x", "l[1]": "y"})

    def test_an_empty_mapping_is_visible(self):
        # without a marker an empty table contributes no path, and a missing
        # table would compare equal to an empty one
        def build(cfg):
            cfg.addMapping("A", PYF.Mapping(cfg), "")
        self.assertEqual(flatten(self.config(build)), {"A": EMPTY_MAPPING})

    def test_an_empty_sequence_is_visible(self):
        def build(cfg):
            cfg.addMapping("l", PYF.Sequence(cfg), "")
        self.assertEqual(flatten(self.config(build)), {"l": EMPTY_SEQUENCE})

    def test_references_are_resolved_not_returned_as_objects(self):
        def build(cfg):
            cfg.addMapping("A", PYF.Mapping(cfg), "")
            cfg.A["name"] = "boost"
            ref = PYF.Reference(cfg, PYF.DOLLAR, "A")
            ref.addElement(PYF.DOT, "name")
            cfg.addMapping("r", ref, "")
        self.assertEqual(flatten(self.config(build))["r"], "boost")


class TestAssertEquivalent(unittest.TestCase):
    """The comparator must fail when it should, and say why."""

    def two(self, a, b):
        first, second = PYF.Config(), PYF.Config()
        first.addMapping("A", PYF.Mapping(first), "")
        second.addMapping("A", PYF.Mapping(second), "")
        for key in a:
            first.A[key] = a[key]
        for key in b:
            second.A[key] = b[key]
        return first, second

    def test_identical_configurations_pass(self):
        first, second = self.two({"x": "1"}, {"x": "1"})
        assert_equivalent(self, first, second)

    def test_a_missing_key_fails_and_is_named(self):
        first, second = self.two({"x": "1", "y": "2"}, {"x": "1"})
        with self.assertRaises(AssertionError) as caught:
            assert_equivalent(self, first, second, "left", "right")
        message = str(caught.exception)
        self.assertIn("different keys", message)
        self.assertIn("A.y", message)
        self.assertIn("left", message)

    def test_a_differing_value_fails_and_shows_both(self):
        first, second = self.two({"x": "1"}, {"x": "2"})
        with self.assertRaises(AssertionError) as caught:
            assert_equivalent(self, first, second, "left", "right")
        message = str(caught.exception)
        self.assertIn("A.x", message)
        self.assertIn("'1'", message)
        self.assertIn("'2'", message)

    def test_key_differences_are_reported_before_value_differences(self):
        # a missing key explains a value mismatch; the reverse is not true
        first, second = self.two({"x": "1", "y": "2"}, {"x": "9"})
        with self.assertRaises(AssertionError) as caught:
            assert_equivalent(self, first, second)
        self.assertIn("different keys", str(caught.exception))
        self.assertNotIn("value(s) differ", str(caught.exception))


if __name__ == '__main__':
    unittest.main()
