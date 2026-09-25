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
Unit tests for the lock branch in src.product.get_product_config.

A lock exists so that a decision made once stays made. If section selection
re-runs against a collapsed tree and happens to agree, there are two
implementations agreeing by luck; the day they disagree the lock says one thing
and the runtime does another.

The third class is the one that matters most: it encodes the global constraint
that a configuration with no lock behaves exactly as it does today.
"""

import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
# src.salomeTools installs gettext at import (line 76), which is what makes _()
# available to src.product's messages. commands/__init__.py looks like it does
# this too, but lines 2-41 of that file are one docstring, so it is inert.
import src.salomeTools  # noqa: F401
import src
import src.pyconf as PYF
import src.product as PROD
from src.configio.lock import SECTION_KEY


def locked_config(get_source="archive"):
    """A config shaped as if it came from a lock: boost already collapsed."""
    cfg = PYF.Config()
    # get_salometool_version reads LOCAL.tag during the derivation that runs
    # after selection, in both branches (src/product.py:176)
    cfg.addMapping("LOCAL", PYF.Mapping(cfg), "")
    cfg.LOCAL["tag"] = "5.3.0"
    # get_config builds PATHS for every run (commands/config.py:~409); the
    # archive and script lookups in the derivation read it
    cfg.addMapping("PATHS", PYF.Mapping(cfg), "")
    cfg.PATHS["ARCHIVEPATH"] = PYF.Sequence(cfg.PATHS)
    cfg.PATHS["PRODUCTPATH"] = PYF.Sequence(cfg.PATHS)
    cfg.addMapping("APPLICATION", PYF.Mapping(cfg), "")
    cfg.APPLICATION.addMapping("products", PYF.Mapping(cfg.APPLICATION), "")
    cfg.APPLICATION.products["boost"] = "1.71.0"
    cfg.APPLICATION["tag"] = "master"
    cfg.addMapping("PRODUCTS", PYF.Mapping(cfg), "")
    cfg.PRODUCTS.addMapping("boost", PYF.Mapping(cfg.PRODUCTS), "")
    block = cfg.PRODUCTS.boost
    block[SECTION_KEY] = "version_1_71_0"
    block["name"] = "boost"
    block["build_source"] = "cmake"   # "script" would require a compil_script file
    block["get_source"] = get_source
    # collapse_products copies from_file out of the section, because
    # get_product_section puts it there; a real lock always carries it
    block["from_file"] = "/fake/products/boost.pyconf"
    return cfg


def unlocked_config():
    """The same product as an ordinary pyconf tree, with a default section."""
    cfg = locked_config()
    del cfg.PRODUCTS.boost[SECTION_KEY]
    boost = cfg.PRODUCTS.boost
    boost.addMapping("default", PYF.Mapping(boost), "")
    boost.default["name"] = "boost"
    boost.default["build_source"] = "cmake"
    boost.default["get_source"] = "archive"
    boost["from_file"] = "/fake/products/boost.pyconf"
    return cfg


class TestLockedProduct(unittest.TestCase):
    """With a marker, the stored block is used verbatim."""

    def test_the_stored_section_is_used(self):
        info = PROD.get_product_config(locked_config(), "boost",
                                       with_install_dir=False)
        self.assertEqual(info.section, "version_1_71_0")
        self.assertEqual(info.name, "boost")

    def test_selection_does_not_re_run(self):
        called = []
        original = PROD.get_product_section
        PROD.get_product_section = (
            lambda *a, **k: called.append(a) or original(*a, **k))
        try:
            PROD.get_product_config(locked_config(), "boost",
                                    with_install_dir=False)
        finally:
            PROD.get_product_section = original
        self.assertEqual(called, [],
                         "selection must not re-run for a locked product")

    def test_from_file_is_set_because_downstream_reads_it(self):
        info = PROD.get_product_config(locked_config(), "boost",
                                       with_install_dir=False)
        self.assertIn("from_file", info)


class TestDerivationStillRuns(unittest.TestCase):
    """The branch replaces selection only. Everything after it still happens."""

    def test_sat_version_is_still_attached(self):
        info = PROD.get_product_config(locked_config(), "boost",
                                       with_install_dir=False)
        self.assertIn("sat_version", info)

    def test_a_vcs_product_still_gets_its_tag(self):
        cfg = locked_config(get_source="git")
        block = cfg.PRODUCTS.boost
        block.addMapping("git_info", PYF.Mapping(block), "")
        block.git_info["repo"] = "https://example/boost.git"
        info = PROD.get_product_config(cfg, "boost", with_install_dir=False)
        self.assertEqual(info.git_info.tag, "1.71.0")

    def test_opt_depend_is_still_merged_into_depend(self):
        cfg = locked_config()
        block = cfg.PRODUCTS.boost
        depend = PYF.Sequence(block)
        depend.append("hdf5", "")
        block["depend"] = depend
        optional = PYF.Sequence(block)
        optional.append("Python", "")
        block["opt_depend"] = optional
        cfg.APPLICATION.products["Python"] = "3.9"
        info = PROD.get_product_config(cfg, "boost", with_install_dir=False)
        self.assertIn("Python", list(info.depend))


class TestUnlockedConfigIsUntouched(unittest.TestCase):
    """The global constraint: no marker means today's behaviour, exactly."""

    def test_selection_still_runs(self):
        info = PROD.get_product_config(unlocked_config(), "boost",
                                       with_install_dir=False)
        self.assertEqual(info.section, "default")

    def test_get_product_section_is_still_called(self):
        called = []
        original = PROD.get_product_section
        PROD.get_product_section = (
            lambda *a, **k: called.append(a) or original(*a, **k))
        try:
            PROD.get_product_config(unlocked_config(), "boost",
                                    with_install_dir=False)
        finally:
            PROD.get_product_section = original
        self.assertEqual(len(called), 1)

    def test_the_version_is_still_normalised_before_selection(self):
        # '1.71.0' must reach get_product_section as '1_71_0'
        seen = []
        original = PROD.get_product_section
        PROD.get_product_section = (
            lambda cfg, name, version, section=None:
            seen.append(version) or original(cfg, name, version, section))
        try:
            PROD.get_product_config(unlocked_config(), "boost",
                                    with_install_dir=False)
        finally:
            PROD.get_product_section = original
        self.assertEqual(seen, ["1_71_0"])


