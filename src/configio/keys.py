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
Keys the lock adds to a configuration.

A leaf module, deliberately importing nothing. src/product.py needs SECTION_KEY
for its lock branch, and src/__init__.py imports product while it is still
executing -- so reaching these constants through lock.py would pull readers,
writers and discovery in before src.SatException exists, and the subclasses
there would fail at import time. Constants with no dependencies cannot cycle.
"""

#: Header holding everything whose change invalidates the lock.
LOCK_KEY = "__lock__"

#: Records which product section won the platform collapse.
SECTION_KEY = "__section__"
