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

import src.pyconf as PYF


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


# The one place a concrete reader class is named. A format is registered once
# its reader exists; toml and json are added by their own tasks.
_READERS = {
    PyconfReader.extension: PyconfReader,
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
