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
Layer discovery: which file provides this configuration layer.

Six layers in commands/config.py build their paths by appending '.pyconf'.
For any of them to accept TOML, that decision moves here, where it is made
once and tested.
"""

import os

import src
from src.configio.readers import reader_for

#: The extensions a layer may be written in, in the order they are reported.
#:
#: '.json' is deliberately absent. JsonReader can load a lock, but a resolved
#: lock is machine-specific (spec D6), so allowing one to be discovered as a
#: layer would let another machine's absolute paths become configuration.
#: Being able to read a format and choosing to look for it are separate
#: decisions, and conflating them is how footguns are built.
LAYER_EXTENSIONS = (".pyconf", ".toml")


class AmbiguousLayerError(src.SatException):
    """Raised when two files claim to be the same configuration layer."""


def resolve_layer(stem, search_paths):
    """\
    Find the file providing one configuration layer.

    The stem is either a path without its extension, as the hardcoded layers
    use (".../data/local"), or a bare name to look up in search_paths, as
    products use ("boost"). A stem carrying a directory is looked for there
    and nowhere else.

    :param stem str: The path or name to resolve, without extension.
    :param search_paths list: Directories to try, in order, for a bare name.
    :return: (path, reader instance), or (None, None) if no file provides it.
    :rtype: tuple
    :raise AmbiguousLayerError: If one directory holds the layer in more than
                                one format.
    """
    directory, name = os.path.split(stem)
    directories = [directory] if directory else list(search_paths)

    for candidate in directories:
        found = _formats_in(candidate, name)

        if len(found) > 1:
            raise AmbiguousLayerError(
                "several files define the same configuration layer %r:\n"
                "  %s\n"
                "SAT will not guess which one you meant. Remove all but one."
                % (name, "\n  ".join(found)))

        if found:
            return found[0], reader_for(found[0])

    return None, None


def layer_is_toml(path):
    """\
    Whether a resolved layer is written in TOML.

    Accepts None so that the result of resolve_layer can be passed straight in.

    :param path str: A path, or None.
    :rtype: bool
    """
    return path is not None and path.endswith(".toml")


def _formats_in(directory, name):
    """\
    List the files providing one layer within a single directory.

    Ambiguity is per directory, never across the search path. The same name in
    two directories is ordinary -- it is what PATHS.PRODUCTPATH overriding is
    for, and first wins. Checking across the search path instead would break
    every project that overrides a product.

    :param directory str: The directory to look in.
    :param name str: The layer name, without extension.
    :return: Existing paths, in LAYER_EXTENSIONS order.
    :rtype: list
    """
    candidates = [os.path.join(directory, name + extension)
                  for extension in LAYER_EXTENSIONS]
    return [path for path in candidates if os.path.isfile(path)]