class TestExplicitSectionGuard(unittest.TestCase):
    """\
    A pre-existing bug in get_product_section, found while locking the corpus.

    An application may name a product section explicitly:

        ParaView : {tag: '6.1.0...', section: 'version_6_1_0_MPI'}

    If that section does not exist the guard sets pi to None and then looks it
    up anyway, so the caller gets AttributeError instead of the diagnostic the
    None path exists to produce. Four applications in SAT_SALOME do this.
    """

    def product(self):
        cfg = PYF.Config()
        cfg.addMapping("PRODUCTS", PYF.Mapping(cfg), "")
        cfg.PRODUCTS.addMapping("ParaView", PYF.Mapping(cfg.PRODUCTS), "")
        product = cfg.PRODUCTS.ParaView
        product["from_file"] = "/fake/products/ParaView.pyconf"
        product.addMapping("version_6_0_0_MPI", PYF.Mapping(product), "")
        product.version_6_0_0_MPI["name"] = "ParaView"
        return cfg

    def test_an_existing_explicit_section_is_returned(self):
        block = PROD.get_product_section(self.product(), "ParaView", "6_0_0",
                                         "version_6_0_0_MPI")
        self.assertEqual(block.section, "version_6_0_0_MPI")

    def test_a_missing_explicit_section_raises_naming_it(self):
        with self.assertRaises(src.SatException) as caught:
            PROD.get_product_section(self.product(), "ParaView", "6_1_0",
                                     "version_6_1_0_MPI")
        message = str(caught.exception)
        self.assertIn("version_6_1_0_MPI", message)
        self.assertIn("ParaView", message)

    def test_the_message_suggests_the_closest_defined_section(self):
        # for the real case this suggests version_6_0_0_MPI out of 66 defined
        # sections, which makes the application's typo obvious
        with self.assertRaises(src.SatException) as caught:
            PROD.get_product_section(self.product(), "ParaView", "6_1_0",
                                     "version_6_1_0_MPI")
        self.assertIn("version_6_0_0_MPI", str(caught.exception))

    def test_a_missing_section_does_not_fall_back_for_an_incremental_product(self):
        # the trap in the first attempt at this fix: pi=None then falls into the
        # incremental branch, which quietly uses 'default'
        cfg = self.product()
        product = cfg.PRODUCTS.ParaView
        product.addMapping("default", PYF.Mapping(product), "")
        product.default["name"] = "ParaView"
        product.default.addMapping("properties", PYF.Mapping(product.default), "")
        product.default.properties["incremental"] = "yes"
        with self.assertRaises(src.SatException):
            PROD.get_product_section(cfg, "ParaView", "6_1_0",
                                     "version_6_1_0_MPI")


if __name__ == '__main__':
    unittest.main()
