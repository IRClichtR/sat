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

import os
import shutil
import tempfile
import unittest

try:
    from unittest import mock
except ImportError:
    import mock

import initializeTest # set PATH etc for test
import venv_fixture as VF
import src
import src.venv as VENV


def read_local(paths):
    with open(os.path.join(paths["data"], "local.pyconf")) as f:
        return f.read()


class TestInitVenv(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.paths = VF.make_fake_project(self.root)
        self.cfg = VF.load_config(self.paths["data"])
        self.logger = VF.FakeLogger()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_init_path_creates_and_records(self):
        venv_dir = os.path.join(self.root, "v1")
        self.assertEqual(VENV.init_venv(self.cfg, venv_dir, self.logger), 0,
                         self.logger.text)
        self.assertTrue(VENV.is_venv(venv_dir))
        self.assertIn(venv_dir, read_local(self.paths))
        reloaded = VF.load_config(self.paths["data"])
        self.assertEqual(reloaded.LOCAL.venv, venv_dir)
        self.assertEqual(VENV.resolve_venv_dir(reloaded), venv_dir)

    def test_init_default(self):
        # "sat init --venv" without a path: <workdir>/venv, stored as a path
        default = VENV.default_venv_path(self.cfg)
        self.assertEqual(VENV.init_venv(self.cfg, default, self.logger), 0,
                         self.logger.text)
        reloaded = VF.load_config(self.paths["data"])
        self.assertEqual(reloaded.LOCAL.venv,
                         os.path.join(self.paths["workdir"], "venv"))
        self.assertEqual(VENV.resolve_venv_dir(reloaded),
                         os.path.join(self.paths["workdir"], "venv"))

    def test_default_is_not_a_keyword(self):
        # "default" is an ordinary (relative) directory name now
        self.assertEqual(VENV.resolve_venv_path("default"),
                         os.path.join(os.getcwd(), "default"))

    def test_relative_path_stored_absolute(self):
        cwd = os.getcwd()
        os.chdir(self.root)
        try:
            self.assertEqual(VENV.init_venv(self.cfg, "rel_venv", self.logger), 0)
        finally:
            os.chdir(cwd)
        reloaded = VF.load_config(self.paths["data"])
        self.assertEqual(reloaded.LOCAL.venv, os.path.join(self.root, "rel_venv"))

    def test_init_forget_keeps_dir(self):
        venv_dir = os.path.join(self.root, "v2")
        VENV.init_venv(self.cfg, venv_dir, self.logger)
        cfg = VF.load_config(self.paths["data"])
        self.assertEqual(VENV.init_venv(cfg, "forget", self.logger), 0)
        self.assertNotIn("venv", cfg.LOCAL)
        self.assertNotIn("venv :", read_local(self.paths))
        self.assertTrue(VENV.is_venv(venv_dir))
        reloaded = VF.load_config(self.paths["data"])
        self.assertNotIn("venv", reloaded.LOCAL)

    def test_init_forget_when_unset_is_ok(self):
        self.assertEqual(VENV.init_venv(self.cfg, "forget", self.logger), 0)

    def test_failure_writes_nothing(self):
        before = read_local(self.paths)
        with mock.patch("src.venv.create_venv", return_value=1):
            self.assertEqual(
                VENV.init_venv(self.cfg, os.path.join(self.root, "v3"), self.logger), 1)
        self.assertEqual(read_local(self.paths), before)

    def test_non_venv_dir_refused(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        before = read_local(self.paths)
        self.assertEqual(VENV.init_venv(self.cfg, plain, self.logger), 1)
        self.assertEqual(read_local(self.paths), before)


class TestInitCommandOption(unittest.TestCase):

    def test_init_declares_venv_option(self):
        import commands.init as INIT
        names = [o['longName'] for o in INIT.parser.options]
        self.assertIn('venv', names)

    def parse(self, args):
        import commands.init as INIT
        options, _ = INIT.parser.parse_args(
            INIT.normalize_venv_arg(args, "/work/venv"))
        return options

    def test_bare_venv_is_default_path(self):
        self.assertEqual(self.parse(["--venv"]).venv, "/work/venv")

    def test_bare_venv_followed_by_option(self):
        options = self.parse(["--venv", "-l", "/logs"])
        self.assertEqual(options.venv, "/work/venv")
        self.assertEqual(options.log_dir, "/logs")

    def test_venv_with_path(self):
        self.assertEqual(self.parse(["--venv", "/my/venv"]).venv, "/my/venv")
        self.assertEqual(self.parse(["--venv=/my/venv"]).venv, "/my/venv")

    def test_venv_forget(self):
        self.assertEqual(self.parse(["--venv", "forget"]).venv, "forget")

    def test_no_venv_option_untouched(self):
        self.assertEqual(self.parse(["-l", "/logs"]).venv, None)


if __name__ == '__main__':
    unittest.main()
