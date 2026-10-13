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
import src.venv as VENV


class TestVenvPkgs(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        cls.paths = VF.make_fake_project(cls.root)
        cls.cfg = VF.load_config(cls.paths["data"])
        cls.venv_dir = os.path.join(cls.root, "venv")
        assert VENV.create_venv(cls.venv_dir, os.path.join(VF.satdir, "sat"),
                                VF.FakeLogger()) == 0
        # a fake installed distribution, to test name normalisation offline
        purelib = subprocess.check_output(
            [VENV.venv_python(cls.venv_dir), "-c",
             "import sysconfig; print(sysconfig.get_paths()['purelib'])"]
        ).decode().strip()
        info = os.path.join(purelib, "foo_bar-1.2.dist-info")
        os.makedirs(info)
        with open(os.path.join(info, "METADATA"), "w") as f:
            f.write("Metadata-Version: 2.1\nName: foo_bar\nVersion: 1.2\n")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def test_check_installed_in_venv(self):
        res = VENV.check_venv_pkgs(self.venv_dir, ["pip"])
        self.assertEqual(res["pip"]["status"], "OK")
        self.assertEqual(res["pip"]["origin"], "venv")
        self.assertTrue(res["pip"]["version"])

    def test_check_missing(self):
        res = VENV.check_venv_pkgs(self.venv_dir, ["sat-no-such-package"])
        self.assertEqual(res["sat-no-such-package"],
                         {"status": "KO", "version": None, "origin": None})

    def test_check_normalises_names(self):
        # Review Focus 2: case, "-", "_" and "." are equivalent (PEP 503)
        res = VENV.check_venv_pkgs(self.venv_dir, ["PIP", "foo-bar", "Foo.Bar"])
        for name in ["PIP", "foo-bar", "Foo.Bar"]:
            self.assertEqual(res[name]["status"], "OK", name)
        self.assertEqual(res["foo-bar"]["version"], "1.2")

    def test_check_system_origin(self):
        # with --system-site-packages, a system-only package is visible
        res = VENV.check_venv_pkgs(self.venv_dir, ["distro"])
        if res["distro"]["status"] == "OK" and res["distro"]["origin"] == "system":
            self.assertIsNotNone(res["distro"]["version"])
        else:
            self.skipTest("distro is not a system-only package here")

    def test_install_nothing_to_do(self):
        # Review Focus 3
        with mock.patch("subprocess.call") as call:
            self.assertEqual(
                VENV.install_venv_pkgs(self.cfg, self.venv_dir, [], VF.FakeLogger()), 0)
            call.assert_not_called()

    def test_install_pinned_and_cached(self):
        if not VF.has_network():
            self.skipTest("needs PyPI")
        logger = VF.FakeLogger()
        failures = VENV.install_venv_pkgs(self.cfg, self.venv_dir,
                                          ["toml==0.10.1"], logger)
        self.assertEqual(failures, 0, logger.text)
        res = VENV.check_venv_pkgs(self.venv_dir, ["toml"])
        self.assertEqual(res["toml"], {"status": "OK", "version": "0.10.1",
                                       "origin": "venv"})
        wheels = os.path.join(self.cfg.LOCAL.archive_dir, "wheels")
        self.assertTrue(any(f.startswith("toml") for f in os.listdir(wheels)))

    def test_install_keeps_going_after_failure(self):
        if not VF.has_network():
            self.skipTest("needs PyPI")
        logger = VF.FakeLogger()
        failures = VENV.install_venv_pkgs(
            self.cfg, self.venv_dir,
            ["sat-no-such-package==0.0.1", "six"], logger)
        self.assertEqual(failures, 1)
        self.assertIn("sat-no-such-package", logger.text)
        self.assertEqual(VENV.check_venv_pkgs(self.venv_dir, ["six"])["six"]["status"], "OK")


REAL_PROJECT = os.environ.get("SAT_TEST_PROJECT", "")
REAL_APP = os.environ.get("SAT_TEST_APP", "MEDCOUPLING-9.15.0-native")


@unittest.skipUnless(REAL_PROJECT and os.path.isfile(REAL_PROJECT),
                     "opt-in: set SAT_TEST_PROJECT=<project pyconf> (and SAT_TEST_APP)")
class TestRealApplication(unittest.TestCase):
    """Check and pip-install the venv group of a real application."""

    @classmethod
    def setUpClass(cls):
        if not VF.has_network():
            raise unittest.SkipTest("needs PyPI")
        cls.root = tempfile.mkdtemp()
        data = os.path.join(cls.root, "data")
        os.makedirs(data)
        with open(os.path.join(data, "local.pyconf"), "w") as f:
            f.write("LOCAL : { base : 'default' workdir : '%s' log_dir : '%s' "
                    "archive_dir : '%s' VCS : 'unknown' tag : 'unknown' }\n"
                    "PROJECTS : { project_file_paths : ['%s'] }\n"
                    % (os.path.join(cls.root, "work"), os.path.join(cls.root, "logs"),
                       os.path.join(cls.root, "archives"), REAL_PROJECT))
        cls.cfg = VF.load_config(data, application=REAL_APP)
        cls.venv_dir = os.path.join(cls.root, "venv")
        assert VENV.create_venv(cls.venv_dir, os.path.join(VF.satdir, "sat"),
                                VF.FakeLogger()) == 0
        cls.venv_products, _ = VENV.split_native_products(cls.cfg)
        cls.requirements = VENV.get_requirements(cls.cfg, cls.venv_products,
                                                 VF.FakeLogger())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def table(self, status):
        lines = []
        for key, name in self.venv_products:
            st = status[name]
            lines.append("%-26s %-26s %-3s %-8s %s" % (key, name, st["status"],
                         st["origin"] or "-", st["version"] or "-"))
        return "\n".join(lines)

    def test_check_install_check(self):
        names = [name for _, name in self.venv_products]
        self.assertTrue(names, "no venv product in %s" % REAL_APP)
        before = VENV.check_venv_pkgs(self.venv_dir, names)
        missing = [key for key, name in self.venv_products
                   if before[name]["status"] == "KO"]
        logger = VF.FakeLogger()
        failures = VENV.install_venv_pkgs(self.cfg, self.venv_dir,
                                          [self.requirements[k] for k in missing],
                                          logger)
        after = VENV.check_venv_pkgs(self.venv_dir, names)
        report = ("application %s, venv %s\n\nBEFORE\n%s\n\nAFTER\n%s\n\n"
                  "install failures: %d\n%s"
                  % (REAL_APP, self.venv_dir, self.table(before), self.table(after),
                     failures, logger.text))
        if os.environ.get("SAT_TEST_REPORT"):
            with open(os.environ["SAT_TEST_REPORT"], "w") as f:
                f.write(report)
        still_missing = [key for key, name in self.venv_products
                         if after[name]["status"] == "KO"]
        self.assertEqual(still_missing, [], report)
        self.assertEqual(failures, 0, report)

if __name__ == '__main__':
    unittest.main()
