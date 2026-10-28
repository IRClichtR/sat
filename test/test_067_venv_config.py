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
import commands.config as CONFIG_CMD

KO = "KO (package is not installed!)\n"
OK = "OK (installed)\n"

# system packages each native product declares in this test
SYS_PKGS = {"sysnative": "libfoo-dev", "pipnative": "python3-toml",
            "fakepkg": "python3-six"}


def fake_check_system_dep(distrib, check_cmd, product_info):
    """KO for every declared package, keyed by product name."""
    pkg = {"sysnative": "libfoo-dev", "toml": "python3-toml",
           "six": "python3-six"}.get(product_info.name)
    return ({pkg: KO} if pkg else {}), {}


class TestOptionRules(unittest.TestCase):

    def test_valid(self):
        for args in [(True, False, False, False), (True, True, False, False),
                     (True, True, True, False), (True, False, False, True),
                     (True, True, True, True), (False, False, False, False),
                     (False, True, False, False)]:
            VENV.check_install_options(*args)   # no exception

    def test_install_venv_requires_venv(self):
        with self.assertRaises(src.SatException) as ctx:
            VENV.check_install_options(True, False, True, False)
        self.assertIn("--install_venv requires --venv", str(ctx.exception))

    def test_install_requires_check_system(self):
        for args in [(False, True, True, False), (False, False, False, True)]:
            with self.assertRaises(src.SatException) as ctx:
                VENV.check_install_options(*args)
            self.assertIn("--install_* requires --check_system", str(ctx.exception))

    def test_config_declares_options(self):
        names = [o['longName'] for o in CONFIG_CMD.parser.options]
        for name in ["venv", "install_venv", "install_system"]:
            self.assertIn(name, names)


