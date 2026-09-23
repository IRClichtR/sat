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
Unit tests for src.configio.readers.TomlReader.

Test classes follow the shape of the conversion: the object graph built from
TOML values, reference resolution through the parent chain, and the boolean
rules of decision D10.
"""

import os
import shutil
import sys
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.readers import Reader, TomlReader, reader_for

NEEDS_TOMLLIB = unittest.skipIf(sys.version_info[:2] < (3, 11),
                                "tomllib is stdlib from Python 3.11")


class TomlTestCase(unittest.TestCase):
    """Base class providing a scratch directory and a TOML file writer."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_toml_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="a.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as stream:
            stream.write(text)
        return path

    def read(self, text, pwd=None):
        return TomlReader().read(self.write(text), pwd=pwd)


@NEEDS_TOMLLIB
class TestObjectGraph(TomlTestCase):
    """TOML values become the pyconf types ConfigMerger expects."""

    def test_returns_a_real_pyconf_Config(self):
        self.assertIsInstance(self.read('[APPLICATION]\nname = "x"\n'), PYF.Config)

    def test_scalars_and_nested_tables(self):
        cfg = self.read('[APPLICATION]\nname = "APPLI_TEST"\n'
                        '[APPLICATION.profile]\nlauncher_name = "appli_test"\n')
        self.assertEqual(cfg.APPLICATION.name, "APPLI_TEST")
        self.assertEqual(cfg.APPLICATION.profile.launcher_name, "appli_test")

    def test_nested_table_is_a_Mapping(self):
        cfg = self.read('[APPLICATION]\n[APPLICATION.profile]\nx = "y"\n')
        self.assertIsInstance(cfg.APPLICATION.profile, PYF.Mapping)

    def test_array_becomes_Sequence(self):
        cfg = self.read('[default]\ndepend = ["Python", "boost"]\n')
        self.assertIsInstance(cfg.default.depend, PYF.Sequence)
        self.assertEqual(len(cfg.default.depend), 2)
        self.assertEqual(cfg.default.depend[0], "Python")

    def test_array_of_tables_becomes_a_Sequence_of_Mappings(self):
        cfg = self.read('[[__overwrite__]]\n__condition__ = "VARS.dist in [\'FD32\']"\n'
                        '"APPLICATION.products.scipy" = "1.5.2"\n')
        self.assertIsInstance(cfg.__overwrite__, PYF.Sequence)
        self.assertIsInstance(cfg.__overwrite__[0], PYF.Mapping)
        self.assertEqual(cfg.__overwrite__[0]["APPLICATION.products.scipy"], "1.5.2")

    def test_integers_and_floats_pass_through(self):
        cfg = self.read('[x]\ni = 3\nf = 1.5\n')
        self.assertEqual(cfg.x.i, 3)
        self.assertEqual(cfg.x.f, 1.5)

    def test_empty_table_is_an_empty_Mapping(self):
        cfg = self.read('[APPLICATION]\n[APPLICATION.environ]\n')
        self.assertIsInstance(cfg.APPLICATION.environ, PYF.Mapping)
        self.assertEqual(len(cfg.APPLICATION.environ.keys()), 0)

    def test_key_order_is_preserved(self):
        cfg = self.read('[x]\nb = "1"\na = "2"\nc = "3"\n')
        self.assertEqual(list(cfg.x.keys()), ["b", "a", "c"])


@NEEDS_TOMLLIB
class TestReferences(TomlTestCase):
    """parse_template runs at every depth, and the parent chain must resolve."""

    def test_template_string_becomes_a_reference(self):
        cfg = self.read('[VARS]\nsep = "/"\n[default]\n'
                        'name = "boost"\nd = "${VARS.sep}${default.name}"\n')
        self.assertEqual(cfg.default.d, "/boost")

    def test_plain_string_is_not_wrapped(self):
        cfg = self.read('[x]\nname = "boost"\n')
        self.assertIsInstance(cfg.x.name, str)

    def test_reference_inside_a_deeply_nested_table(self):
        # APPLICATION.environ.build.* holds references in 151 of 162 real files
        cfg = self.read('[APPLICATION]\nworkdir = "/tmp/w"\n'
                        '[APPLICATION.environ.build]\n'
                        'CONFIGURATION_ROOT_DIR = "${APPLICATION.workdir}/SOURCES"\n')
        self.assertEqual(cfg.APPLICATION.environ.build.CONFIGURATION_ROOT_DIR,
                         "/tmp/w/SOURCES")

    def test_reference_inside_an_inline_table(self):
        # APPLICATION.products.<name>.tag holds references in the real corpus
        cfg = self.read('[APPLICATION]\ntag = "V9_12_0"\n'
                        '[APPLICATION.products]\n'
                        'mesa = { tag = "${APPLICATION.tag}" }\n')
        self.assertEqual(cfg.APPLICATION.products.mesa.tag, "V9_12_0")

    def test_reference_inside_a_sequence(self):
        cfg = self.read('[VARS]\nsep = "/"\n[x]\nl = ["a${VARS.sep}b"]\n')
        self.assertEqual(cfg.x.l[0], "a/b")

    def test_reference_resolves_through_the_parent_chain(self):
        # 'sep' is not in the same table; resolution must walk up to the root
        cfg = self.read('[VARS]\nsep = "/"\n'
                        '[APPLICATION.environ.build]\nP = "${VARS.sep}opt"\n')
        self.assertEqual(cfg.APPLICATION.environ.build.P, "/opt")

    def test_escaped_dollar_stays_literal(self):
        cfg = self.read('[x]\nnote = "costs $${100}"\n')
        self.assertEqual(cfg.x.note, "costs ${100}")

    def test_unterminated_template_raises(self):
        with self.assertRaises(Exception):
            self.read('[x]\nbad = "${unterminated"\n')


