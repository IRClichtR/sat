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
import src.product as PROD
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

    products = cfg.PRODUCTS
    for name in cfg.APPLICATION.products.keys():
        if name not in products:
            continue

        version, section = _requested(cfg, name)
        block = PROD.get_product_section(cfg, name, _normalise_version(version),
                                         section)
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
        flat.addMapping(SECTION_KEY, _section_name(block, section), None,
                        setting=True)

        products[name] = flat
        object.__setattr__(flat, 'parent', products)


def lock_path(cfg):
    """\
    Where this configuration's lock belongs.

    :param cfg: The merged configuration.
    :return: <LOCAL.workdir>/.sat/<APPLICATION.name>.lock.json
    :rtype: str
    """
    workdir = cfg.LOCAL.workdir
    name = cfg.APPLICATION.name
    return os.path.join(workdir, LOCK_DIR, "%s.lock.json" % name)


def write_lock(cfg, path, sources):
    """\
    Serialise a collapsed configuration, with the header that invalidates it.

    Call collapse_products first. Serialising an uncollapsed tree evaluates
    references belonging to platforms this machine will never build for.

    :param cfg: The collapsed configuration.
    :param path str: Where to write. Parent directories are created.
    :param sources list: One [path, mtime, size] per file consumed, for every
                         layer -- application, products, projects, local,
                         internal and user.
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


def is_stale(path, sources, cfg):
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


def _requested(cfg, name):
    """\
    What the application asks of one product: a version, and maybe a section.

    Mirrors the small first half of get_product_config (src/product.py:51-120).
    Only the shapes are reproduced here -- bool, str, Mapping -- never the
    section matching, which get_product_section owns. If the application ever
    grows a fourth shape, this is the second place that must learn it.

    :return: (version, section or None)
    :rtype: tuple
    """
    requested = cfg.APPLICATION.products[name]

    if isinstance(requested, PYF.Mapping):
        version = (requested.tag if "tag" in requested
                   else cfg.APPLICATION.tag)
        section = requested.section if "section" in requested else None
        return version, section

    if isinstance(requested, bool):
        # the bare-key shorthand: this product, at the application's own tag
        return cfg.APPLICATION.tag, None

    return requested, None


def _normalise_version(version):
    """\
    Spell a version the way product sections are keyed.

    pyconf cannot use '.', '-' or '/' in a key, so a product asking for
    '1.71.0' must be matched against the section named version_1_71_0.
    get_product_config does this substitution before calling
    get_product_section (src/product.py:168); skipping it makes every dotted
    version miss its section and fall through to default, which is a product
    silently built from the wrong definition.

    :param version: The version as the application spells it.
    :rtype: str
    """
    text = str(version)
    for character in ".-/":
        text = text.replace(character, "_")
    return text


def _section_name(block, requested_section):
    """\
    Which section won.

    get_product_section sets `section` on what it returns, so prefer that; fall
    back to an explicit request, then to 'default'.
    """
    if "section" in block:
        return block.section
    return requested_section or "default"


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
