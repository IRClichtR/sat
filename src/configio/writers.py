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

import src
import src.pyconf as PYF
from src.configio.discovery import resolve_layer, layer_is_toml


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
        failures = []
        tree = self._convert(cfg, cfg, resolved, "", failures)
        if failures:
            # Every failure, not the first. Reporting one at a time turned a
            # two-bug, 40-application problem in SAT_SALOME into a single
            # mystery; the cause is only visible once they are side by side.
            raise PYF.ConfigResolutionError(
                "%d value(s) could not be resolved:\n%s"
                % (len(failures), "\n".join(failures)))

        # sort_keys stays False: product.py iterates aProd.keys() looking for
        # version-range sections, and a lock should remain diffable against the
        # source it was generated from.
        json.dump(tree, stream, indent=2, sort_keys=False)

    def _convert(self, node, container, resolved, path="", failures=None):
        """\
        Build the JSON-serialisable form of one configuration node.

        :param node: The node to convert.
        :param container: The mapping enclosing it. Reference.resolve and
                          Expression.evaluate resolve against the container
                          they are given, so this must be the real parent or
                          references resolve to the wrong value -- silently,
                          in resolved mode.
        :param resolved bool: See write.
        :param path str: The key path of this node, for failure messages.
        :param failures list: Accumulator for unresolvable values.
        """
        if isinstance(node, PYF.Mapping):
            data = object.__getattribute__(node, 'data')
            return dict((key, self._convert(data[key], node, resolved,
                                            PYF.makePath(path, key), failures))
                        for key in node.keys())

        if isinstance(node, PYF.Sequence):
            data = object.__getattribute__(node, 'data')
            return [self._convert(item, node, resolved,
                                  "%s[%d]" % (path, index), failures)
                    for index, item in enumerate(data)]

        if isinstance(node, (PYF.Reference, PYF.Expression)):
            if not resolved:
                return str(node)
            try:
                evaluated = container.evaluate(node)
            except Exception as error:
                if failures is None:
                    raise
                failures.append("  %s\n    expression: %s\n    %s: %s"
                                % (path, node, type(error).__name__, error))
                return None
            # an expression may evaluate to a container, so keep walking
            return self._convert(evaluated, container, resolved, path, failures)

        return node


class TomlWriteRefused(src.SatException):
    """Raised when SAT is asked to write back a layer whose source is TOML."""


def writer_for_layer(stem, search_paths, key=None):
    """\
    The writer for a configuration layer, or a refusal if its source is TOML.

    TOML is written by people, not by tools (spec D4), so a layer that came from
    a .toml file is never written back over. The refusal matters more than it
    looks: task 7 makes two files for one layer fatal, so silently writing
    local.pyconf beside an existing local.toml would break the user's next
    command with an error naming a file they never created. An invariant
    enforced on read but not on write is a trap, not an invariant.

    Absence is not TOML. create_config_file exists to create a user
    configuration that is not there yet, and refusing that would break every
    first run.

    :param stem str: The layer path or name, without extension.
    :param search_paths list: Directories to try for a bare name.
    :param key str: The configuration key the caller was about to change, named
                    in the refusal so the user knows what to edit. Optional,
                    because not every site changes a single key.
    :return: A writer for the layer.
    :rtype: class 'Writer'
    :raise TomlWriteRefused: If the layer's source is a .toml file.
    :raise AmbiguousLayerError: If two files define the layer -- task 7's error,
                                deliberately not masked here.
    """
    path, _reader = resolve_layer(stem, search_paths)

    if layer_is_toml(path):
        what = _("Set %s in:") % key if key else _("Edit:")
        raise TomlWriteRefused(
            _("""\
cannot write TOML configuration.
  SAT does not write .toml files -- they are yours to edit.
  %(what)s
      %(path)s""") % {"what": what, "path": path})

    return PyconfWriter()
