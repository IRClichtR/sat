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
Unit tests for src.configio.readers.JsonReader, and the roundtrip property.

read(write(x)) == x, on the values that survive the format. The roundtrip is
lossy by design and the losses are stated here rather than discovered later:
references and expressions are gone, having become the values they evaluated
to, and comments are gone because JSON has none.
"""

import io
import json
import os
import shutil
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.readers import Reader, JsonReader, PyconfReader, reader_for
from src.configio.writers import JsonWriter
from configio_compare import flatten, assert_equivalent

HERE = os.path.dirname(os.path.abspath(__file__))
PYCONF = os.path.join(HERE, "APPLI_TEST", "APPLI_TEST.pyconf")


class JsonTestCase(unittest.TestCase):
    """Base class providing a scratch directory and a write/read cycle."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_json_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="a.json"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as stream:
            stream.write(text)
        return path

    def roundtrip(self, cfg, resolved=True):
        path = os.path.join(self.tmp, "rt.json")
        with open(path, "w") as stream:
            JsonWriter().write(cfg, stream, resolved=resolved)
        return JsonReader().read(path)

    def config(self, build):
        cfg = PYF.Config()
        build(cfg)
        return cfg


class TestJsonReader(JsonTestCase):
    """What the reader must produce: a Config, not a dict."""

    def test_returns_a_real_Config(self):
        path = self.write('{"A": {"x": "1"}}')
        self.assertIsInstance(JsonReader().read(path), PYF.Config)

    def test_objects_become_Mappings_and_arrays_become_Sequences(self):
        path = self.write('{"A": {"B": {"x": "1"}, "depend": ["Python"]}}')
        cfg = JsonReader().read(path)
        self.assertIsInstance(cfg.A.B, PYF.Mapping)
        self.assertIsInstance(cfg.A.depend, PYF.Sequence)

    def test_attribute_access_and_membership_work(self):
        path = self.write('{"APPLICATION": {"name": "MYAPP"}}')
        cfg = JsonReader().read(path)
        self.assertEqual(cfg.APPLICATION.name, "MYAPP")
        self.assertIn("name", cfg.APPLICATION)
        self.assertEqual(list(cfg.APPLICATION.keys()), ["name"])

    def test_the_parent_chain_is_built(self):
        # a Mapping with parent None prints correctly and breaks on access
        path = self.write('{"A": {"B": {"x": "1"}}}')
        cfg = JsonReader().read(path)
        self.assertIs(object.__getattribute__(cfg.A.B, 'parent'), cfg.A)
        self.assertIs(object.__getattribute__(cfg.A, 'parent'), cfg)

    def test_booleans_stay_booleans(self):
        # CONFIGURATION = true feeds isinstance(version, bool) in
        # get_product_config; a stringified bool picks the wrong version
        path = self.write('{"P": {"CONFIGURATION": true}}')
        self.assertIs(JsonReader().read(path).P.CONFIGURATION, True)

    def test_false_is_read_without_complaint(self):
        # D10 constrains what humans may write in TOML, not what a generated
        # lock may contain
        path = self.write('{"P": {"X": false}}')
        self.assertIs(JsonReader().read(path).P.X, False)

    def test_numbers_and_null_survive(self):
        path = self.write('{"n": {"i": 3, "f": 1.5, "z": null}}')
        cfg = JsonReader().read(path)
        self.assertEqual(cfg.n.i, 3)
        self.assertEqual(cfg.n.f, 1.5)
        self.assertIsNone(cfg.n.z)

    def test_templates_are_not_parsed(self):
        # a resolved lock has no references; a ${} here means a raw dump was
        # handed to the wrong loader, and it must stay an inert string
        path = self.write('{"A": {"x": "${VARS.sep}"}}')
        self.assertEqual(JsonReader().read(path).A.x, "${VARS.sep}")

    def test_key_order_is_preserved(self):
        path = self.write('{"x": {"b": "1", "a": "2", "c": "3"}}')
        self.assertEqual(list(JsonReader().read(path).x.keys()), ["b", "a", "c"])

    def test_malformed_json_raises_naming_the_file(self):
        path = self.write('{"A": ', "bad.json")
        with self.assertRaises(Exception) as caught:
            JsonReader().read(path)
        self.assertIn("bad.json", str(caught.exception))


