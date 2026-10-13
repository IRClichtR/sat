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

A venv is created once with "sat init --venv [<path>]" (no path: <workdir>/venv)
and its path is stored in LOCAL.venv; "sat init --venv forget" forgets it. Commands given --venv build and run the application
against it. See VENV_FEAT_DESIGN.md.
'''

import json
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


# value of "sat init --venv" that forgets the configured venv
FORGET = "forget"


def default_venv_path(config):
    '''Venv used by "sat init --venv" when no path is given'''
    return os.path.join(config.LOCAL.workdir, "venv")


def resolve_venv_path(value):
    '''Turn a venv path (as given or as stored in LOCAL.venv) into an
    absolute path

    :rtype: str
    '''
    return os.path.abspath(os.path.expanduser(value))


def resolve_venv_dir(config):
    '''Absolute path of the venv configured with "sat init --venv"

    :raise SatException: if no venv is configured or it is not a venv
    :rtype: str
    '''
    if "venv" not in config.LOCAL:
        raise src.SatException(
            _("no venv configured: run 'sat init --venv [<path>]'"))
    venv_dir = resolve_venv_path(config.LOCAL.venv)
    if not is_venv(venv_dir):
        raise src.SatException(
            _("the venv configured in LOCAL.venv (%s) does not exist or is not "
              "a virtual environment: run 'sat init --venv [<path>]' "
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


def _save_local_venv(config, value):
    '''Write (or remove when value is None) LOCAL.venv in data/local.pyconf'''
    local_file_path = os.path.join(config.VARS.datadir, "local.pyconf")
    local_cfg = src.pyconf.Config(local_file_path)
    if value is None:
        if "venv" in local_cfg.LOCAL:
            del local_cfg.LOCAL["venv"]
    else:
        local_cfg.LOCAL["venv"] = value
    with open(local_file_path, 'w') as ff:
        local_cfg.__save__(ff, 1)
    if value is None:
        if "venv" in config.LOCAL:
            del config.LOCAL["venv"]
    else:
        config.LOCAL["venv"] = value


def init_venv(config, value, logger):
    '''Implementation of "sat init --venv [<path>|forget]"

    :param value str: a path (commands/init.py turns a bare --venv into
                      default_venv_path), or FORGET
    :rtype: int
    :return: 0 if OK, 1 on error
    '''
    try:
        if value == FORGET:
            _save_local_venv(config, None)
            logger.write(_("venv forgotten. You can safely remove from disk.\n"), 1)
            return 0

        venv_dir = resolve_venv_path(value)
        sat_path = os.path.join(config.VARS.salometoolsway, "sat")
        if create_venv(venv_dir, sat_path, logger) != 0:
            return 1
        # written last: a failed init leaves local.pyconf untouched
        _save_local_venv(config, venv_dir)
        logger.write(_("venv ready: %s\nactivate it with: source %s\n") %
                     (venv_dir, os.path.join(venv_bin_dir(venv_dir), "activate")), 1)
        return 0
    except Exception as e:
        logger.write(src.printcolors.printcError(
            _("Unable to configure the venv: %s\n") % str(e)), 1)
        return 1


def split_native_products(config):
    '''Split the native products of the application (D2)

    :rtype: tuple (venv_products, system_products)
    :return: venv_products: [(product_key, pip_name)] native products with
             property pip "yes"; system_products: [(product_key, product_info)]
             every other native product. Both sorted by product key.
    '''
    venv_products = []
    system_products = []
    for product in sorted(config.APPLICATION.products):
        product_info = src.product.get_product_config(config, product)
        if not src.product.product_is_native(product_info):
            continue
        if src.product.product_test_property(product_info, "pip", "yes"):
            venv_products.append((product, product_info.name))
        else:
            system_products.append((product, product_info))
    return venv_products, system_products


def get_requirements(config, venv_products, logger):
    '''pip requirement of each venv product, pinned with APPLICATION.venv (D10)

    :rtype: dict
    :return: {product_key: "pip_name" or "pip_name==pin"}
    '''
    pins = {}
    if "venv" in config.APPLICATION:
        for key in config.APPLICATION.venv:
            pins[key] = str(config.APPLICATION.venv[key])
    requirements = {}
    for key, pip_name in venv_products:
        if key in pins:
            requirements[key] = "%s==%s" % (pip_name, pins.pop(key))
        else:
            requirements[key] = pip_name
    for key in sorted(pins):
        logger.warning(_("APPLICATION.venv.%s is ignored: %s is not a native "
                         "pip product of the application") % (key, key))
    return requirements


# run by the venv interpreter: argv[1] is a json list of distribution names,
# prints {name: [version, location] or null}. The first distribution found on
# sys.path wins (the one "import" would load).
_CHECK_SCRIPT = r'''
import json, re, sys
try:
    from importlib import metadata
except ImportError:
    import importlib_metadata as metadata
def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()
found = {}
for dist in metadata.distributions():
    name = dist.metadata["Name"]
    if name and norm(name) not in found:
        found[norm(name)] = [dist.version, str(dist.locate_file(""))]
print(json.dumps(dict((n, found.get(norm(n))) for n in json.loads(sys.argv[1]))))
'''


def check_venv_pkgs(venv_dir, pip_names):
    '''Check which distributions the venv interpreter sees

    :param pip_names list: distribution names (product "name" keys)
    :rtype: dict
    :return: {name: {"status": "OK"|"KO", "version": str|None,
                     "origin": "venv"|"system"|None}}
    '''
    output = subprocess.check_output([venv_python(venv_dir), "-c",
                                      _CHECK_SCRIPT, json.dumps(list(pip_names))])
    raw = json.loads(output.decode("utf-8"))
    venv_root = os.path.realpath(venv_dir) + os.sep
    result = {}
    for name in pip_names:
        if raw.get(name) is None:
            result[name] = {"status": "KO", "version": None, "origin": None}
            continue
        version, location = raw[name]
        in_venv = (os.path.realpath(location) + os.sep).startswith(venv_root)
        result[name] = {"status": "OK", "version": version,
                        "origin": "venv" if in_venv else "system"}
    return result


def install_venv_pkgs(config, venv_dir, requirements, logger):
    '''pip install the requirements into the venv, caching the downloaded
    files in $LOCAL.archive_dir/wheels (same place as sat compile)

    :param requirements list: pip requirement strings ("toml", "toml==0.10.2")
    :rtype: int
    :return: the number of requirements that could not be installed
    '''
    if not requirements:
        return 0
    python = venv_python(venv_dir)
    wheels_dir = os.path.join(config.LOCAL.archive_dir, "wheels")
    src.ensure_path_exists(wheels_dir)
    pip = [python, "-m", "pip", "--disable-pip-version-check"]
    failures = 0
    for requirement in requirements:
        logger.write(_("pip install %s in %s\n") % (requirement, venv_dir), 3)
        # failure ignored: the wheel may already be cached (offline use)
        subprocess.call(pip + ["download", "-q", "--dest", wheels_dir, requirement])
        rc = subprocess.call(pip + ["install", "-q", "--no-index",
                                    "--find-links", wheels_dir, requirement])
        if rc != 0:
            # an sdist may need build dependencies from the index
            rc = subprocess.call(pip + ["install", "-q",
                                        "--find-links", wheels_dir, requirement])
        if rc != 0:
            failures += 1
            logger.write(src.printcolors.printcError(
                _("Error: pip could not install %s\n") % requirement), 1)
    return failures
