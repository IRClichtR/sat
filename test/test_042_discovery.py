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
Unit tests for src.configio.discovery.

Discovery answers one question -- which file is this configuration layer --
and refuses to answer it when two files claim the same layer. Absence is
reported rather than judged, because whether a missing layer is fatal depends
on the layer and only the caller knows that.
"""

import os
import shutil
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src
from src.configio.discovery import (resolve_layer, layer_is_toml,
                                    AmbiguousLayerError, LAYER_EXTENSIONS)
from src.configio.readers import PyconfReader, TomlReader


class DiscoveryTestCase(unittest.TestCase):
    """Base class providing a scratch tree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_disc_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def touch(self, name, directory=None):
        directory = directory or self.tmp
        if not os.path.isdir(directory):
            os.makedirs(directory)
        path = os.path.join(directory, name)
        with open(path, "w") as stream:
            stream.write("")
        return path

    def subdir(self, name):
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        return path


class TestResolveByPath(DiscoveryTestCase):
    """A stem carrying a directory, as the hardcoded layers do today."""

    def stem(self, name="local"):
        return os.path.join(self.tmp, name)

    def test_finds_pyconf_when_only_pyconf_exists(self):
        self.touch("local.pyconf")
        path, reader = resolve_layer(self.stem(), [self.tmp])
        self.assertTrue(path.endswith(".pyconf"))
        self.assertIsInstance(reader, PyconfReader)

    def test_finds_toml_when_only_toml_exists(self):
        self.touch("local.toml")
        path, reader = resolve_layer(self.stem(), [self.tmp])
        self.assertTrue(path.endswith(".toml"))
        self.assertIsInstance(reader, TomlReader)

    def test_missing_layer_returns_none_rather_than_raising(self):
        # absence is the caller's to interpret: LOCAL is required,
        # APPLICATION is not. Discovery reports, it does not judge.
        self.assertEqual(resolve_layer(self.stem("nope"), [self.tmp]),
                         (None, None))

    def test_a_missing_directory_is_not_an_error(self):
        stem = os.path.join(self.tmp, "absent_dir", "local")
        self.assertEqual(resolve_layer(stem, []), (None, None))


class TestAmbiguity(DiscoveryTestCase):
    """Two files claiming one layer is fatal, never a precedence decision."""

    def test_both_present_is_fatal(self):
        self.touch("local.pyconf")
        self.touch("local.toml")
        with self.assertRaises(AmbiguousLayerError):
            resolve_layer(os.path.join(self.tmp, "local"), [self.tmp])

    def test_the_message_names_both_paths(self):
        pyconf = self.touch("local.pyconf")
        toml = self.touch("local.toml")
        with self.assertRaises(AmbiguousLayerError) as caught:
            resolve_layer(os.path.join(self.tmp, "local"), [self.tmp])
        message = str(caught.exception)
        self.assertIn(pyconf, message)
        self.assertIn(toml, message)

    def test_the_message_says_what_to_do(self):
        self.touch("local.pyconf")
        self.touch("local.toml")
        with self.assertRaises(AmbiguousLayerError) as caught:
            resolve_layer(os.path.join(self.tmp, "local"), [self.tmp])
        self.assertIn("remove", str(caught.exception).lower())

    def test_it_is_a_SatException_so_sat_reports_it_normally(self):
        self.assertTrue(issubclass(AmbiguousLayerError, src.SatException))


class TestSearchPaths(DiscoveryTestCase):
    """A bare name resolved against a search path, as products are."""

    def test_search_paths_are_tried_in_order(self):
        first, second = self.subdir("a"), self.subdir("b")
        self.touch("boost.pyconf", first)
        self.touch("boost.pyconf", second)
        path, _ = resolve_layer("boost", [first, second])
        self.assertTrue(path.startswith(first))

    def test_the_same_name_in_two_formats_in_two_directories_is_not_ambiguous(self):
        # this is what PATHS.PRODUCTPATH overriding is for: first wins.
        # checking ambiguity across the search path instead of per directory
        # would break every project that overrides a product.
        first, second = self.subdir("a"), self.subdir("b")
        self.touch("boost.pyconf", first)
        self.touch("boost.toml", second)
        path, reader = resolve_layer("boost", [first, second])
        self.assertTrue(path.startswith(first))
        self.assertIsInstance(reader, PyconfReader)

    def test_ambiguity_inside_a_later_directory_is_still_fatal(self):
        first, second = self.subdir("a"), self.subdir("b")
        self.touch("boost.pyconf", second)
        self.touch("boost.toml", second)
        with self.assertRaises(AmbiguousLayerError):
            resolve_layer("boost", [first, second])

    def test_a_later_directory_is_used_when_the_first_has_nothing(self):
        first, second = self.subdir("a"), self.subdir("b")
        self.touch("boost.toml", second)
        path, reader = resolve_layer("boost", [first, second])
        self.assertTrue(path.startswith(second))
        self.assertIsInstance(reader, TomlReader)

    def test_no_search_paths_finds_nothing(self):
        self.assertEqual(resolve_layer("boost", []), (None, None))


class TestJsonIsNotDiscoverable(DiscoveryTestCase):
    """Being able to read a format and looking for it are separate decisions."""

    def test_json_alone_is_not_found(self):
        self.touch("local.json")
        self.assertEqual(resolve_layer(os.path.join(self.tmp, "local"),
                                       [self.tmp]), (None, None))

    def test_json_beside_pyconf_is_not_ambiguous(self):
        self.touch("local.pyconf")
        self.touch("local.json")
        path, reader = resolve_layer(os.path.join(self.tmp, "local"), [self.tmp])
        self.assertTrue(path.endswith(".pyconf"))
        self.assertIsInstance(reader, PyconfReader)

    def test_the_discovered_extensions_are_exactly_two(self):
        # a resolved lock is machine-specific (D6); letting one be dropped in
        # as a layer would make someone else's absolute paths configuration
        self.assertEqual(tuple(LAYER_EXTENSIONS), (".pyconf", ".toml"))


class TestOurOwnFixtures(unittest.TestCase):
    """The repository must not break the rule discovery enforces."""

    def test_the_unittest_application_directory_is_unambiguous(self):
        # commands/config.py:465 appends test/APPLI_TEST to APPLICATIONPATH,
        # so once task 10 routes that layer through resolve_layer, a second
        # file naming APPLI_TEST there would make sat config APPLI_TEST fail.
        # The oracle's TOML twin lives in test/configio_fixtures for this reason.
        here = os.path.dirname(os.path.abspath(__file__))
        stem = os.path.join(here, "APPLI_TEST", "APPLI_TEST")
        path, reader = resolve_layer(stem, [])
        self.assertTrue(path.endswith(".pyconf"))
        self.assertIsInstance(reader, PyconfReader)


class TestLayerIsToml(DiscoveryTestCase):

    def test_true_for_a_toml_path(self):
        self.assertTrue(layer_is_toml("/a/b/local.toml"))

    def test_false_for_a_pyconf_path(self):
        self.assertFalse(layer_is_toml("/a/b/local.pyconf"))

    def test_false_for_a_missing_layer(self):
        # callers pass the result of resolve_layer straight in
        self.assertFalse(layer_is_toml(None))


if __name__ == '__main__':
    unittest.main()
