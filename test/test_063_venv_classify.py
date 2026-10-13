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


import shutil
import tempfile
import unittest

import initializeTest # set PATH etc for test
import venv_fixture as VF
import src.venv as VENV


class TestSplit(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.paths = VF.make_fake_project(self.root)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def test_groups(self):
        cfg = VF.load_config(self.paths["data"])
        venv_products, system_products = VENV.split_native_products(cfg)
        self.assertEqual(venv_products, [("pipnative", "toml")])
        self.assertEqual([k for k, _ in system_products],
                         ["Python", "nopipnative", "sysnative"])

    def test_non_native_excluded(self):
        cfg = VF.load_config(self.paths["data"])
        venv_products, system_products = VENV.split_native_products(cfg)
        keys = [k for k, _ in venv_products] + [k for k, _ in system_products]
        self.assertNotIn("fakepkg", keys)

    def test_requirements_unpinned(self):
        cfg = VF.load_config(self.paths["data"])
        venv_products, _ = VENV.split_native_products(cfg)
        reqs = VENV.get_requirements(cfg, venv_products, VF.FakeLogger())
        self.assertEqual(reqs, {"pipnative": "toml"})

    def test_requirements_pinned(self):
        cfg = VF.load_config(self.paths["data"],
                             ["APPLICATION.venv={'pipnative' : '0.10.2'}"])
        venv_products, _ = VENV.split_native_products(cfg)
        reqs = VENV.get_requirements(cfg, venv_products, VF.FakeLogger())
        self.assertEqual(reqs, {"pipnative": "toml==0.10.2"})

    def test_pin_outside_group_warns(self):
        cfg = VF.load_config(self.paths["data"],
                             ["APPLICATION.venv={'sysnative' : '1.0'}"])
        venv_products, _ = VENV.split_native_products(cfg)
        logger = VF.FakeLogger()
        reqs = VENV.get_requirements(cfg, venv_products, logger)
        self.assertEqual(reqs, {"pipnative": "toml"})
        self.assertIn("WARNING", logger.text)
        self.assertIn("sysnative", logger.text)


if __name__ == '__main__':
    unittest.main()
