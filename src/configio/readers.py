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
Configuration readers.

A reader maps a file path to a src.pyconf.Config. Format selection is done by
reader_for, which dispatches on the file extension.
"""

import abc
import os

try:
    import tomllib
except ImportError:                                     # Python < 3.11
    tomllib = None

import src.pyconf as PYF
from src.configio.interp import parse_template


class Reader(abc.ABC):
    """
    Abstract base class for configuration readers.

    Subclasses must set extension and implement read; both are enforced by abc.
    The following requirements are not enforceable by the language and are
    covered by test/test_037_readers.py:

    - return a src.pyconf.Config, not a bare Mapping. Config provides the
      namespace and path handling that ConfigMerger requires.
    - pass pwd to the underlying loader unchanged. Relative paths inside the
      file are resolved against it.
    - raise on error rather than return a partially loaded Config.
    - hold no state between calls. A single instance may read several files.
    - reproduce the behaviour of the format's native loader exactly. The
      equivalence oracle compares the two.
    """

    extension = None

    @abc.abstractmethod
    def read(self, path, pwd=None):
        """\
        Load a configuration file.

        :param path str: The file to read.
        :param pwd tuple: A (section, directory) pair, or None. Passed to the
                          underlying loader unchanged.
        :return: The loaded configuration.
        :rtype: class 'src.pyconf.Config'
        """


class PyconfReader(Reader):
    """\
    Reader for the pyconf format.

    Delegates to src.pyconf.Config and adds no behaviour of its own, being the
    reference side of the equivalence oracle.
    """

    extension = ".pyconf"

    def read(self, path, pwd=None):
        """\
        Load a pyconf file.

        :param path str: The file to read.
        :param pwd tuple: A (section, directory) pair, or None.
        :return: The loaded configuration.
        :rtype: class 'src.pyconf.Config'
        """
        with open(path) as stream:
            return PYF.Config(stream, PWD=pwd)


#: Where a bool is the only accepted spelling of "this product, at the
#: application tag". Decision D10; see TomlReader._convert_bool.
PRODUCTS_PATH = ("APPLICATION", "products")


class TomlReader(Reader):
    """\
    Reader for the TOML format.

    TOML has no interpolation and no reference type, so the same object graph
    pyconf's parser builds is assembled here from tomllib's dicts and lists:
    dict to Mapping, list to Sequence, and any string holding ${...} to a
    Reference or Expression via src.configio.interp.

    Two TOML features have no pyconf counterpart and are rejected rather than
    approximated: booleans outside APPLICATION.products, and date/time values.
    """

    extension = ".toml"

    def read(self, path, pwd=None):
        """\
        Load a TOML file.

        :param path str: The file to read.
        :param pwd tuple: A (section, directory) pair, or None.
        :return: The loaded configuration.
        :rtype: class 'src.pyconf.Config'
        :raise ValueError: If the file holds a value with no pyconf equivalent.
        """
        if tomllib is None:
            raise ValueError(
                "cannot read %r: TOML support needs Python 3.11 or later "
                "(running %d.%d). Use a .pyconf file instead."
                % (path, os.sys.version_info[0], os.sys.version_info[1]))

        with open(path, "rb") as stream:
            try:
                data = tomllib.load(stream)
            except tomllib.TOMLDecodeError as error:
                raise ValueError("invalid TOML in %r: %s" % (path, error))

        config = PYF.Config()
        self._fill(config, data, config, ())

        # same contract as src.pyconf.Config, applied once the tree exists
        if pwd:
            key, directory = pwd
            if not key:
                config.PWD = directory
            else:
                config[key].PWD = directory
        return config

    def _fill(self, container, data, config, path):
        """Populate a Mapping (or Config) from a dict, in file order."""
        for key in data:
            value = self._convert(data[key], container, config, path + (key,))
            container.addMapping(key, value, None, setting=True)

    def _convert(self, value, parent, config, path):
        """\
        Build the pyconf node for one TOML value.

        :param value: The tomllib value to convert.
        :param parent: The container this node hangs from. Pyconf's resolver
                       walks this chain upwards, so it must be the real parent.
        :param config: The root Config, passed to every Reference built.
        :param path tuple: The key path of this value, used to locate bools.
        """
        if isinstance(value, dict):
            mapping = PYF.Mapping(parent)
            mapping.setPath(PYF.makePath(
                object.__getattribute__(parent, 'path'), path[-1]))
            self._fill(mapping, value, config, path)
            return mapping

        if isinstance(value, list):
            sequence = PYF.Sequence(parent)
            sequence.setPath(PYF.makePath(
                object.__getattribute__(parent, 'path'), path[-1]))
            for index, item in enumerate(value):
                # pyconf spells a sequence step '[n]' -- see makePath
                sequence.append(
                    self._convert(item, sequence, config,
                                  path + ("[%d]" % index,)), None)
            return sequence

        if isinstance(value, bool):
            return self._convert_bool(value, path)

        if isinstance(value, str):
            return parse_template(value, config)

        if isinstance(value, (int, float)):
            return value

        raise ValueError(
            "%s: %r has no pyconf equivalent. TOML dates and times are not "
            "supported; quote the value to store it as a string."
            % (self._where(path), value))

    @staticmethod
    def _convert_bool(value, path):
        """\
        Apply decision D10.

        A bool is never equal to a str, so SAT's `== "yes"` tests (for instance
        src/compilation.py:59) read every bool as "no", while
        get_product_config's isinstance(version, bool) test
        (src/product.py:77) reads every bool as "enabled at APPLICATION.tag".
        Both values of a bool are therefore indistinguishable, and wrong in
        opposite directions, so a bool is only accepted where it is unambiguous.
        """
        where = TomlReader._where(path)
        if path[:2] != PRODUCTS_PATH or len(path) != 3:
            raise ValueError(
                "%s: booleans are not configuration values here. SAT compares "
                'against the strings "yes" and "no", and a boolean matches '
                "neither, so it would silently read as \"no\". Write "
                '"yes" or "no".' % where)
        if not value:
            raise ValueError(
                "%s: false does not disable a product -- membership is by key, "
                "so this would enable it at APPLICATION.tag. Delete the line "
                "to remove the product." % where)
        return True

    @staticmethod
    def _where(path):
        """Render a key path for an error message, pyconf style."""
        rendered = ""
        for step in path:
            rendered = PYF.makePath(rendered, step)
        return rendered


# The one place a concrete reader class is named. A format is registered once
# its reader exists; json is added by its own task.
_READERS = {
    PyconfReader.extension: PyconfReader,
    TomlReader.extension: TomlReader,
}


def reader_for(path):
    """\
    Return a reader for the given path, selected on its extension.

    :param path str: The file path to dispatch on.
    :return: A new reader instance.
    :rtype: class 'Reader'
    :raise ValueError: If no reader is registered for the extension.
    """
    extension = os.path.splitext(path)[1]
    if extension not in _READERS:
        raise ValueError(
            "no reader for extension %r (path %r); known extensions: %s"
            % (extension, path, ", ".join(sorted(_READERS)) or "none"))
    return _READERS[extension]()