class TestReaderContract(JsonTestCase):

    def test_is_a_Reader(self):
        self.assertIsInstance(JsonReader(), Reader)

    def test_declares_its_extension(self):
        self.assertEqual(JsonReader.extension, ".json")

    def test_reader_for_dispatches_json(self):
        self.assertIsInstance(reader_for("sat.lock.json"), JsonReader)

    def test_pwd_is_threaded_through_unchanged(self):
        path = self.write('{"LOCAL": {"x": "y"}}')
        cfg = JsonReader().read(path, pwd=("LOCAL", "/some/dir"))
        self.assertEqual(cfg.LOCAL.PWD, "/some/dir")


class TestRoundtrip(JsonTestCase):
    """read(write(x)) == x, on the values that survive."""

    def test_a_flat_config_survives(self):
        def build(cfg):
            cfg.addMapping("A", PYF.Mapping(cfg), "")
            cfg.A["x"] = "1"
        cfg = self.config(build)
        assert_equivalent(self, cfg, self.roundtrip(cfg), "source", "roundtrip")

    def test_nested_mappings_and_sequences_survive(self):
        def build(cfg):
            cfg.addMapping("A", PYF.Mapping(cfg), "")
            cfg.A.addMapping("B", PYF.Mapping(cfg.A), "")
            cfg.A.B["x"] = "1"
            seq = PYF.Sequence(cfg.A)
            seq.append("Python", "")
            cfg.A["depend"] = seq
        cfg = self.config(build)
        rt = self.roundtrip(cfg)
        self.assertIsInstance(rt.A.B, PYF.Mapping)
        self.assertIsInstance(rt.A.depend, PYF.Sequence)
        assert_equivalent(self, cfg, rt, "source", "roundtrip")

    def test_the_whole_fixture_survives_as_resolved_values(self):
        cfg = with_context(PyconfReader().read(PYCONF))
        assert_equivalent(self, cfg, self.roundtrip(cfg), "pyconf", "lock")

    def test_references_become_their_values_not_objects(self):
        # the stated loss: object identity is not preserved, and should not be
        cfg = with_context(PyconfReader().read(PYCONF))
        rt = self.roundtrip(cfg)
        raw = object.__getattribute__(cfg.APPLICATION, 'data')["workdir"]
        self.assertIsInstance(raw, PYF.Expression)
        self.assertIsInstance(
            object.__getattribute__(rt.APPLICATION, 'data')["workdir"], str)
        self.assertEqual(rt.APPLICATION.workdir, cfg.APPLICATION.workdir)

    def test_booleans_survive_the_roundtrip(self):
        def build(cfg):
            cfg.addMapping("P", PYF.Mapping(cfg), "")
            cfg.P["CONFIGURATION"] = True
        self.assertIs(self.roundtrip(self.config(build)).P.CONFIGURATION, True)

    def test_a_second_roundtrip_changes_nothing(self):
        # idempotence: once resolved, writing and reading again is a no-op
        cfg = with_context(PyconfReader().read(PYCONF))
        once = self.roundtrip(cfg)
        twice = self.roundtrip(once)
        assert_equivalent(self, once, twice, "first", "second")


def with_context(cfg):
    """Supply the LOCAL and VARS the fixture references, with fixed values."""
    base = PYF.Config()
    base.addMapping("VARS", PYF.Mapping(base), "")
    base.VARS["sep"] = "/"
    base.VARS["dist"] = "UB24.04"
    base.VARS["user"] = "testuser"
    base.addMapping("LOCAL", PYF.Mapping(base), "")
    base.LOCAL["workdir"] = "/work"
    PYF.ConfigMerger().merge(base, cfg)
    return base


if __name__ == '__main__':
    unittest.main()
