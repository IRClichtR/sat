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
Unit tests for src.configio.lock.

Three concerns, kept apart: collapsing a product to its winning section,
persisting the result, and deciding when the result has gone stale. The
collapse must happen before serialisation -- that ordering is what stops a
platform-dead reference from being evaluated.
"""

import io
import os
import shutil
import tempfile
import unittest

import initializeTest  # noqa: F401  -- must be first, sets sys.path
import src.pyconf as PYF
from src.configio.lock import (collapse_products, lock_path, write_lock,
                               read_lock, is_stale, SECTION_KEY, LOCK_KEY)


class LockTestCase(unittest.TestCase):
    """Base class providing a scratch tree and a trivial source file."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sat_lock_")
        self.src = os.path.join(self.tmp, "src.toml")
        with open(self.src, "w") as stream:
            stream.write('x = 1\n')
        self.lock = os.path.join(self.tmp, "a.lock.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def cfg(self):
        """A minimal config carrying the keys the lock header looks for."""
        cfg = PYF.Config()
        cfg.addMapping("A", PYF.Mapping(cfg), "")
        cfg.A["name"] = "MYAPP"
        cfg.addMapping("VARS", PYF.Mapping(cfg), "")
        cfg.VARS["dist"] = "UB24.04"
        cfg.addMapping("APPLICATION", PYF.Mapping(cfg), "")
        cfg.APPLICATION["name"] = "MYAPP"
        return cfg

    def sources(self, *extra):
        entries = []
        for path in (self.src,) + extra:
            stat = os.stat(path)
            entries.append([path, int(stat.st_mtime), stat.st_size])
        return entries


class TestPersistence(LockTestCase):
    """write_lock and read_lock are two halves of one property."""

    def test_lock_roundtrips_through_disk(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertEqual(read_lock(self.lock).A.name, "MYAPP")

    def test_the_header_records_the_sources(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertIn(self.src, str(read_lock(self.lock)[LOCK_KEY]))

    def test_the_header_records_the_invalidating_facts(self):
        write_lock(self.cfg(), self.lock, self.sources())
        header = read_lock(self.lock)[LOCK_KEY]
        self.assertEqual(header.dist, "UB24.04")
        self.assertEqual(header.application, "MYAPP")
        self.assertIn("sat_version", header)

    def test_it_creates_the_containing_directory(self):
        deep = os.path.join(self.tmp, ".sat", "nested", "a.lock.json")
        write_lock(self.cfg(), deep, self.sources())
        self.assertTrue(os.path.isfile(deep))

    def test_read_lock_returns_a_real_Config(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertIsInstance(read_lock(self.lock), PYF.Config)

    def test_lock_path_is_under_the_workdir(self):
        cfg = self.cfg()
        cfg.addMapping("LOCAL", PYF.Mapping(cfg), "")
        cfg.LOCAL["workdir"] = os.path.join(self.tmp, "work")
        path = lock_path(cfg)
        self.assertTrue(path.startswith(os.path.join(self.tmp, "work")))
        self.assertIn(".sat", path)
        self.assertTrue(path.endswith("MYAPP.lock.json"))


class TestStaleness(LockTestCase):
    """A lock is a cache, so this is the part that actually matters."""

    def test_a_fresh_lock_is_not_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertFalse(is_stale(self.lock, self.sources(), self.cfg()))

    def test_a_missing_lock_is_stale(self):
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_an_edited_source_makes_it_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        with open(self.src, "w") as stream:
            stream.write('x = 2\nyyyy = 3\n')      # mtime and size both change
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_a_source_of_the_same_size_at_a_new_time_makes_it_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        os.utime(self.src, (0, 0))
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_a_new_source_file_makes_it_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        extra = os.path.join(self.tmp, "extra.toml")
        with open(extra, "w") as stream:
            stream.write('y = 1\n')
        self.assertTrue(is_stale(self.lock, self.sources(extra), self.cfg()))

    def test_a_removed_source_file_makes_it_stale(self):
        extra = os.path.join(self.tmp, "extra.toml")
        with open(extra, "w") as stream:
            stream.write('y = 1\n')
        write_lock(self.cfg(), self.lock, self.sources(extra))
        os.remove(extra)
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_a_different_platform_makes_it_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        other = self.cfg()
        other.VARS["dist"] = "CO9"
        self.assertTrue(is_stale(self.lock, self.sources(), other))

    def test_a_different_application_makes_it_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        other = self.cfg()
        other.APPLICATION["name"] = "OTHERAPP"
        self.assertTrue(is_stale(self.lock, self.sources(), other))

    def test_an_unreadable_lock_is_stale_rather_than_fatal(self):
        # conservative by design: regenerating costs a second, using a stale
        # lock costs an afternoon
        with open(self.lock, "w") as stream:
            stream.write("{not json")
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_a_lock_without_a_header_is_stale(self):
        with open(self.lock, "w") as stream:
            stream.write('{"A": {"name": "MYAPP"}}')
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))


class TestOverridesInTheKey(LockTestCase):
    """\
    Command-line overrides change the configuration without changing a file.

    SALOME is hosted on CEA Tuleap and on GitHub; all 61 application files that
    name a server default to 'tuleap', and the public workflow overrides it with
    -o "APPLICATION.properties.git_server='github'" on every command. Two
    populations, identical files. A lock that ignores overrides can be served to
    an invocation that asked for the other one.
    """

    def test_overrides_are_recorded_in_the_header(self):
        write_lock(self.cfg(), self.lock, self.sources(),
                   overrides=["APPLICATION.properties.git_server='github'"])
        header = read_lock(self.lock)[LOCK_KEY]
        self.assertIn("git_server", str(header.overrides))

    def test_no_overrides_records_an_empty_list(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertIn("overrides", read_lock(self.lock)[LOCK_KEY])

    def test_the_same_overrides_are_not_stale(self):
        rules = ["APPLICATION.properties.git_server='github'"]
        write_lock(self.cfg(), self.lock, self.sources(), overrides=rules)
        self.assertFalse(is_stale(self.lock, self.sources(), self.cfg(),
                                 overrides=rules))

    def test_a_different_override_value_is_stale(self):
        write_lock(self.cfg(), self.lock, self.sources(),
                   overrides=["APPLICATION.properties.git_server='github'"])
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg(),
                                 overrides=["APPLICATION.properties.git_server='tuleap'"]))

    def test_losing_an_override_is_stale(self):
        # the public user who forgets the -o on one command out of eleven
        write_lock(self.cfg(), self.lock, self.sources(),
                   overrides=["APPLICATION.properties.git_server='github'"])
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg()))

    def test_gaining_an_override_is_stale(self):
        write_lock(self.cfg(), self.lock, self.sources())
        self.assertTrue(is_stale(self.lock, self.sources(), self.cfg(),
                                 overrides=["APPLICATION.debug='yes'"]))

    def test_override_order_does_not_matter(self):
        a = ["APPLICATION.debug='yes'", "APPLICATION.verbose='no'"]
        write_lock(self.cfg(), self.lock, self.sources(), overrides=a)
        self.assertFalse(is_stale(self.lock, self.sources(), self.cfg(),
                                 overrides=list(reversed(a))))


