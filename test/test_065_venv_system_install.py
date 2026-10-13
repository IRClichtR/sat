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

import unittest

try:
    from unittest import mock
except ImportError:
    import mock

import initializeTest # set PATH etc for test
import venv_fixture as VF
import src.system as SYS


def which_only(*available):
    return lambda name: ("/usr/bin/" + name) if name in available else None


class TestInstallCmd(unittest.TestCase):

    def test_debian_family(self):
        with mock.patch("shutil.which", which_only("apt-get")):
            for code in ["DB", "UB", "MN"]:
                self.assertEqual(SYS.get_pkg_install_cmd(code),
                                 ["apt-get", "install", "-y"])

    def test_redhat_family_dnf(self):
        with mock.patch("shutil.which", which_only("dnf", "yum")):
            for code in ["CO", "FD"]:
                self.assertEqual(SYS.get_pkg_install_cmd(code),
                                 ["dnf", "install", "-y"])

    def test_redhat_family_yum_only(self):
        with mock.patch("shutil.which", which_only("yum")):
            self.assertEqual(SYS.get_pkg_install_cmd("CO"), ["yum", "install", "-y"])

    def test_unsupported(self):
        with mock.patch("shutil.which", which_only("apt-get", "dnf")):
            for code in ["W", "OS", "MG", "MD"]:
                self.assertIsNone(SYS.get_pkg_install_cmd(code))

    def test_tool_missing(self):
        with mock.patch("shutil.which", which_only()):
            self.assertIsNone(SYS.get_pkg_install_cmd("UB"))


class TestInstallSystemPkgs(unittest.TestCase):

    def setUp(self):
        self.logger = VF.FakeLogger()
        self.ask = mock.Mock(return_value="y")
        self.call = mock.Mock(return_value=0)
        patcher = mock.patch("os.geteuid", return_value=1000, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_install(self, pkgs, batch=False, cmd=("apt-get", "install", "-y")):
        return SYS.install_system_pkgs(pkgs, list(cmd) if cmd else None, batch,
                                       self.logger, ask=self.ask, call=self.call)

    def test_install_system_nothing_to_do(self):
        # Review Focus 3: no prompt, no sudo
        self.assertEqual(self.run_install([]), 0)
        self.ask.assert_not_called()
        self.call.assert_not_called()

    def test_accepted(self):
        self.assertEqual(self.run_install(["libb", "liba"]), 0)
        self.call.assert_called_once_with(
            ["sudo", "apt-get", "install", "-y", "liba", "libb"])
        self.assertIn("sudo apt-get install -y liba libb", self.logger.text)

    def test_declined(self):
        self.ask.return_value = ""
        self.assertEqual(self.run_install(["liba"]), 1)
        self.call.assert_not_called()

    def test_batch_refused(self):
        self.assertEqual(self.run_install(["liba"], batch=True), 1)
        self.ask.assert_not_called()
        self.call.assert_not_called()
        self.assertIn("sudo apt-get install -y liba", self.logger.text)

    def test_command_fails(self):
        self.call.return_value = 100
        self.assertEqual(self.run_install(["liba"]), 1)

    def test_unsupported_platform(self):
        self.assertEqual(self.run_install(["liba"], cmd=None), 1)
        self.call.assert_not_called()
        self.assertIn("liba", self.logger.text)

    def test_root_no_sudo(self):
        with mock.patch("os.geteuid", return_value=0, create=True):
            self.run_install(["liba"])
        self.call.assert_called_once_with(["apt-get", "install", "-y", "liba"])


if __name__ == '__main__':
    unittest.main()
