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
Unit tests for the write refusal.

Task 7 made one layer, one file an invariant enforced on read. An invariant
enforced on read but not on write is not an invariant: a user with
data/local.toml who runs `sat init --base` would get a local.pyconf written
beside it, and the fatal ambiguity error on their next command, pointing at a
file they never created.

So every write boundary has to know about it -- and the refusal has to tell the
user which file and which key to edit, or it is just a wall.
"""

import os
import shutil
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src
import src.salomeTools  # noqa: F401  -- installs gettext for _()
from src.configio.writers import (TomlWriteRefused, PyconfWriter,
                                  writer_for_layer)


class RefusalTestCase(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_refuse_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, name):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as stream:
            stream.write("")
        return path

    def stem(self, name="local"):
        return os.path.join(self.tmp, name)


class TestWriterForLayer(RefusalTestCase):

    def test_a_pyconf_layer_returns_a_writer(self):
        self.touch("local.pyconf")
        self.assertIsInstance(writer_for_layer(self.stem(), [self.tmp]),
                              PyconfWriter)

    def test_an_absent_layer_returns_a_writer(self):
        # first run: no local.* exists yet, and create_config_file exists
        # precisely to create one. Absence is not TOML.
        self.assertIsInstance(writer_for_layer(self.stem(), [self.tmp]),
                              PyconfWriter)

    def test_a_toml_layer_refuses(self):
        self.touch("local.toml")
        with self.assertRaises(TomlWriteRefused):
            writer_for_layer(self.stem(), [self.tmp])

    def test_it_is_a_SatException_so_sat_reports_it_normally(self):
        self.assertTrue(issubclass(TomlWriteRefused, src.SatException))


class TestTheRefusalIsUseful(RefusalTestCase):
    """A refusal the user cannot act on is a defect, not a safeguard."""

    def refuse(self, key=None):
        path = self.touch("local.toml")
        with self.assertRaises(TomlWriteRefused) as caught:
            writer_for_layer(self.stem(), [self.tmp], key=key)
        return path, str(caught.exception)

    def test_it_names_the_file(self):
        path, message = self.refuse()
        self.assertIn(path, message)

    def test_it_names_the_key_when_one_is_given(self):
        path, message = self.refuse(key="LOCAL.base")
        self.assertIn("LOCAL.base", message)

    def test_it_says_toml_is_the_user_s_to_edit(self):
        path, message = self.refuse()
        self.assertIn("not write", message.lower())

    def test_it_works_without_a_key(self):
        # not every site knows a single key -- the file alone must still be named
        path, message = self.refuse()
        self.assertIn(".toml", message)


class TestSearchPathForm(RefusalTestCase):
    """The same two stem forms discovery accepts."""

    def test_a_bare_name_is_resolved_against_the_search_path(self):
        self.touch("SAT.toml")
        with self.assertRaises(TomlWriteRefused):
            writer_for_layer("SAT", [self.tmp])

    def test_a_bare_name_with_no_file_returns_a_writer(self):
        self.assertIsInstance(writer_for_layer("SAT", [self.tmp]), PyconfWriter)

    def test_ambiguity_still_propagates(self):
        # two files for one layer is task 7's error, and it must not be masked
        from src.configio.discovery import AmbiguousLayerError
        self.touch("local.pyconf")
        self.touch("local.toml")
        with self.assertRaises(AmbiguousLayerError):
            writer_for_layer(self.stem(), [self.tmp])


if __name__ == '__main__':
    unittest.main()
