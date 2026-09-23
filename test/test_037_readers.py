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
Unit tests for src.configio.readers.

Test classes follow the two sides of the contract: the requirements a reader
implementation must meet, those the language enforces, and the dispatch
behaviour a caller relies on.
"""

import os
import unittest
import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.readers import Reader, PyconfReader, reader_for

SATDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLI = os.path.join(SATDIR, "test", "APPLI_TEST", "APPLI_TEST.pyconf")


class TestPyconfReader(unittest.TestCase):
    """Requirements met by an implementation of Reader."""

    def test_reader_matches_direct_pyconf_load(self):
        direct = PYF.Config(open(APPLI))
        viaReader = PyconfReader().read(APPLI)
        self.assertEqual(sorted(direct.APPLICATION.keys()),
                         sorted(viaReader.APPLICATION.keys()))
        self.assertEqual(direct.APPLICATION.name, viaReader.APPLICATION.name)

    def test_returns_a_real_pyconf_Config(self):
        self.assertIsInstance(PyconfReader().read(APPLI), PYF.Config)

    def test_declares_its_extension(self):
        self.assertEqual(PyconfReader.extension, ".pyconf")

    def test_pwd_is_threaded_through_unchanged(self):
        here = os.path.dirname(APPLI)
        cfg = PyconfReader().read(APPLI, pwd=("", here))
        self.assertEqual(cfg.PWD, here)

    def test_pwd_defaults_to_none_without_error(self):
        self.assertIsInstance(PyconfReader().read(APPLI), PYF.Config)

    def test_one_instance_can_read_twice(self):
        reader = PyconfReader()
        first = reader.read(APPLI)
        second = reader.read(APPLI)
        self.assertEqual(sorted(first.APPLICATION.keys()),
                         sorted(second.APPLICATION.keys()))

    def test_missing_file_raises(self):
        with self.assertRaises(Exception):
            PyconfReader().read(os.path.join(SATDIR, "test", "no_such.pyconf"))


class TestReaderABC(unittest.TestCase):
    """Requirements enforced by abc."""

    def test_the_base_class_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            Reader()

    def test_a_subclass_without_read_cannot_be_instantiated(self):
        class Incomplete(Reader):
            extension = ".nope"
        with self.assertRaises(TypeError):
            Incomplete()

    def test_PyconfReader_is_a_Reader(self):
        self.assertIsInstance(PyconfReader(), Reader)


class TestReaderFor(unittest.TestCase):
    """Extension dispatch and its failure mode."""

    def test_dispatches_on_extension(self):
        self.assertIsInstance(reader_for("x.pyconf"), PyconfReader)

    def test_dispatches_on_a_full_path(self):
        self.assertIsInstance(reader_for(APPLI), PyconfReader)

    def test_rejects_unknown_extension(self):
        with self.assertRaises(ValueError):
            reader_for("x.ini")

    def test_rejects_a_path_with_no_extension(self):
        with self.assertRaises(ValueError):
            reader_for("x")

    def test_the_error_names_the_extension(self):
        with self.assertRaises(ValueError) as caught:
            reader_for("x.ini")
        self.assertIn(".ini", str(caught.exception))

    def test_does_not_pre_register_json(self):
        # .json is registered by its own task; until then it must raise.
        # .toml was registered by task 3 and is covered in test_038.
        with self.assertRaises(ValueError):
            reader_for("x.json")

    def test_returns_a_fresh_reader_each_call(self):
        self.assertIsNot(reader_for("x.pyconf"), reader_for("x.pyconf"))


if __name__ == '__main__':
    unittest.main()