@NEEDS_TOMLLIB
class TestBooleanRules(TomlTestCase):
    """Decision D10: a bool is valid only as true, only in APPLICATION.products."""

    def test_true_is_accepted_in_products(self):
        cfg = self.read('[APPLICATION.products]\nCONFIGURATION = true\n')
        self.assertIs(cfg.APPLICATION.products.CONFIGURATION, True)

    def test_empty_inline_table_is_accepted_in_products(self):
        cfg = self.read('[APPLICATION.products]\nCONFIGURATION = {}\n')
        self.assertIsInstance(cfg.APPLICATION.products.CONFIGURATION, PYF.Mapping)
        self.assertEqual(len(cfg.APPLICATION.products.CONFIGURATION.keys()), 0)

    def test_false_in_products_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.read('[APPLICATION.products]\nSMESH = false\n')
        self.assertIn("SMESH", str(caught.exception))

    def test_true_outside_products_is_rejected(self):
        with self.assertRaises(ValueError) as caught:
            self.read('[APPLICATION]\ndebug = true\n')
        self.assertIn("debug", str(caught.exception))

    def test_false_outside_products_is_rejected(self):
        with self.assertRaises(ValueError):
            self.read('[APPLICATION]\npython3 = false\n')

    def test_bool_nested_under_a_product_is_rejected(self):
        with self.assertRaises(ValueError):
            self.read('[APPLICATION.products]\nboost = { dev = true }\n')

    def test_yes_and_no_strings_pass_through_untouched(self):
        cfg = self.read('[APPLICATION]\ndebug = "no"\npython3 = "yes"\n')
        self.assertEqual(cfg.APPLICATION.debug, "no")
        self.assertEqual(cfg.APPLICATION.python3, "yes")

    def test_the_rejection_message_explains_the_alternative(self):
        with self.assertRaises(ValueError) as caught:
            self.read('[APPLICATION]\ndebug = true\n')
        message = str(caught.exception)
        self.assertIn('"yes"', message)
        self.assertIn('"no"', message)


@NEEDS_TOMLLIB
class TestReaderContract(TomlTestCase):
    """The obligations Reader states, and registration with reader_for."""

    def test_is_a_Reader(self):
        self.assertIsInstance(TomlReader(), Reader)

    def test_declares_its_extension(self):
        self.assertEqual(TomlReader.extension, ".toml")

    def test_reader_for_dispatches_toml(self):
        self.assertIsInstance(reader_for("x.toml"), TomlReader)

    def test_pwd_is_threaded_through_unchanged(self):
        cfg = self.read('[LOCAL]\nx = "y"\n', pwd=("LOCAL", "/some/dir"))
        self.assertEqual(cfg.LOCAL.PWD, "/some/dir")

    def test_pwd_with_an_empty_key_lands_on_the_config(self):
        cfg = self.read('[LOCAL]\nx = "y"\n', pwd=("", "/some/dir"))
        self.assertEqual(cfg.PWD, "/some/dir")

    def test_one_instance_can_read_twice(self):
        reader = TomlReader()
        first = reader.read(self.write('[x]\na = "1"\n', "one.toml"))
        second = reader.read(self.write('[x]\na = "2"\n', "two.toml"))
        self.assertEqual(first.x.a, "1")
        self.assertEqual(second.x.a, "2")

    def test_missing_file_raises(self):
        with self.assertRaises(Exception):
            TomlReader().read(os.path.join(self.tmp, "absent.toml"))

    def test_malformed_toml_raises_naming_the_file(self):
        path = self.write('[x\nbroken\n', "bad.toml")
        with self.assertRaises(Exception) as caught:
            TomlReader().read(path)
        self.assertIn("bad.toml", str(caught.exception))


if __name__ == '__main__':
    unittest.main()
