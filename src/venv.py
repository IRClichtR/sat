#!/usr/bin/env python
#-*- coding:utf-8 -*-
#  Copyright (C) 2010-2026  CEA/DEN
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

'''
Virtual environment support (option --venv).

A venv is created once with "sat init --venv <path|default|none>" and its path
is stored in LOCAL.venv. Commands given --venv build and run the application
against it. See VENV_FEAT_DESIGN.md.
'''

import os
import sys
import stat
import subprocess

import src


def venv_bin_dir(venv_dir):
    '''Directory holding the venv executables (bin, or Scripts on windows)'''
    if src.architecture.is_windows():
        return os.path.join(venv_dir, "Scripts")
    return os.path.join(venv_dir, "bin")


def venv_python(venv_dir):
    '''Path of the venv interpreter'''
    if src.architecture.is_windows():
        return os.path.join(venv_bin_dir(venv_dir), "python.exe")
    return os.path.join(venv_bin_dir(venv_dir), "python")


def is_venv(venv_dir):
    '''True if venv_dir is a virtual environment (has a pyvenv.cfg)'''
    return os.path.isfile(os.path.join(venv_dir, "pyvenv.cfg"))


def resolve_venv_path(config, value):
    '''Turn a LOCAL.venv value into an absolute path

    :param value str: a path, or "default" for $LOCAL.workdir/venv
    :rtype: str
    '''
    if value == "default":
        return os.path.join(config.LOCAL.workdir, "venv")
    return os.path.abspath(os.path.expanduser(value))


def resolve_venv_dir(config):
    '''Absolute path of the venv configured with "sat init --venv"

    :raise SatException: if no venv is configured or it is not a venv
    :rtype: str
    '''
    if "venv" not in config.LOCAL:
        raise src.SatException(
            _("no venv configured: run 'sat init --venv <path|default>'"))
    venv_dir = resolve_venv_path(config, config.LOCAL.venv)
    if not is_venv(venv_dir):
        raise src.SatException(
            _("the venv configured in LOCAL.venv (%s) does not exist or is not "
              "a virtual environment: run 'sat init --venv <path|default>' "
              "again") % venv_dir)
    return venv_dir


def write_wrapper(venv_dir, sat_path):
    '''Write <venv>/bin/sat (Scripts\\sat.bat on windows), which runs sat
    with the venv interpreter.

    :rtype: str
    :return: the wrapper path
    '''
    python = venv_python(venv_dir)
    if src.architecture.is_windows():
        path = os.path.join(venv_bin_dir(venv_dir), "sat.bat")
        content = '@echo off\r\n"%s" "%s" %%*\r\n' % (python, sat_path)
    else:
        path = os.path.join(venv_bin_dir(venv_dir), "sat")
        content = '#!/bin/sh\nexec "%s" "%s" "$@"\n' % (python, sat_path)
    with open(path, "w") as f:
        f.write(content)
    mode = os.stat(path).st_mode
    os.chmod(path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def create_venv(venv_dir, sat_path, logger):
    '''Create (or reuse) a venv with --system-site-packages, install distro
    in it and write the sat wrapper.

    :rtype: int
    :return: 0 if OK, 1 on error
    '''
    if os.path.exists(venv_dir) and not is_venv(venv_dir):
        logger.write(src.printcolors.printcError(
            _("Error: %s exists and is not a virtual environment\n") % venv_dir), 1)
        return 1

    if is_venv(venv_dir):
        logger.write(_("Reusing existing venv %s\n") % venv_dir, 3)
    else:
        logger.write(_("Creating venv %s\n") % venv_dir, 3)
        rc = subprocess.call([sys.executable, "-m", "venv",
                              "--system-site-packages", venv_dir])
        if rc != 0:
            logger.write(src.printcolors.printcError(
                _("Error: unable to create the venv %s\n") % venv_dir), 1)
            return 1

    # sat's own dependency; a failure is not fatal (system distro may be
    # visible through system site packages, and src.architecture has a fallback)
    rc = subprocess.call([venv_python(venv_dir), "-m", "pip", "install",
                          "--disable-pip-version-check", "-q", "distro"])
    if rc != 0:
        logger.write(src.printcolors.printcWarning(
            _("Warning: could not install distro in the venv\n")), 1)

    wrapper = write_wrapper(venv_dir, sat_path)
    logger.write(_("sat wrapper: %s\n") % wrapper, 3)
    return 0
