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


import io
import unittest

try:
    from unittest import mock
except ImportError:
    import mock

import initializeTest # set PATH etc for test
import src.environment
import src.fileEnviron as FE


def header(extra):
    env = {"sat_python_version": 3, "sat_INIT_SYS_PATH_VALUE": "/k", "PATH": ""}
    env.update(extra)
    out = io.StringIO()
    with mock.patch("src.architecture.is_windows", return_value=False):
        FE.LauncherFileEnviron(out, src.environment.Environ(env))
    return out.getvalue().splitlines()[0]


class TestLauncherHeader(unittest.TestCase):

    def test_default_header_unchanged(self):
        self.assertEqual(header({}), "#! /usr/bin/env python3")

    def test_venv_header(self):
        self.assertEqual(header({"sat_venv_python": "/v/bin/python3"}),
                         "#! /v/bin/python3")

    def test_venv_header_modules_pip(self):
        self.assertEqual(header({"sat_venv_python": "/v/bin/python3",
                                 "sat_MODULES_USE_PIP": "1"}),
                         "#! /v/bin/python3")

    def test_sat_variable_not_written(self):
        env = {"sat_python_version": 3, "sat_INIT_SYS_PATH_VALUE": "/k",
               "PATH": "", "sat_venv_python": "/v/bin/python3"}
        out = io.StringIO()
        with mock.patch("src.architecture.is_windows", return_value=False):
            FE.LauncherFileEnviron(out, src.environment.Environ(env))
        self.assertNotIn("sat_venv_python", out.getvalue())

    def test_windows_no_shebang(self):
        env = {"sat_python_version": 3, "sat_INIT_SYS_PATH_VALUE": "/k",
               "PATH": "", "sat_venv_python": "C:\\v\\Scripts\\python3"}
        out = io.StringIO()
        with mock.patch("src.architecture.is_windows", return_value=True):
            FE.LauncherFileEnviron(out, src.environment.Environ(env))
        for line in out.getvalue().splitlines():
            self.assertFalse(line.startswith("#!"), line)


if __name__ == '__main__':
    unittest.main()
