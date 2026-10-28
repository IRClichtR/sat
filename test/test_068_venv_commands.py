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


import importlib
import os
import shutil
import tempfile
import unittest

import initializeTest # set PATH etc for test
import venv_fixture as VF
import src
import src.venv as VENV

COMMANDS = ["compile", "configure", "make", "makeinstall", "script",
            "environ", "launcher", "application", "test"]


class TestOptionDeclared(unittest.TestCase):

    def test_every_env_command_has_venv(self):
        for name in COMMANDS:
            module = importlib.import_module("commands." + name)
            names = [o['longName'] for o in module.parser.options]
            self.assertIn("venv", names, name)
            short = [o['shortName'] for o in module.parser.options
                     if o['longName'] == "venv"]
            self.assertEqual(short, [''], name)          # D16: long only

    def test_package_has_no_venv(self):
        module = importlib.import_module("commands.package")
        self.assertNotIn("venv", [o['longName'] for o in module.parser.options])

    def test_parse(self):
        module = importlib.import_module("commands.compile")
        options, _ = module.parser.parse_args(["--venv", "-p", "KERNEL"])
        self.assertTrue(options.venv)
        options, _ = module.parser.parse_args(["-p", "KERNEL"])
        self.assertFalse(options.venv)


class TestHandleVenvOption(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.paths = VF.make_fake_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    class Options(object):
        def __init__(self, venv):
            self.venv = venv

    def test_no_flag_no_effect(self):
        cfg = VF.load_config(self.paths["data"])     # no LOCAL.venv: would raise
        VENV.handle_venv_option(self.Options(None), cfg, VF.FakeLogger())
        self.assertNotIn("venv_dir", cfg.VARS)

    def test_flag_without_init(self):
        cfg = VF.load_config(self.paths["data"])
        with self.assertRaises(src.SatException) as ctx:
            VENV.handle_venv_option(self.Options(True), cfg, VF.FakeLogger())
        self.assertIn("sat init --venv", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
