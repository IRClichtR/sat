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
Comparison helpers for the configuration equivalence oracle.

Two configurations loaded from different formats should describe the same
thing. These helpers reduce each to a flat mapping of path to resolved value
so that a difference names a key rather than a tree.

Nothing here knows which formats are being compared. The oracle starts with
pyconf against TOML and gains a JSON lane later, so labels are arguments.
"""

import src.pyconf as PYF

#: Stand-ins for containers holding nothing. Without them an empty table
#: contributes no path at all and a missing one compares equal to it.
EMPTY_MAPPING = "<empty mapping>"
EMPTY_SEQUENCE = "<empty sequence>"


def flatten(cfg, prefix=""):
    """\
    Reduce a configuration to {path: resolved value}.

    Leaves are read through normal item access so that pyconf's lazy
    resolution fires: a Reference and an Expression that compute the same
    string flatten to the same value, which is the equivalence being tested.

    :param cfg: The configuration, or any node within one.
    :param prefix str: The path of this node, empty at the root.
    :return: One entry per leaf, keyed by dotted path.
    :rtype: dict
    """
    flat = {}

    if isinstance(cfg, PYF.Mapping):            # Config is a Mapping
        keys = cfg.keys()
        if not keys:
            return {prefix: EMPTY_MAPPING}
        for key in keys:
            flat.update(flatten(cfg[key], PYF.makePath(prefix, key)))

    elif isinstance(cfg, PYF.Sequence):
        if not len(cfg):
            return {prefix: EMPTY_SEQUENCE}
        for index in range(len(cfg)):
            flat.update(flatten(cfg[index], "%s[%d]" % (prefix, index)))

    else:
        flat[prefix] = cfg

    return flat


def assert_equivalent(testcase, cfg_a, cfg_b, label_a="A", label_b="B"):
    """\
    Fail the test unless two configurations flatten identically.

    Key differences are reported before value differences: a key missing on
    one side explains a value mismatch, while the reverse is not true, so
    reporting values first buries the cause under its own symptoms.

    :param testcase: The TestCase to fail through.
    :param cfg_a: The reference configuration.
    :param cfg_b: The configuration under test.
    :param label_a str: How to name the first side in a failure message.
    :param label_b str: How to name the second side in a failure message.
    """
    flat_a = flatten(cfg_a)
    flat_b = flatten(cfg_b)

    only_a = sorted(set(flat_a) - set(flat_b))
    only_b = sorted(set(flat_b) - set(flat_a))
    if only_a or only_b:
        report = []
        if only_a:
            report.append("only in %s:\n  %s" % (label_a, "\n  ".join(only_a)))
        if only_b:
            report.append("only in %s:\n  %s" % (label_b, "\n  ".join(only_b)))
        testcase.fail("configurations have different keys\n" + "\n".join(report))

    mismatches = []
    for key in sorted(flat_a):
        if flat_a[key] != flat_b[key]:
            mismatches.append("  %s\n    %s: %r\n    %s: %r"
                              % (key, label_a, flat_a[key],
                                 label_b, flat_b[key]))
    if mismatches:
        testcase.fail("%d value(s) differ\n%s"
                      % (len(mismatches), "\n".join(mismatches)))