class TestCollapse(unittest.TestCase):
    """The winning section is chosen by SAT's own code, then stored flat."""

    def build(self, products_entry="'1_71_0'", incremental=False,
              environ_ref=False):
        """\
        A config shaped the way get_product_section expects.

        PRODUCTS.boost carries three sections: default, version_1_71_0 and
        default_win. Only one may survive a collapse on Linux.
        """
        text = '''
APPLICATION :
{
    name : 'MYAPP'
    tag : 'master'
    workdir : '/tmp/work/MYAPP'
    products : { boost : %s }
}
PRODUCTS :
{
    boost :
    {
        # get_config sets this on every product file it loads
        # (commands/config.py:535), and get_product_section reads it
        from_file : '/fake/products/boost.pyconf'
        default :
        {
            name : 'boost'
            build_source : 'autotools'
            get_source : 'archive'
            %s
        }
        version_1_71_0 :
        {
            name : 'boost'
            build_source : 'cmake'
            get_source : 'archive'
            %s
        }
        default_win :
        {
            name : 'boost'
            get_source : 'archive'
            compil_script : 'boost.bat'
        }
    }
}
''' % (products_entry,
       'properties : { incremental : "yes" }' if incremental else '',
       'environ : { PREFIX : $install_dir + "/bin" }' if environ_ref else '')
        cfg = PYF.Config(io.StringIO(text))
        # get_product_config derives more than get_product_section does, so the
        # fixture must carry what that derivation reads: LOCAL.tag for
        # get_salometool_version, PATHS for the archive and script lookups,
        # LOCAL.workdir and VARS for get_install_dir
        cfg.addMapping("LOCAL", PYF.Mapping(cfg), "")
        cfg.LOCAL["tag"] = "5.3.0"
        cfg.LOCAL["workdir"] = "/tmp/work"
        cfg.LOCAL["base"] = "/tmp/base"
        cfg.addMapping("VARS", PYF.Mapping(cfg), "")
        cfg.VARS["sep"] = "/"
        cfg.VARS["dist"] = "UB24.04"
        cfg.VARS["scriptExtension"] = ".sh"
        cfg.addMapping("PATHS", PYF.Mapping(cfg), "")
        cfg.PATHS["ARCHIVEPATH"] = PYF.Sequence(cfg.PATHS)
        cfg.PATHS["PRODUCTPATH"] = PYF.Sequence(cfg.PATHS)
        cfg.addMapping("INTERNAL", PYF.Mapping(cfg), "")
        cfg.INTERNAL.addMapping("config", PYF.Mapping(cfg.INTERNAL), "")
        cfg.INTERNAL.config["install_dir"] = "INSTALL"
        return cfg

    def test_the_winning_section_is_recorded(self):
        cfg = self.build()
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "version_1_71_0")

    def test_the_winning_sections_contents_are_flattened_in(self):
        cfg = self.build()
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost.build_source, "cmake")

    def test_the_losing_sections_are_gone(self):
        cfg = self.build()
        collapse_products(cfg)
        keys = cfg.PRODUCTS.boost.keys()
        self.assertNotIn("default", keys)
        self.assertNotIn("version_1_71_0", keys)

    def test_default_win_is_dropped_on_linux(self):
        # the whole point of collapsing before serialising: this section holds
        # references that are inert here and must never be evaluated
        cfg = self.build()
        collapse_products(cfg)
        self.assertNotIn("default_win", cfg.PRODUCTS.boost.keys())
        self.assertNotIn("compil_script", cfg.PRODUCTS.boost.keys())

    def test_a_product_falling_back_to_default_records_default(self):
        cfg = self.build(products_entry="'9_9_9'")
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "default")
        self.assertEqual(cfg.PRODUCTS.boost.build_source, "autotools")

    def test_an_explicit_section_override_is_honoured(self):
        cfg = self.build(products_entry="{ tag : '1_71_0', section : 'default' }")
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "default")

    def test_a_bare_product_entry_uses_the_application_tag(self):
        cfg = self.build(products_entry="'master'")
        collapse_products(cfg)
        self.assertIn(SECTION_KEY, cfg.PRODUCTS.boost.keys())

    def test_a_dotted_version_still_matches_its_section(self):
        # get_product_config substitutes ".-/" with "_" before calling
        # get_product_section (src/product.py:168), because pyconf cannot use
        # those characters in a key. Passing the version raw makes
        # "version_1.71.0" miss version_1_71_0 and fall through to default --
        # a product silently built from the wrong section.
        cfg = self.build(products_entry="'1.71.0'")
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "version_1_71_0")
        self.assertEqual(cfg.PRODUCTS.boost.build_source, "cmake")

    def test_a_dashed_version_is_normalised_too(self):
        cfg = self.build(products_entry="'1-71-0'")
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "version_1_71_0")

    def test_an_incremental_product_keeps_the_layered_result(self):
        # get_product_section layers default then the winning section, and it
        # does so by mutating default in place -- so collapse must read the
        # result once and replace the product wholesale
        cfg = self.build(incremental=True)
        collapse_products(cfg)
        self.assertEqual(cfg.PRODUCTS.boost[SECTION_KEY], "version_1_71_0")
        self.assertEqual(cfg.PRODUCTS.boost.build_source, "cmake")

    def test_collapsing_twice_changes_no_value(self):
        # get_product_config keeps its own install_dir_save bookkeeping for
        # repeat calls, so a second collapse adds that one key. Every value the
        # first collapse produced must still be the same -- which is what
        # matters, since a lock regenerated twice must describe one product.
        cfg = self.build(incremental=True)
        collapse_products(cfg)
        first = dict((k, cfg.PRODUCTS.boost[k])
                     for k in cfg.PRODUCTS.boost.keys())
        collapse_products(cfg)
        second = dict((k, cfg.PRODUCTS.boost[k])
                      for k in cfg.PRODUCTS.boost.keys())
        for key in first:
            self.assertEqual(first[key], second[key], "%s changed" % key)
        self.assertEqual(set(second) - set(first), {"install_dir_save"})

    def test_install_dir_is_derived_and_stored(self):
        # decision 16, option 2: $install_dir is referenced by 521 values in 33
        # product files but exists nowhere in any file -- get_product_config
        # computes it, so the collapse must call that and keep the result, or
        # the resolved lock cannot be written at all
        cfg = self.build()
        collapse_products(cfg)
        self.assertIn("install_dir", cfg.PRODUCTS.boost.keys())
        self.assertTrue(cfg.PRODUCTS.boost.install_dir)

    def test_install_mode_is_stored_alongside_it(self):
        cfg = self.build()
        collapse_products(cfg)
        self.assertIn("install_mode", cfg.PRODUCTS.boost.keys())

    def test_a_reference_to_install_dir_resolves_after_collapse(self):
        cfg = self.build(environ_ref=True)
        collapse_products(cfg)
        self.assertTrue(
            cfg.PRODUCTS.boost.environ.PREFIX.endswith("/bin"))

    def test_a_config_without_products_is_left_alone(self):
        cfg = PYF.Config()
        cfg.addMapping("A", PYF.Mapping(cfg), "")
        collapse_products(cfg)          # must not raise
        self.assertEqual(list(cfg.keys()), ["A"])

    def test_the_parent_chain_survives_the_replacement(self):
        cfg = self.build()
        collapse_products(cfg)
        self.assertIs(object.__getattribute__(cfg.PRODUCTS.boost, 'parent'),
                      cfg.PRODUCTS)


if __name__ == '__main__':
    unittest.main()
