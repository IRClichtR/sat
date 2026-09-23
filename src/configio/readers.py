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
import json
import os

try:
    import tomllib
except ImportError:                                     # Python < 3.11
    tomllib = None

import src
import src.pyconf as PYF
from src.configio.interp import parse_template, TemplateError


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
#: application tag". Decision D10; see TomlReader._check_bool.
PRODUCTS_PATH = ("APPLICATION", "products")


def _where(path):
    """\
    Render a key path for an error message, pyconf style.

    :param path tuple: The keys walked to reach a value.
    :rtype: str
    """
    rendered = ""
    for step in path:
        rendered = PYF.makePath(rendered, step)
    return rendered


def _fill(container, data, path, scalar):
    """\
    Populate a Mapping (or Config) from a dict, in document order.

    Shared by every reader whose format parses to nested dicts and lists.
    The formats differ only in what a leaf means, which is the scalar hook.

    :param container: The Mapping or Config to populate.
    :param data dict: The parsed document, or a sub-object of it.
    :param path tuple: The key path of container, empty at the root.
    :param scalar: Called as scalar(value, path) for every leaf.
    """
    for key in data:
        container.addMapping(
            key, _node(data[key], container, path + (key,), scalar),
            None, setting=True)


def _node(value, parent, path, scalar):
    """\
    Build one pyconf node.

    :param value: The parsed value to convert.
    :param parent: The container this node hangs from. Pyconf's resolver walks
                   this chain upwards, so it must be the real parent: a node
                   built with the wrong one prints correctly and fails to
                   resolve.
    :param path tuple: The key path of this value.
    :param scalar: The leaf hook.
    """
    if isinstance(value, dict):
        mapping = PYF.Mapping(parent)
        mapping.setPath(PYF.makePath(
            object.__getattribute__(parent, 'path'), path[-1]))
        _fill(mapping, value, path, scalar)
        return mapping

    if isinstance(value, list):
        sequence = PYF.Sequence(parent)
        sequence.setPath(PYF.makePath(
            object.__getattribute__(parent, 'path'), path[-1]))
        for index, item in enumerate(value):
            # pyconf spells a sequence step '[n]' -- see makePath
            sequence.append(
                _node(item, sequence, path + ("[%d]" % index,), scalar), None)
        return sequence

    return scalar(value, path)


def _apply_pwd(config, pwd):
    """Attach PWD to the loaded tree, as src.pyconf.Config does."""
    if not pwd:
        return
    key, directory = pwd
    if not key:
        config.PWD = directory
    else:
        config[key].PWD = directory


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
        _fill(config, data, (), self._scalar(config, path))
        _apply_pwd(config, pwd)
        return config

    def _scalar(self, config, source):
        """\
        Build the leaf hook for one file.

        Closes over the root config, which every Reference needs, and the file
        path, which only the error messages need.
        """
        def scalar(value, path):
            if isinstance(value, bool):
                return self._check_bool(value, path)

            if isinstance(value, str):
                try:
                    return parse_template(value, config)
                except TemplateError as error:
                    # interp is pure and knows only the string; the file and
                    # the key path exist here and nowhere else, so this is
                    # where the diagnostic gets assembled.
                    raise src.SatException(
                        "%s: in %s: %s" % (source, _where(path), error))

            if isinstance(value, (int, float)):
                return value

            raise ValueError(
                "%s: %r has no pyconf equivalent. TOML dates and times are "
                "not supported; quote the value to store it as a string."
                % (_where(path), value))
        return scalar

    @staticmethod
    def _check_bool(value, path):
        """\
        Apply decision D10.

        A bool is never equal to a str, so SAT's `== "yes"` tests (for instance
        src/compilation.py:59) read every bool as "no", while
        get_product_config's isinstance(version, bool) test
        (src/product.py:77) reads every bool as "enabled at APPLICATION.tag".
        Both values of a bool are therefore indistinguishable, and wrong in
        opposite directions, so a bool is only accepted where it is unambiguous.
        """
        where = _where(path)
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


class JsonReader(Reader):
    """\
    Reader for the JSON lock.

    The lock is not a report: it is the artifact SAT executes against, so this
    is on the hot path of every invocation in the TOML world and must produce a
    Config that product.py and every command can use unchanged.

    It parses no templates. A resolved lock holds no references, and a ${} seen
    here means a raw diagnostic dump was handed to the wrong loader, so the
    string is left inert rather than quietly revived. D10 does not apply
    either: it governs what a person may write in TOML, not what a generated
    lock may contain.
    """

    extension = ".json"

    def read(self, path, pwd=None):
        """\
        Load a JSON lock.

        :param path str: The file to read.
        :param pwd tuple: A (section, directory) pair, or None.
        :return: The loaded configuration.
        :rtype: class 'src.pyconf.Config'
        :raise ValueError: If the file is not valid JSON.
        """
        with open(path) as stream:
            try:
                data = json.load(stream)
            except ValueError as error:
                raise ValueError("invalid JSON in %r: %s" % (path, error))

        config = PYF.Config()
        # json yields only str, int, float, bool and None, all of which pyconf
        # stores as they are -- so the leaf hook is the identity.
        _fill(config, data, (), lambda value, path: value)
        _apply_pwd(config, pwd)
        return config


# The one place a concrete reader class is named. A format is registered once
# its reader exists; json is added by its own task.
_READERS = {
    PyconfReader.extension: PyconfReader,
    TomlReader.extension: TomlReader,
    JsonReader.extension: JsonReader,
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
