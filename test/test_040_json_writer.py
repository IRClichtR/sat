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
Unit tests for src.configio.writers.

A Config holds plain values and deferred computations. The tests are organised
around the choice that forces: resolved mode snapshots the result, raw mode
snapshots the computation.
"""

import io
import json
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.writers import Writer, JsonWriter, PyconfWriter


def sample():
    """A config holding a plain value, a Reference and an Expression."""
    cfg = PYF.Config()
    cfg.addMapping("VARS", PYF.Mapping(cfg), "")
    cfg.VARS["sep"] = "/"
    cfg.addMapping("APPLICATION", PYF.Mapping(cfg), "")
    cfg.APPLICATION["name"] = "MYAPP"
    cfg.APPLICATION["workdir"] = "/work"
    ref = PYF.Reference(cfg, PYF.DOLLAR, "APPLICATION")
    ref.addElement(PYF.DOT, "workdir")
    cfg.APPLICATION["src"] = PYF.Expression(PYF.PLUS, ref, "/SOURCES")
    return cfg


def dump(cfg, resolved=True):
    stream = io.StringIO()
    JsonWriter().write(cfg, stream, resolved=resolved)
    return json.loads(stream.getvalue())


def text(cfg, resolved=True):
    stream = io.StringIO()
    JsonWriter().write(cfg, stream, resolved=resolved)
    return stream.getvalue()


class TestResolvedMode(unittest.TestCase):
    """The lock: deferred computations are evaluated and the result written."""

    def test_expressions_are_evaluated(self):
        self.assertEqual(dump(sample())["APPLICATION"]["src"], "/work/SOURCES")

    def test_references_are_evaluated(self):
        cfg = sample()
        ref = PYF.Reference(cfg, PYF.DOLLAR, "VARS")
        ref.addElement(PYF.DOT, "sep")
        cfg.APPLICATION["s"] = ref
        self.assertEqual(dump(cfg)["APPLICATION"]["s"], "/")

    def test_resolved_is_the_default(self):
        self.assertEqual(dump(sample())["APPLICATION"]["src"],
                         json.loads(text(sample()))["APPLICATION"]["src"])

    def test_evaluation_uses_the_enclosing_container_not_the_root(self):
        # a bare reference resolves by walking up from its own container;
        # handing the root config to evaluate() would fail to find 'workdir'
        cfg = PYF.Config()
        cfg.addMapping("APPLICATION", PYF.Mapping(cfg), "")
        cfg.APPLICATION["workdir"] = "/work"
        environ = PYF.Mapping(cfg.APPLICATION)
        cfg.APPLICATION.addMapping("environ", environ, "")
        ref = PYF.Reference(cfg, PYF.DOLLAR, "workdir")
        environ["BUILD"] = PYF.Expression(PYF.PLUS, ref, "/BUILD")
        self.assertEqual(dump(cfg)["APPLICATION"]["environ"]["BUILD"],
                         "/work/BUILD")

    def test_an_unresolvable_reference_raises(self):
        # a real bug in the caller; task 8 drops dead sections before this point
        cfg = PYF.Config()
        cfg.addMapping("A", PYF.Mapping(cfg), "")
        cfg.A["x"] = PYF.Reference(cfg, PYF.DOLLAR, "nowhere")
        with self.assertRaises(PYF.ConfigResolutionError):
            dump(cfg)


class TestRawMode(unittest.TestCase):
    """The diagnostic: what did the author actually write?"""

    def test_the_template_is_preserved(self):
        self.assertIn("$APPLICATION.workdir",
                      dump(sample(), resolved=False)["APPLICATION"]["src"])

    def test_a_lone_reference_is_written_in_pyconf_syntax(self):
        cfg = sample()
        ref = PYF.Reference(cfg, PYF.DOLLAR, "VARS")
        ref.addElement(PYF.DOT, "sep")
        cfg.APPLICATION["s"] = ref
        self.assertEqual(dump(cfg, resolved=False)["APPLICATION"]["s"],
                         "$VARS.sep")

    def test_raw_mode_does_not_resolve_and_so_does_not_raise(self):
        cfg = PYF.Config()
        cfg.addMapping("A", PYF.Mapping(cfg), "")
        cfg.A["x"] = PYF.Reference(cfg, PYF.DOLLAR, "nowhere")
        self.assertEqual(dump(cfg, resolved=False)["A"]["x"], "$nowhere")


class TestValueMapping(unittest.TestCase):
    """Everything that is not a deferred computation."""

    def test_plain_scalars_survive_both_modes(self):
        for resolved in (True, False):
            self.assertEqual(dump(sample(), resolved)["APPLICATION"]["name"],
                             "MYAPP")

    def test_sequences_become_arrays(self):
        cfg = PYF.Config()
        cfg.addMapping("d", PYF.Mapping(cfg), "")
        seq = PYF.Sequence(cfg.d)
        seq.append("Python", "")
        seq.append("boost", "")
        cfg.d["depend"] = seq
        self.assertEqual(dump(cfg)["d"]["depend"], ["Python", "boost"])

    def test_booleans_stay_booleans(self):
        cfg = PYF.Config()
        cfg.addMapping("P", PYF.Mapping(cfg), "")
        cfg.P["CONFIGURATION"] = True
        self.assertIs(dump(cfg)["P"]["CONFIGURATION"], True)

    def test_numbers_stay_numbers(self):
        cfg = PYF.Config()
        cfg.addMapping("n", PYF.Mapping(cfg), "")
        cfg.n["i"] = 3
        cfg.n["f"] = 1.5
        self.assertEqual(dump(cfg)["n"], {"i": 3, "f": 1.5})

    def test_none_becomes_null(self):
        cfg = PYF.Config()
        cfg.addMapping("n", PYF.Mapping(cfg), "")
        cfg.n["x"] = None
        self.assertIn('"x": null', text(cfg))

    def test_nested_mappings_become_nested_objects(self):
        cfg = PYF.Config()
        cfg.addMapping("A", PYF.Mapping(cfg), "")
        cfg.A.addMapping("B", PYF.Mapping(cfg.A), "")
        cfg.A.B["x"] = "1"
        self.assertEqual(dump(cfg)["A"]["B"]["x"], "1")


class TestOutputShape(unittest.TestCase):

    def test_keys_are_not_sorted(self):
        # product.py iterates aProd.keys() hunting version-range sections, and
        # a lock should stay diffable against its source
        cfg = PYF.Config()
        cfg.addMapping("x", PYF.Mapping(cfg), "")
        for key in ("b", "a", "c"):
            cfg.x[key] = "1"
        self.assertEqual(list(json.loads(text(cfg))["x"].keys()), ["b", "a", "c"])

    def test_output_is_indented(self):
        self.assertIn("\n  ", text(sample()))


class TestWriterContract(unittest.TestCase):

    def test_the_base_class_cannot_be_instantiated(self):
        with self.assertRaises(TypeError):
            Writer()

    def test_json_writer_declares_its_extension(self):
        self.assertEqual(JsonWriter.extension, ".json")

    def test_pyconf_writer_declares_its_extension(self):
        self.assertEqual(PyconfWriter.extension, ".pyconf")

    def test_pyconf_writer_round_trips_through_pyconf_itself(self):
        stream = io.StringIO()
        PyconfWriter().write(sample(), stream)
        reloaded = PYF.Config(io.StringIO(stream.getvalue()))
        self.assertEqual(reloaded.APPLICATION.name, "MYAPP")

    def test_writers_are_not_readers(self):
        self.assertFalse(hasattr(JsonWriter(), "read"))


if __name__ == '__main__':
    unittest.main()
