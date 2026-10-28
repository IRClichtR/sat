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

import initializeTest # set PATH etc for test
import venv_fixture as VF
import src
import src.environment
import src.venv as VENV


def fake_venv(path):
    """A directory that passes is_venv (enough for environment tests)."""
    os.makedirs(os.path.join(path, "bin"))
    with open(os.path.join(path, "pyvenv.cfg"), "w") as f:
        f.write("include-system-site-packages = true\n")
    open(VENV.venv_python(path), "w").close()
    return path


def build_env(cfg, products, for_build=True):
    env = src.environment.SalomeEnviron(cfg, src.environment.Environ({}),
                                        forBuild=for_build)
    env.silent = True
    env.set_full_environ(VF.FakeLogger(), products)
    return env.environ.environ


class TestApplyVenvEnv(unittest.TestCase):

    def test_overrides_only_the_four_variables(self):
        env = src.environment.Environ({"PATH": "/usr/bin",
                                       "PYTHON_ROOT_DIR": "/usr",
                                       "PYTHON_INCLUDE": "/usr/include/python3"})
        VENV.apply_venv_env(env, "/v")
        py = VENV.venv_python("/v")
        self.assertEqual(env.get("VIRTUAL_ENV"), "/v")
        self.assertTrue(env.get("PATH").startswith(VENV.venv_bin_dir("/v") + os.pathsep))
        self.assertEqual(env.get("PYTHONBIN"), py)
        self.assertEqual(env.get("Python3_EXECUTABLE"), py)
        self.assertEqual(env.get("PYTHON_ROOT_DIR"), "/usr")
        self.assertEqual(env.get("PYTHON_INCLUDE"), "/usr/include/python3")


