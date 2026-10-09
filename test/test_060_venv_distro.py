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
import sys
import unittest
import importlib.util
import platform

try:
    from unittest import mock
except ImportError:
    import mock

import initializeTest # set PATH etc for test

satdir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
ARCH_PATH = os.path.join(satdir, "src", "architecture.py")


def load_fresh_architecture():
    """Load a private copy of src/architecture.py (does not touch src.architecture)."""
    spec = importlib.util.spec_from_file_location("arch_under_test", ARCH_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestDistroFallback(unittest.TestCase):

    @unittest.skipUnless(hasattr(platform, "freedesktop_os_release"),
                         "needs python >= 3.10")
    def test_no_distro_uses_os_release(self):
        fake_release = {"NAME": "Ubuntu", "VERSION_ID": "24.04",
                        "VERSION_CODENAME": "noble"}
        # None in sys.modules makes "import distro" raise ImportError
        with mock.patch.dict(sys.modules, {"distro": None}), \
             mock.patch("platform.freedesktop_os_release",
                        return_value=fake_release):
            arch = load_fresh_architecture()   # must not sys.exit
            self.assertEqual(arch.linux_distribution(),
                             ("Ubuntu", "24.04", "noble"))

    @unittest.skipUnless(hasattr(platform, "freedesktop_os_release"),
                         "needs python >= 3.10")
    def test_no_distro_no_os_release_file(self):
        with mock.patch.dict(sys.modules, {"distro": None}), \
             mock.patch("platform.freedesktop_os_release",
                        side_effect=OSError("no os-release")):
            arch = load_fresh_architecture()
            self.assertEqual(arch.linux_distribution(), ("", "", ""))

    def test_with_distro_unchanged(self):
        try:
            import distro
        except ImportError:
            self.skipTest("distro not installed")
        arch = load_fresh_architecture()
        self.assertEqual(arch.linux_distribution()[:2],
                         distro.linux_distribution()[:2])


if __name__ == '__main__':
    unittest.main()
