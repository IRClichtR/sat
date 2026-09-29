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
Unit tests for src.configio.validate and `sat config --validate`.

Validation is limited to what the file alone determines: TOML grammar, the
${} template grammar, and the value rules TomlReader enforces (D10 booleans,
no dates). References are not resolved and products are not looked up.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
from src.configio.validate import validate_toml

NEEDS_TOMLLIB = unittest.skipIf(sys.version_info[:2] < (3, 11),
                                "tomllib is stdlib from Python 3.11")

SATDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE = os.path.join(SATDIR, "test", "configio_fixtures", "APPLI_TEST.toml")


class ValidateTestCase(unittest.TestCase):
    """Base class providing a scratch directory and a file writer."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_validate_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, text, name="a.toml"):
        path = os.path.join(self.tmp, name)
        with open(path, "w") as stream:
            stream.write(text)
        return path

    def errors(self, text):
        return validate_toml(self.write(text))


@NEEDS_TOMLLIB
class TestValidFiles(ValidateTestCase):

    def test_the_fixture_application_is_valid(self):
        self.assertEqual(validate_toml(FIXTURE), [])

    def test_unresolvable_references_are_not_an_error(self):
        # Resolution needs the other layers; validation deliberately stops short.
        self.assertEqual(self.errors('[A]\nx = "${NO.SUCH.KEY}/bin"\n'), [])

    def test_the_accepted_product_spellings_are_valid(self):
        text = ('[APPLICATION.products]\n'
                'KERNEL = true\n'
                'GUI = {}\n'
                'boost = "1.58.0"\n'
                'MEDCOUPLING = { tag = "master", section = "default_MPI" }\n')
        self.assertEqual(self.errors(text), [])


@NEEDS_TOMLLIB
class TestTomlGrammar(ValidateTestCase):

    def test_a_syntax_error_is_reported_with_its_position(self):
        errors = self.errors('[APPLICATION]\nname "X"\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("line 2", errors[0])

    def test_a_syntax_error_names_the_file(self):
        path = self.write('[APPLICATION\n')
        self.assertIn(path, validate_toml(path)[0])

    def test_a_duplicate_key_is_an_error(self):
        errors = self.errors('[A]\nx = "1"\nx = "2"\n')
        self.assertEqual(len(errors), 1)


@NEEDS_TOMLLIB
class TestSatRules(ValidateTestCase):

    def test_a_boolean_flag_is_rejected_with_its_key(self):
        errors = self.errors('[APPLICATION]\ndebug = false\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("APPLICATION.debug", errors[0])

    def test_a_false_product_is_rejected(self):
        errors = self.errors('[APPLICATION.products]\nSMESH = false\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("APPLICATION.products.SMESH", errors[0])

    def test_an_unterminated_template_is_rejected_with_its_key(self):
        errors = self.errors('[APPLICATION]\nworkdir = "${LOCAL.workdir"\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("APPLICATION.workdir", errors[0])

    def test_a_date_is_rejected(self):
        errors = self.errors('[A]\nwhen = 2026-09-29\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("A.when", errors[0])

    def test_rules_are_checked_inside_sequences(self):
        errors = self.errors('[A]\nx = ["ok", "${bad"]\n')
        self.assertEqual(len(errors), 1)
        self.assertIn("A.x[1]", errors[0])

    def test_every_violation_is_reported_not_only_the_first(self):
        text = ('[APPLICATION]\n'
                'debug = false\n'
                'workdir = "${oops"\n'
                '[APPLICATION.products]\n'
                'SMESH = false\n')
        self.assertEqual(len(self.errors(text)), 3)


class TestFileChecks(ValidateTestCase):

    def test_a_missing_file_is_an_error(self):
        errors = validate_toml(os.path.join(self.tmp, "absent.toml"))
        self.assertEqual(len(errors), 1)
        self.assertIn("absent.toml", errors[0])

    def test_a_non_toml_extension_is_an_error(self):
        errors = validate_toml(self.write("A : { x : 1 }\n", "a.pyconf"))
        self.assertEqual(len(errors), 1)
        self.assertIn(".toml", errors[0])


@NEEDS_TOMLLIB
class TestCommand(ValidateTestCase):
    """`sat config --validate FILE`: exit status and output."""

    def sat(self, *args):
        return subprocess.run(
            [sys.executable, os.path.join(SATDIR, "sat"), "config"] + list(args),
            capture_output=True, text=True, cwd=SATDIR)

    def test_a_valid_file_exits_zero(self):
        result = self.sat("--validate", FIXTURE)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)

    def test_an_invalid_file_exits_non_zero_and_prints_the_error(self):
        path = self.write('[APPLICATION]\ndebug = false\n')
        result = self.sat("--validate", path)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APPLICATION.debug", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
