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
Configuration writers.

Writing is a separate axis from reading: pyconf, toml and json can all be
read, but only pyconf and json can be written. Writers therefore have their
own base class rather than an unimplemented half of Reader.
"""

import abc
import json

import src.pyconf as PYF


class Writer(abc.ABC):
    """\
    Abstract base class for configuration writers.

    Subclasses must set extension and implement write.
    """

    extension = None

    @abc.abstractmethod
    def write(self, cfg, stream, **kw):
        """\
        Serialise a configuration.

        :param cfg: The configuration to write.
        :type cfg: class 'src.pyconf.Config'
        :param stream: An open text stream to write to.
        """


class PyconfWriter(Writer):
    """\
    Writer for the pyconf format. Delegates to Config.__save__.
    """

    extension = ".pyconf"

    def write(self, cfg, stream, evaluated=False):
        """\
        Serialise a configuration in pyconf syntax.

        :param cfg: The configuration to write.
        :param stream: An open text stream to write to.
        :param evaluated bool: Write evaluated values rather than the
                               references and expressions that produce them.
        """
        cfg.__save__(stream, no_close=True, evaluated=evaluated)


class JsonWriter(Writer):
    """\
    Writer for the JSON format, in two modes.

    A configuration holds plain values and deferred computations (Reference,
    Expression), and a serialiser has to decide which of the two it is
    snapshotting. Making that an explicit argument rather than picking one
    silently is what lets the lock and the diagnostic share an implementation:

    - resolved (the default) evaluates and writes the result. This is the lock,
      the artifact SAT executes against and jq can read.
    - raw writes the computation back out as pyconf's $-syntax. This answers
      "what did the author write?", the question a surprising resolved value
      prompts. It is a diagnostic view, not a format: there is no ${}
      re-serialiser and no TOML writer.

    The same distinction exists in pyconf itself; see Container.writeValue.
    """

    extension = ".json"

    def write(self, cfg, stream, resolved=True):
        """\
        Serialise a configuration as JSON.

        :param cfg: The configuration to write.
        :param stream: An open text stream to write to.
        :param resolved bool: Evaluate references and expressions rather than
                              writing them back as templates.
        :raise ConfigResolutionError: In resolved mode, if a reference cannot
                                      be resolved. Not caught here: by the time
                                      a configuration reaches the writer, an
                                      unresolvable reference is a caller bug.
        """
        # sort_keys stays False: product.py iterates aProd.keys() looking for
        # version-range sections, and a lock should remain diffable against the
        # source it was generated from.
        json.dump(self._convert(cfg, cfg, resolved), stream,
                  indent=2, sort_keys=False)

    def _convert(self, node, container, resolved):
        """\
        Build the JSON-serialisable form of one configuration node.

        :param node: The node to convert.
        :param container: The mapping enclosing it. Reference.resolve and
                          Expression.evaluate resolve against the container
                          they are given, so this must be the real parent or
                          references resolve to the wrong value -- silently,
                          in resolved mode.
        :param resolved bool: See write.
        """
        if isinstance(node, PYF.Mapping):
            data = object.__getattribute__(node, 'data')
            return dict((key, self._convert(data[key], node, resolved))
                        for key in node.keys())

        if isinstance(node, PYF.Sequence):
            data = object.__getattribute__(node, 'data')
            return [self._convert(item, node, resolved) for item in data]

        if isinstance(node, (PYF.Reference, PYF.Expression)):
            if not resolved:
                return str(node)
            evaluated = container.evaluate(node)
            # an expression may evaluate to a container, so keep walking
            return self._convert(evaluated, container, resolved)

        return node