class TestEnableVenvMode(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.venv_dir = fake_venv(os.path.join(self.root, "venv"))
        self.paths = VF.make_fake_project(self.root,
                                          local_extra="venv : '%s'" % self.venv_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_native_python(self):
        cfg = VF.load_config(self.paths["data"])
        self.assertEqual(VENV.enable_venv_mode(cfg, VF.FakeLogger()), self.venv_dir)
        self.assertEqual(cfg.VARS.venv_dir, self.venv_dir)

    def test_compiled_python_refused(self):
        cfg = VF.load_config(self.paths["data"],
                             ["APPLICATION.products.Python='3.12.0'"])
        with self.assertRaises(src.SatException) as ctx:
            VENV.enable_venv_mode(cfg, VF.FakeLogger())
        self.assertIn("already isolated", str(ctx.exception))
        self.assertNotIn("venv_dir", cfg.VARS)

    def test_enable_requires_python_declared(self):
        # Review Focus 4
        cfg = VF.load_config(self.paths["data"])
        del cfg.APPLICATION.products["Python"]
        with self.assertRaises(src.SatException) as ctx:
            VENV.enable_venv_mode(cfg, VF.FakeLogger())
        self.assertIn("Python", str(ctx.exception))


class TestEnvironmentHook(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.venv_dir = fake_venv(os.path.join(self.root, "venv"))
        self.paths = VF.make_fake_project(self.root,
                                          local_extra="venv : '%s'" % self.venv_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def check_venv_env(self, env):
        py = VENV.venv_python(self.venv_dir)
        self.assertEqual(env["VIRTUAL_ENV"], self.venv_dir)
        self.assertEqual(env["PYTHONBIN"], py)
        self.assertEqual(env["Python3_EXECUTABLE"], py)
        self.assertTrue(env["PATH"].startswith(VENV.venv_bin_dir(self.venv_dir)))
        self.assertEqual(env["PYTHON_ROOT_DIR"], "/usr")             # D12
        self.assertEqual(env["PYTHON_INCLUDE"], "/usr/include/python3")

    def test_build_env_in_venv_mode(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, VF.FakeLogger())
        self.check_venv_env(build_env(cfg, ["Python", "pipnative"], True))

    def test_launch_env_in_venv_mode(self):
        cfg = VF.load_config(self.paths["data"])
        VENV.enable_venv_mode(cfg, VF.FakeLogger())
        self.check_venv_env(build_env(cfg, ["Python", "pipnative"], False))

    def test_without_venv_mode_unchanged(self):
        # non-regression: LOCAL.venv is set, but --venv is not given
        cfg = VF.load_config(self.paths["data"])
        env = build_env(cfg, ["Python", "pipnative"], True)
        self.assertNotIn("VIRTUAL_ENV", env)
        self.assertNotIn("Python3_EXECUTABLE", env)
        self.assertEqual(env["PYTHONBIN"], "/usr/bin/python3")
        self.assertNotIn(self.venv_dir, env.get("PATH", ""))


class SwitchScenario(object):
    """D17: a product compiled from FTP (archive) or git becomes a pip
    package installed in the venv, then back. Mixed into two TestCases."""

    fakepkg_source = None
    NATIVE = ["APPLICATION.products.fakepkg='native'"]

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.venv_dir = fake_venv(os.path.join(self.root, "venv"))
        self.paths = VF.make_fake_project(self.root, self.fakepkg_source,
                                          local_extra="venv : '%s'" % self.venv_dir)
        # stale install of a previous compiled build
        compiled = src.product.get_product_config(
            VF.load_config(self.paths["data"]), "fakepkg")
        self.stale = os.path.join(compiled.install_dir, "lib", "site-packages")
        os.makedirs(self.stale)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_switch_classification(self):
        cfg = VF.load_config(self.paths["data"])
        venv_products, system_products = VENV.split_native_products(cfg)
        self.assertNotIn("fakepkg", [k for k, _ in venv_products + system_products])
        cfg = VF.load_config(self.paths["data"], self.NATIVE)
        venv_products, _ = VENV.split_native_products(cfg)
        self.assertIn(("fakepkg", "six"), venv_products)

    def test_switch_one_command(self):
        # no file edited: only -o switches, and dropping -o switches back
        before = open(os.path.join(self.paths["proj"], "applications",
                                   "VENVTEST.pyconf")).read()
        cfg = VF.load_config(self.paths["data"], self.NATIVE)
        self.assertTrue(src.product.product_is_native(
            src.product.get_product_config(cfg, "fakepkg")))
        cfg = VF.load_config(self.paths["data"])
        self.assertFalse(src.product.product_is_native(
            src.product.get_product_config(cfg, "fakepkg")))
        after = open(os.path.join(self.paths["proj"], "applications",
                                  "VENVTEST.pyconf")).read()
        self.assertEqual(before, after)

    def test_switch_no_shadowing(self):
        cfg = VF.load_config(self.paths["data"], self.NATIVE)
        VENV.enable_venv_mode(cfg, VF.FakeLogger())
        env = build_env(cfg, ["Python", "fakepkg"], False)
        for var in env:
            self.assertNotIn(self.stale, str(env[var]), var)
        self.assertEqual(env["PYTHONBIN"], VENV.venv_python(self.venv_dir))

    def test_switch_revert(self):
        cfg = VF.load_config(self.paths["data"])          # compiled again
        VENV.enable_venv_mode(cfg, VF.FakeLogger())
        env = build_env(cfg, ["Python", "fakepkg"], False)
        # PYTHONPATH wins over the venv site-packages: the compiled build is used
        self.assertIn(self.stale, env["PYTHONPATH"].split(os.pathsep))

    def test_switch_install_possible(self):
        if not VF.has_network():
            self.skipTest("needs PyPI")
        venv_dir = os.path.join(self.root, "real_venv")
        self.assertEqual(VENV.create_venv(venv_dir, os.path.join(VF.satdir, "sat"),
                                          VF.FakeLogger()), 0)
        cfg = VF.load_config(self.paths["data"],
                             self.NATIVE + ["APPLICATION.venv={'fakepkg' : '1.15.0'}"])
        venv_products, _ = VENV.split_native_products(cfg)
        reqs = VENV.get_requirements(cfg, venv_products, VF.FakeLogger())
        self.assertEqual(reqs["fakepkg"], "six==1.15.0")
        self.assertEqual(VENV.install_venv_pkgs(cfg, venv_dir, [reqs["fakepkg"]],
                                                VF.FakeLogger()), 0)
        self.assertEqual(VENV.check_venv_pkgs(venv_dir, ["six"])["six"],
                         {"status": "OK", "version": "1.15.0", "origin": "venv"})
        where = subprocess.check_output(
            [VENV.venv_python(venv_dir), "-c", "import six; print(six.__file__)"]
        ).decode().strip()
        self.assertTrue(os.path.realpath(where).startswith(os.path.realpath(venv_dir)))


class TestSwitchFromArchive(SwitchScenario, unittest.TestCase):
    fakepkg_source = "archive"


class TestSwitchFromGit(SwitchScenario, unittest.TestCase):
    fakepkg_source = "git"


if __name__ == '__main__':
    unittest.main()