class TestCheckInstallSystem(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.venv_dir = os.path.join(self.root, "venv")
        os.makedirs(os.path.join(self.venv_dir, "bin"))
        open(os.path.join(self.venv_dir, "pyvenv.cfg"), "w").close()
        open(VENV.venv_python(self.venv_dir), "w").close()
        self.paths = VF.make_fake_project(self.root,
                                          local_extra="venv : '%s'" % self.venv_dir)
        self.logger = VF.FakeLogger()
        patches = [
            mock.patch("src.system.get_pkg_check_cmd", return_value=["dpkg-query", "-l"]),
            mock.patch("src.product.check_system_dep", side_effect=fake_check_system_dep),
            mock.patch("src.system.get_pkg_install_cmd", return_value=["apt-get", "install", "-y"]),
        ]
        self.mocks = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.check_system_dep = self.mocks[1]

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def checked_products(self):
        return sorted(c[0][2].name for c in self.check_system_dep.call_args_list)

    def test_without_venv_checks_every_native(self):
        cfg = VF.load_config(self.paths["data"])
        rc = CONFIG_CMD.check_install_system(cfg, self.logger)
        self.assertEqual(rc, 0)
        self.assertEqual(self.checked_products(),
                         ["Python", "nopipnative", "sysnative", "toml"])
        self.assertNotIn("Venv packages", self.logger.text)
        self.assertIn("   - libfoo-dev : " + KO, self.logger.text)

    def test_switch_without_venv_untouched(self):
        # D17: switched to native without --venv -> system check, as today
        cfg = VF.load_config(self.paths["data"], ["APPLICATION.products.fakepkg='native'"])
        CONFIG_CMD.check_install_system(cfg, self.logger)
        self.assertIn("six", self.checked_products())

    def test_with_venv_two_groups(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, self.logger)
        ko = {"toml": {"status": "KO", "version": None, "origin": None}}
        with mock.patch("src.venv.check_venv_pkgs", return_value=ko):
            rc = CONFIG_CMD.check_install_system(cfg, self.logger, venv=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.checked_products(), ["Python", "nopipnative", "sysnative"])
        self.assertIn("System packages (dpkg-query)", self.logger.text)
        self.assertIn("Venv packages (pip, %s)" % self.venv_dir, self.logger.text)
        self.assertIn("pipnative", self.logger.text)

    def test_install_venv(self):
        cfg = VF.load_config(self.paths["data"],
                             ["APPLICATION.venv={'pipnative' : '0.10.2'}"])
        VENV.enable_venv_mode(cfg, self.logger)
        ko = {"toml": {"status": "KO", "version": None, "origin": None}}
        ok = {"toml": {"status": "OK", "version": "0.10.2", "origin": "venv"}}
        with mock.patch("src.venv.check_venv_pkgs", side_effect=[ko, ok]), \
             mock.patch("src.venv.install_venv_pkgs", return_value=0) as install:
            rc = CONFIG_CMD.check_install_system(cfg, self.logger, venv=True,
                                                 install_venv=True)
        self.assertEqual(rc, 0)
        install.assert_called_once_with(cfg, self.venv_dir, ["toml==0.10.2"], self.logger)
        self.assertIn("(venv 0.10.2)", self.logger.text)   # "OK" may carry color codes

    def _run_pinned(self, version, extra_pins="", **kwargs):
        cfg = VF.load_config(self.paths["data"],
                             ["APPLICATION.venv={'pipnative' : '0.10.2'%s}" % extra_pins])
        VENV.enable_venv_mode(cfg, self.logger)
        seen = {"toml": {"status": "OK", "version": version, "origin": "system"}}
        ok = {"toml": {"status": "OK", "version": "0.10.2", "origin": "venv"}}
        with mock.patch("src.venv.check_venv_pkgs", side_effect=[seen, ok]), \
             mock.patch("src.venv.install_venv_pkgs", return_value=0) as install:
            rc = CONFIG_CMD.check_install_system(cfg, self.logger, venv=True, **kwargs)
        return rc, install

    def test_pin_differs_plain_check(self):
        rc, install = self._run_pinned("0.9.0")
        self.assertEqual(rc, 0)
        install.assert_not_called()
        self.assertIn("(system 0.9.0, pinned 0.10.2)", self.logger.text)
        self.assertIn("Install them with", self.logger.text)

    def test_pin_differs_installs_pin(self):
        rc, install = self._run_pinned("0.9.0", install_venv=True)
        self.assertEqual(rc, 0)
        self.assertEqual(install.call_args[0][2], ["toml==0.10.2"])
        self.assertIn("pinned 0.10.2", self.logger.text)

    def test_pin_equal_is_ok(self):
        rc, install = self._run_pinned("0.10.2", install_venv=True)
        self.assertEqual(rc, 0)
        install.assert_not_called()
        self.assertIn("(system 0.10.2)", self.logger.text)
        self.assertNotIn("pinned", self.logger.text)

    def test_pin_warning_once(self):
        rc, install = self._run_pinned("0.9.0", extra_pins=", 'nopipnative' : '1'",
                                       install_venv=True)
        self.assertEqual(self.logger.text.count("APPLICATION.venv.nopipnative is ignored"), 1)

    def test_pin_warning_plain_check(self):
        self._run_pinned("0.10.2", extra_pins=", 'nopipnative' : '1'")
        self.assertEqual(self.logger.text.count("APPLICATION.venv.nopipnative is ignored"), 1)

    def test_install_venv_still_missing(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, self.logger)
        ko = {"toml": {"status": "KO", "version": None, "origin": None}}
        with mock.patch("src.venv.check_venv_pkgs", side_effect=[ko, ko]), \
             mock.patch("src.venv.install_venv_pkgs", return_value=1):
            rc = CONFIG_CMD.check_install_system(cfg, self.logger, venv=True,
                                                 install_venv=True)
        self.assertEqual(rc, 1)

    def test_install_system_with_venv_only_system_group(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, self.logger)
        ok = {"toml": {"status": "OK", "version": "1", "origin": "venv"}}
        with mock.patch("src.venv.check_venv_pkgs", return_value=ok), \
             mock.patch("src.system.install_system_pkgs", return_value=0) as install:
            CONFIG_CMD.check_install_system(cfg, self.logger, venv=True,
                                            install_system=True, batch=True)
        args = install.call_args[0]
        self.assertEqual(args[0], ["libfoo-dev"])
        self.assertEqual(args[1], ["apt-get", "install", "-y"])
        self.assertEqual(args[2], True)     # batch passed through

    def test_install_system_without_venv_all_native(self):
        cfg = VF.load_config(self.paths["data"])
        with mock.patch("src.system.install_system_pkgs", return_value=1) as install:
            rc = CONFIG_CMD.check_install_system(cfg, self.logger, install_system=True)
        self.assertEqual(install.call_args[0][0], ["libfoo-dev", "python3-toml"])
        self.assertEqual(rc, 1)

    def test_broken_venv_clear_error(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, self.logger)
        with mock.patch("src.venv.check_venv_pkgs", side_effect=OSError("no interpreter")):
            with self.assertRaises(src.SatException) as ctx:
                CONFIG_CMD.check_install_system(cfg, self.logger, venv=True)
        self.assertIn("sat init --venv", str(ctx.exception))
        self.assertIn(self.venv_dir, str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
