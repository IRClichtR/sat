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
import subprocess
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


class TestPaths(unittest.TestCase):

    def test_layout_linux(self):
        with mock.patch("src.architecture.is_windows", return_value=False):
            self.assertEqual(VENV.venv_bin_dir("/v"), os.path.join("/v", "bin"))
            self.assertEqual(VENV.venv_python("/v"), os.path.join("/v", "bin", "python"))

    def test_layout_windows(self):
        with mock.patch("src.architecture.is_windows", return_value=True):
            self.assertEqual(VENV.venv_bin_dir("/v"), os.path.join("/v", "Scripts"))
            self.assertEqual(VENV.venv_python("/v"), os.path.join("/v", "Scripts", "python.exe"))


class TestResolve(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _config(self, local_extra=""):
        paths = VF.make_fake_project(self.root, local_extra=local_extra)
        return VF.load_config(paths["data"]), paths

    def test_resolve_default(self):
        cfg, paths = self._config()
        self.assertEqual(VENV.resolve_venv_path(cfg, "default"),
                         os.path.join(paths["workdir"], "venv"))

    def test_resolve_path_is_absolute(self):
        cfg, _ = self._config()
        self.assertTrue(os.path.isabs(VENV.resolve_venv_path(cfg, "relative/venv")))

    def test_resolve_venv_dir_unset(self):
        cfg, _ = self._config()
        with self.assertRaises(src.SatException) as ctx:
            VENV.resolve_venv_dir(cfg)
        self.assertIn("sat init --venv", str(ctx.exception))

    def test_resolve_venv_dir_deleted(self):
        # Review Focus 5: LOCAL.venv set, directory gone
        gone = os.path.join(self.root, "gone")
        cfg, _ = self._config("venv : '%s'" % gone)
        with self.assertRaises(src.SatException) as ctx:
            VENV.resolve_venv_dir(cfg)
        self.assertIn(gone, str(ctx.exception))
        self.assertIn("sat init --venv", str(ctx.exception))

    def test_resolve_venv_dir_not_a_venv(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        cfg, _ = self._config("venv : '%s'" % plain)
        with self.assertRaises(src.SatException):
            VENV.resolve_venv_dir(cfg)


class TestCreateVenv(unittest.TestCase):
    """One real venv for the whole class (creation takes a few seconds)."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        cls.venv_dir = os.path.join(cls.root, "my venv")   # space on purpose
        cls.sat_path = os.path.join(VF.satdir, "sat")
        cls.logger = VF.FakeLogger()
        cls.rc = VENV.create_venv(cls.venv_dir, cls.sat_path, cls.logger)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_created(self):
        self.assertEqual(self.rc, 0, self.logger.text)
        self.assertTrue(VENV.is_venv(self.venv_dir))

    def test_system_site_packages(self):
        with open(os.path.join(self.venv_dir, "pyvenv.cfg")) as f:
            self.assertIn("include-system-site-packages = true", f.read())

    def test_wrapper_runs_sat(self):
        wrapper = os.path.join(VENV.venv_bin_dir(self.venv_dir), "sat")
        self.assertTrue(os.access(wrapper, os.X_OK))
        # wrapper path contains a space (Review Focus 1)
        out = subprocess.check_output([wrapper, "--help"], stderr=subprocess.STDOUT)
        self.assertIn(b"config", out)

    def test_distro_importable(self):
        rc = subprocess.call([VENV.venv_python(self.venv_dir), "-c", "import distro"])
        if rc != 0 and not VF.has_network():
            self.skipTest("distro neither on the system nor installable offline")
        self.assertEqual(rc, 0)

    def test_idempotent(self):
        logger = VF.FakeLogger()
        self.assertEqual(VENV.create_venv(self.venv_dir, self.sat_path, logger), 0)
        self.assertIn("Reusing", logger.text)

    def test_existing_non_venv_dir(self):
        plain = os.path.join(self.root, "plain")
        os.makedirs(plain)
        logger = VF.FakeLogger()
        self.assertEqual(VENV.create_venv(plain, self.sat_path, logger), 1)
        self.assertFalse(VENV.is_venv(plain))


if __name__ == '__main__':
    unittest.main()
