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
Integration tests for the lock gate in ConfigManager.get_config.

The first class is the one that must never be weakened: a configuration with no
TOML layer leaves get_config by the route it always has. The rest exercise the
gate, using a TOML application placed on APPLICATIONPATH for the duration of a
test and removed afterwards.
"""

import os
import shutil
import sys
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from commands.config import ConfigManager
from src.configio.lock import LOCK_KEY, SECTION_KEY

SATDIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APPLI_DIR = os.path.join(SATDIR, "test", "APPLI_TEST")
FIXTURE = os.path.join(SATDIR, "test", "configio_fixtures", "APPLI_TEST.toml")

NEEDS_TOMLLIB = unittest.skipIf(sys.version_info[:2] < (3, 11),
                                "tomllib is stdlib from Python 3.11")


class Options(object):
    """The subset of sat's global options get_config reads."""

    def __init__(self, overwrite=None, relock=False):
        self.overwrite = overwrite
        self.relock = relock


class TestPurePyconfIsUntouched(unittest.TestCase):
    """The global constraint. If this needs weakening, stop and escalate."""

    def test_no_lock_is_written(self):
        manager = ConfigManager()
        cfg = manager.get_config(application="APPLI_TEST")
        self.assertEqual(cfg.APPLICATION.name, "APPLI_TEST")
        self.assertFalse(os.path.exists(
            os.path.join(cfg.LOCAL.workdir, ".sat",
                         "APPLI_TEST.lock.json")))

    def test_the_lock_header_is_absent_from_the_returned_config(self):
        cfg = ConfigManager().get_config(application="APPLI_TEST")
        self.assertNotIn(LOCK_KEY, cfg.keys())

    def test_products_keep_their_section_families(self):
        # collapse_products must not have run: KERNEL still has named sections
        cfg = ConfigManager().get_config(application="APPLI_TEST")
        self.assertNotIn(SECTION_KEY, cfg.PRODUCTS.KERNEL.keys())
        self.assertIn("default", cfg.PRODUCTS.KERNEL.keys())

    def test_sources_are_still_recorded(self):
        # the lock is not used, but discovery runs for every configuration
        manager = ConfigManager()
        manager.get_config(application="APPLI_TEST")
        self.assertGreater(len(manager.sources), 5)
        for entry in manager.sources:
            self.assertTrue(os.path.isfile(entry[0]))
            self.assertEqual(len(entry), 3)

    def test_no_toml_layer_is_detected(self):
        manager = ConfigManager()
        manager.get_config(application="APPLI_TEST")
        self.assertEqual(manager.toml_layers, [])


@NEEDS_TOMLLIB
class TestTomlApplicationGoesThroughTheLock(unittest.TestCase):
    """A TOML layer routes the whole configuration through the lock."""

    NAME = "TOMLAPP"

    def setUp(self):
        # APPLI_TEST is on APPLICATIONPATH for the unit tests
        # (commands/config.py appends it), so a .toml placed there is
        # discovered. A distinct name keeps it from colliding with the
        # pyconf fixture, which task 7 would otherwise call ambiguous.
        self.appli = os.path.join(APPLI_DIR, self.NAME + ".toml")
        shutil.copyfile(FIXTURE, self.appli)
        text = open(self.appli).read().replace('"APPLI_TEST"',
                                               '"%s"' % self.NAME)
        with open(self.appli, "w") as stream:
            stream.write(text)
        self.lock = None

    def tearDown(self):
        if os.path.exists(self.appli):
            os.remove(self.appli)
        if self.lock and os.path.exists(self.lock):
            shutil.rmtree(os.path.dirname(self.lock), ignore_errors=True)

    def load(self, options=None):
        manager = ConfigManager()
        cfg = manager.get_config(application=self.NAME,
                                 options=options or Options())
        self.lock = os.path.join(cfg.LOCAL.workdir, ".sat",
                                 "%s.lock.json" % self.NAME)
        return manager, cfg

    def test_the_toml_layer_is_detected(self):
        manager, cfg = self.load()
        self.assertEqual(len(manager.toml_layers), 1)
        self.assertTrue(manager.toml_layers[0].endswith(".toml"))

    def test_a_lock_is_written(self):
        self.load()
        self.assertTrue(os.path.isfile(self.lock))

    def test_the_returned_config_came_from_the_lock(self):
        # the lock is the artifact SAT executes against, so the returned tree
        # must be the one read back from it, header and all
        manager, cfg = self.load()
        self.assertIn(LOCK_KEY, cfg.keys())

    def test_the_application_still_resolves_correctly(self):
        manager, cfg = self.load()
        self.assertEqual(cfg.APPLICATION.name, self.NAME)
        # workdir is ${LOCAL.workdir}${VARS.sep}${APPLICATION.name}-${VARS.dist}
        self.assertIn(self.NAME, cfg.APPLICATION.workdir)
        self.assertTrue(cfg.APPLICATION.workdir.startswith(cfg.LOCAL.workdir))
        self.assertTrue(cfg.APPLICATION.workdir.endswith(cfg.VARS.dist))

    def test_products_are_collapsed(self):
        manager, cfg = self.load()
        self.assertIn(SECTION_KEY, cfg.PRODUCTS.KERNEL.keys())
        self.assertNotIn("default", cfg.PRODUCTS.KERNEL.keys())

    def test_install_dir_is_present_so_references_to_it_resolved(self):
        manager, cfg = self.load()
        self.assertIn("install_dir", cfg.PRODUCTS.KERNEL.keys())

    def test_the_header_records_the_sources(self):
        manager, cfg = self.load()
        self.assertGreater(len(cfg[LOCK_KEY].sources), 5)

    def test_a_second_load_reuses_the_lock(self):
        first, _ = self.load()
        mtime = os.path.getmtime(self.lock)
        second, cfg = self.load()
        self.assertEqual(os.path.getmtime(self.lock), mtime,
                         "the lock was rewritten although nothing changed")
        self.assertEqual(cfg.APPLICATION.name, self.NAME)

    def test_relock_regenerates_it(self):
        self.load()
        os.utime(self.lock, (0, 0))
        stale_mtime = os.path.getmtime(self.lock)
        self.load(Options(relock=True))
        self.assertNotEqual(os.path.getmtime(self.lock), stale_mtime)

    def test_editing_the_source_invalidates_the_lock(self):
        # the wiki tells users to edit the application file to set debug mode,
        # so this is the documented path, not an edge case
        self.load()
        first = os.path.getmtime(self.lock)
        os.utime(self.lock, (0, 0))
        with open(self.appli, "a") as stream:
            stream.write('\n[APPLICATION.extra]\nk = "v"\n')
        manager, cfg = self.load()
        self.assertNotEqual(os.path.getmtime(self.lock), 0)
        self.assertEqual(cfg.APPLICATION.extra.k, "v")

    def test_a_different_override_invalidates_the_lock(self):
        # tuleap vs github: same files, different configuration
        self.load(Options(overwrite=["APPLICATION.debug='no'"]))
        os.utime(self.lock, (0, 0))
        self.load(Options(overwrite=["APPLICATION.debug='yes'"]))
        self.assertNotEqual(os.path.getmtime(self.lock), 0)

    def test_the_same_override_reuses_the_lock(self):
        rules = ["APPLICATION.debug='no'"]
        self.load(Options(overwrite=rules))
        mtime = os.path.getmtime(self.lock)
        self.load(Options(overwrite=rules))
        self.assertEqual(os.path.getmtime(self.lock), mtime)


if __name__ == '__main__':
    unittest.main()
