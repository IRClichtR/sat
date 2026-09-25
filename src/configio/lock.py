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
The JSON lock: platform collapse, persistence and invalidation.

The lock is not a report. It is the artifact SAT executes against when any
configuration layer is TOML, in the spirit of Cargo.lock. It is generated,
machine-local and gitignored: it holds absolute paths, the distro tag and the
user name, so it means nothing on another machine.

Being generated makes it a cache, and caches are only as good as their
invalidation, which is why is_stale is the most important function here.
"""

import json
import os

import src.pyconf as PYF
from src.configio.readers import JsonReader
from src.configio.writers import JsonWriter

#: Header key holding everything whose change invalidates the lock.
LOCK_KEY = "__lock__"

#: Key recording which product section won the collapse.
SECTION_KEY = "__section__"

#: Directory, relative to LOCAL.workdir, holding generated locks.
LOCK_DIR = ".sat"


def collapse_products(cfg):
    """\
    Replace each product's section family with the one section that applies.

    Every product file carries sections that are inert on this machine --
    default_win on Linux, other distros' variants -- and those sections hold
    references that never resolve here. Writing a fully resolved lock evaluates
    the whole tree eagerly, so those references must be gone before
    serialisation rather than handled during it. Collapse first, then serialise.

    The choice of section is not made here: get_product_section already encodes
    it, including incremental layering, version ranges and explicit overrides.
    This calls it once per product and stores the result flat, with SECTION_KEY
    recording which section won.

    Modifies cfg in place.

    :param cfg: The merged configuration.
    :type cfg: class 'src.pyconf.Config'
    """
    if "APPLICATION" not in cfg or "products" not in cfg.APPLICATION:
        return
    if "PRODUCTS" not in cfg:
        return

    # Imported here, not at module level: src.product imports SECTION_KEY from
    # this module for its lock branch, so a module-level import either way
    # round would make the cycle depend on which side is imported first.
    import src.product as PROD

    products = cfg.PRODUCTS
    for name in cfg.APPLICATION.products.keys():
        if name not in products:
            continue

        # get_product_config, not get_product_section: the section decision is
        # only half of what a resolved lock needs. $install_dir is referenced by
        # 521 values across 33 product files and exists in none of them --
        # get_install_dir computes it at runtime -- so a lock written from the
        # section alone cannot be resolved at all (spec section 16, option 2).
        # Calling the real function keeps one implementation of that decision,
        # which is the same reason the section itself is not re-derived here.
        block = PROD.get_product_config(cfg, name)
        if block is None:
            continue

        # Copy before replacing. get_product_section is not pure: for an
        # incremental product it returns the product's own 'default' section
        # after writing the winning section's keys into it (src/product.py:483).
        # Reading it once and replacing the product wholesale keeps that
        # mutation from being observed, and makes a second collapse a no-op.
        flat = PYF.Mapping(products)
        flat.setPath(PYF.makePath(
            object.__getattribute__(products, 'path'), name))
        data = object.__getattribute__(block, 'data')
        for key in block.keys():
            flat.addMapping(key, data[key], None, setting=True)
        flat.addMapping(SECTION_KEY, _section_name(block), None,
                        setting=True)

        products[name] = flat
        object.__setattr__(flat, 'parent', products)


def lock_path(cfg, name=None):
    """\
    Where this configuration's lock belongs.

    :param cfg: The merged configuration.
    :param name str: The application name. Defaults to APPLICATION.name, but the
                     fast path in get_config has only the command-line argument
                     at the point it needs this, and the two must agree or it
                     would look for a lock nothing ever writes.
    :return: <LOCAL.workdir>/.sat/<name>.lock.json
    :rtype: str
    """
    workdir = cfg.LOCAL.workdir
    return os.path.join(workdir, LOCK_DIR,
                        "%s.lock.json" % (name or cfg.APPLICATION.name))


def write_lock(cfg, path, sources, overrides=None):
    """\
    Serialise a collapsed configuration, with the header that invalidates it.

    Call collapse_products first. Serialising an uncollapsed tree evaluates
    references belonging to platforms this machine will never build for.

    :param cfg: The collapsed configuration.
    :param path str: Where to write. Parent directories are created.
    :param sources list: One [path, mtime, size] per file consumed, for every
                         layer -- application, products, projects, local,
                         internal and user.
    :param overrides list: The command-line -o rules that were applied. They
                           change the configuration without changing any file,
                           so a lock that ignored them could be served to an
                           invocation that asked for something different --
                           the tuleap/github case in Task 10.
    """
    directory = os.path.dirname(path)
    if directory and not os.path.isdir(directory):
        os.makedirs(directory)

    header = PYF.Mapping(cfg)
    header.setPath(LOCK_KEY)
    header.addMapping("sat_version", _sat_version(cfg), None, setting=True)
    header.addMapping("dist", _lookup(cfg, "VARS", "dist"), None, setting=True)
    header.addMapping("application", _lookup(cfg, "APPLICATION", "name"),
                      None, setting=True)
    sequence = PYF.Sequence(header)
    sequence.setPath(PYF.makePath(LOCK_KEY, "sources"))
    for entry in sources:
        item = PYF.Sequence(sequence)
        for field in entry:
            item.append(field, None)
        sequence.append(item, None)
    header.addMapping("sources", sequence, None, setting=True)

    rules = PYF.Sequence(header)
    rules.setPath(PYF.makePath(LOCK_KEY, "overrides"))
    for rule in sorted(overrides or []):
        rules.append(rule, None)
    header.addMapping("overrides", rules, None, setting=True)

    cfg[LOCK_KEY] = header
    with open(path, "w") as stream:
        JsonWriter().write(cfg, stream, resolved=True)


def read_lock(path):
    """\
    Load a lock back as a configuration.

    :param path str: The lock to read.
    :return: The configuration the lock describes.
    :rtype: class 'src.pyconf.Config'
    """
    return JsonReader().read(path)


def is_stale(path, sources, cfg, overrides=None):
    """\
    Whether a lock must be regenerated before it can be trusted.

    Conservative on purpose. Regenerating a good lock costs a second; using a
    stale one costs an afternoon, and the symptom -- an edit that has no effect
    -- sends the reader looking anywhere but here. Any doubt means stale:
    a missing or unreadable lock, a missing header, a different SAT version,
    a different platform, a different application, or any difference at all in
    the source list.

    :param path str: The lock to check.
    :param sources list: [path, mtime, size] per source file, as they are now.
    :param cfg: The configuration about to be built.
    :param overrides list: The command-line -o rules for this invocation.
    :rtype: bool
    """
    if not os.path.isfile(path):
        return True

    try:
        with open(path) as stream:
            header = json.load(stream).get(LOCK_KEY)
    except (ValueError, OSError):
        return True

    if not isinstance(header, dict):
        return True

    if header.get("sat_version") != _sat_version(cfg):
        return True
    if header.get("dist") != _lookup(cfg, "VARS", "dist"):
        return True
    if header.get("application") != _lookup(cfg, "APPLICATION", "name"):
        return True

    if sorted(header.get("overrides") or []) != sorted(overrides or []):
        return True

    recorded = header.get("sources")
    if not isinstance(recorded, list):
        return True
    if _normalise(recorded) != _normalise(sources):
        return True

    # a source recorded but since deleted leaves the triples matching only if
    # the caller also stopped listing it, so check the files themselves too
    for entry in recorded:
        if not entry or not os.path.isfile(entry[0]):
            return True

    return False


def can_reuse(path, application, dist, sat_version, overrides=None):
    """\
    Whether a lock can be returned without building the configuration at all.

    is_stale compares a lock against a freshly computed source list, so by the
    time it can be called every layer has already been read -- correct, but it
    saves nothing. This validates the lock against the inputs it *recorded*,
    which is possible after two cheap files (internal and local) and before
    projects, application, products and user are touched.

    Sound rather than a shortcut: a source that could newly appear only becomes
    relevant if a file already in the recorded set changed, because the
    application file is what names the products and local.pyconf is what names
    the projects. Either change invalidates the lock through its own triple, so
    no separate discovery pass is needed to notice new files.

    A pure-pyconf configuration never writes a lock, so a validating lock also
    implies the configuration was TOML-sourced. That is what lets this run before
    the TOML gate is known.

    :param path str: The lock to validate.
    :param application str: The application being built.
    :param dist str: VARS.dist for this machine.
    :param sat_version str: INTERNAL.sat_version.
    :param overrides list: The command-line -o rules for this invocation.
    :rtype: bool
    """
    if not os.path.isfile(path):
        return False

    try:
        with open(path) as stream:
            header = json.load(stream).get(LOCK_KEY)
    except (ValueError, OSError):
        return False

    if not isinstance(header, dict):
        return False
    if header.get("application") != application:
        return False
    if header.get("dist") != dist:
        return False
    if header.get("sat_version") != sat_version:
        return False
    if sorted(header.get("overrides") or []) != sorted(overrides or []):
        return False

    recorded = header.get("sources")
    if not isinstance(recorded, list) or not recorded:
        # nothing to validate against means nothing can be trusted
        return False

    for entry in recorded:
        try:
            source, mtime, size = entry
        except (TypeError, ValueError):
            return False
        if not os.path.isfile(source):
            return False
        stat = os.stat(source)
        if int(stat.st_mtime) != mtime or stat.st_size != size:
            return False

    return True


def _section_name(block):
    """\
    Which section won.

    get_product_config sets `section` on the product info it returns, by way of
    get_product_section. 'default' is the fallback that function itself uses.
    """
    if "section" in block:
        return block.section
    return "default"


def _sat_version(cfg):
    """The SAT version, or a placeholder when INTERNAL is not loaded."""
    return _lookup(cfg, "INTERNAL", "sat_version")


def _lookup(cfg, section, key):
    """Read cfg.<section>.<key>, or None if either is absent."""
    if section not in cfg:
        return None
    node = cfg[section]
    if key not in node:
        return None
    return node[key]


def _normalise(sources):
    """\
    Put a source list in a comparable form.

    Order must not matter -- layers are discovered in whatever order
    get_config happens to walk them -- but every triple must match exactly.
    """
    return sorted([str(entry[0]), int(entry[1]), int(entry[2])]
                  for entry in sources)
