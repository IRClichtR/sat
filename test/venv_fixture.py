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


"""Shared helpers for the --venv tests (test_06x_venv_*.py)."""

import os
import socket
import textwrap

import initializeTest # set PATH etc for test

satdir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
import sys
if os.path.join(satdir, "commands") not in sys.path:
    # SalomeEnviron imports "compile" as a top-level module
    sys.path.insert(0, os.path.join(satdir, "commands"))

import src.salomeTools as SAT   # installs gettext "_" as a builtin
import src
import commands.config as CONFIG_CMD


class FakeLogger(object):
    """Collects everything SAT writes; same calls as src.logger.Logger."""
    def __init__(self):
        self.text = ""
    def write(self, message, level=None, screenOnly=False):
        self.text += message
    def warning(self, message, *args, **kwargs):
        self.text += "WARNING: %s\n" % message
    def error(self, message, *args, **kwargs):
        self.text += "ERROR: %s\n" % message
    def flush(self):
        pass


def has_network(host="pypi.org", port=443, timeout=3):
    try:
        socket.create_connection((host, port), timeout).close()
        return True
    except OSError:
        return False


def _write(path, content):
    d = os.path.dirname(path)
    if not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w") as f:
        f.write(textwrap.dedent(content))


def make_fake_project(root, fakepkg_source="archive", local_extra=""):
    """Create <root>/proj (a SAT project) and <root>/data (a SAT datadir).

    :param fakepkg_source str: "archive" (FTP) or "git" for the compiled
                               section of fakepkg.
    :param local_extra str: extra lines inserted in the LOCAL section of
                            local.pyconf (e.g. "venv : '/x'").
    :return: dict with keys root, proj, data, workdir
    """
    proj = os.path.join(root, "proj")
    data = os.path.join(root, "data")
    work = os.path.join(root, "work")
    _write(os.path.join(proj, "proj.pyconf"), '''
        project_path : $PWD
        ARCHIVEPATH : $project_path + "/archives"
        ARCHIVEFTP : "ftp.example.org/pub"
        APPLICATIONPATH : $project_path + "/applications/"
        PRODUCTPATH : $project_path + "/products/"
        JOBPATH : $project_path + "/jobs/"
        LICENCEPATH : ""
        git_info :
        {
          git_server : { github : {url : "https://github.com/x/", opensource_only: 'yes'} }
          default_git_server : "https://github.com/x/"
        }
        ''')
    _write(os.path.join(data, "local.pyconf"), '''
        LOCAL :
        {
          base : 'default'
          workdir : '%s'
          log_dir : '%s'
          archive_dir : '%s'
          VCS : 'unknown'
          tag : 'unknown'
          %s
        }
        PROJECTS :
        {
          project_file_paths : ['%s']
        }
        ''' % (work, os.path.join(root, "logs"), os.path.join(root, "archives"),
               local_extra, os.path.join(proj, "proj.pyconf")))
    _write(os.path.join(proj, "applications", "VENVTEST.pyconf"), '''
        APPLICATION :
        {
            name : 'VENVTEST'
            workdir : $LOCAL.workdir + $VARS.sep + $APPLICATION.name
            tag : 'master'
            base : 'no'
            python3 : 'yes'
            environ : { build : {} launch : {} }
            products :
            {
                Python : 'native'
                pipnative : 'native'
                sysnative : 'native'
                nopipnative : 'native'
                fakepkg : {tag : '1.0', section : 'version_1_0_compiled'}
            }
            properties : { pip : 'yes', pip_install_dir : 'python' }
        }
        ''')
    common = '''
            build_source : "script"
            compil_script : $name + ".sh"
            source_dir : $APPLICATION.workdir + $VARS.sep + 'SOURCES' + $VARS.sep + $name
            build_dir : $APPLICATION.workdir + $VARS.sep + 'BUILD' + $VARS.sep + $name
            install_dir : 'base'
    '''
    _write(os.path.join(proj, "products", "Python.pyconf"), '''
        default :
        {
            name : "Python"
            get_source : "archive"
            environ : { env_script : "Python.py" }
            depend : []
            properties : { incremental : "yes" }
    ''' + common + '''
        }
        ''')
    _write(os.path.join(proj, "products", "pipnative.pyconf"), '''
        default :
        {
            name : "toml"
            get_source : "archive"
            depend : ["Python"]
            properties : { incremental : "yes", pip : "yes" }
    ''' + common + '''
        }
        ''')
    _write(os.path.join(proj, "products", "sysnative.pyconf"), '''
        default :
        {
            name : "sysnative"
            get_source : "archive"
            system_info : { rpm : ["libfoo-devel"] rpm_dev : [] apt : ["libfoo-dev"] apt_dev : [] }
            depend : []
            properties : { incremental : "yes" }
    ''' + common + '''
        }
        ''')
    _write(os.path.join(proj, "products", "nopipnative.pyconf"), '''
        default :
        {
            name : "nopipnative"
            get_source : "archive"
            depend : ["Python"]
            properties : { incremental : "yes", pip : "no" }
    ''' + common + '''
        }
        ''')
    if fakepkg_source == "git":
        compiled = '''
        version_1_0_compiled :
        {
            get_source : "git"
            git_info : { repo : "https://github.com/x/fakepkg.git" }
            properties : { incremental : "yes", pip : "no" }
        }
        '''
    else:
        compiled = '''
        version_1_0_compiled :
        {
            get_source : "archive"
            archive_info : { archive_name : "fakepkg-1.0.tar.gz" }
            properties : { incremental : "yes", pip : "no" }
        }
        '''
    _write(os.path.join(proj, "products", "fakepkg.pyconf"), '''
        default :
        {
            name : "six"
            get_source : "archive"
            environ : { env_script : "fakepkg.py" }
            depend : ["Python"]
            properties : { incremental : "yes", pip : "yes" }
    ''' + common + '''
        }
        ''' + compiled)
    _write(os.path.join(proj, "products", "env_scripts", "Python.py"), '''
        import os
        def set_env(env, prereq_dir, version, forBuild=None):
            env.set("PYTHON_ROOT_DIR", prereq_dir)
            env.set("PYTHONBIN", os.path.join(prereq_dir, "bin", "python3"))
        def set_nativ_env(env):
            env.set("PYTHON_ROOT_DIR", "/usr")
            env.set("PYTHON_INCLUDE", "/usr/include/python3")
            env.set("PYTHONBIN", "/usr/bin/python3")
        ''')
    _write(os.path.join(proj, "products", "env_scripts", "fakepkg.py"), '''
        import os
        def set_env(env, prereq_dir, version):
            env.prepend("PYTHONPATH", os.path.join(prereq_dir, "lib", "site-packages"))
        def set_nativ_env(env):
            pass
        ''')
    return {"root": root, "proj": proj, "data": data, "workdir": work}


def load_config(datadir, overrides=None, application="VENVTEST"):
    """Load the SAT config of <application> from <datadir>.

    :param overrides list: -o rules, e.g. ["APPLICATION.products.fakepkg='native'"]
    """
    args = []
    for rule in (overrides or []):
        args += ["-o", rule]
    options, _ = SAT.parser.parse_args(args)
    return CONFIG_CMD.ConfigManager().get_config(datadir=datadir,
                                                 application=application,
                                                 options=options,
                                                 command="config")
