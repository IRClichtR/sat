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
Stand-alone validation of a TOML configuration file.

Checks what the file alone determines, and nothing that needs the other
configuration layers:

- TOML grammar, as tomllib parses it;
- the ${} template grammar of every string;
- the value rules TomlReader enforces: decision D10 on booleans, no dates.

References are not resolved and products are not looked up, so a file that
validates can still fail to load. Each leaf is checked by TomlReader's own
hook, so a message reported here is the one loading the file would raise.
"""

import os

try:
    import tomllib
except ImportError:                                     # Python < 3.11
    tomllib = None

import src
import src.pyconf as PYF
from src.configio.readers import TomlReader


def validate_toml(path):
    """\
    Validate one TOML configuration file.

    Grammar errors stop the check, since tomllib cannot parse past them. Value
    errors are collected, so every offending key is reported in one pass.

    :param path str: The file to validate.
    :return: The error messages, empty if the file is valid.
    :rtype: list
    """
    if os.path.splitext(path)[1] != TomlReader.extension:
        return ["%s: not a %s file" % (path, TomlReader.extension)]
    if not os.path.isfile(path):
        return ["%s: no such file" % path]
    if tomllib is None:
        return ["%s: TOML support needs Python 3.11 or later" % path]

    with open(path, "rb") as stream:
        try:
            data = tomllib.load(stream)
        except tomllib.TOMLDecodeError as error:
            return ["%s: invalid TOML: %s" % (path, error)]

    # The hook builds References against this root; nothing is resolved.
    scalar = TomlReader()._scalar(PYF.Config(), path)
    errors = []
    _walk(data, (), scalar, path, errors)
    return errors


def _walk(value, key_path, scalar, path, errors):
    """\
    Apply the leaf hook to every scalar below value, collecting failures.

    Key paths are built as readers._node builds them, sequence steps as
    '[n]', so the messages name keys exactly as a load failure would.

    :param value: A parsed TOML value.
    :param key_path tuple: The keys walked to reach value.
    :param scalar: TomlReader's leaf hook.
    :param path str: The file, for messages that do not already name it.
    :param errors list: Receives one message per offending leaf.
    """
    if isinstance(value, dict):
        for key in value:
            _walk(value[key], key_path + (key,), scalar, path, errors)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, key_path + ("[%d]" % index,), scalar, path, errors)
        return
    try:
        scalar(value, key_path)
    except ValueError as error:
        errors.append("%s: %s" % (path, error))
    except src.SatException as error:
        # template errors arrive already prefixed with the file and key
        errors.append(str(error))
