#!/usr/bin/env python3
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

required = {
    "obsidian_memory_core/__init__.py",
    "obsidian_memory_core/store.py",
    "obsidian_memory_core/config.py",
    "mcp_server.py",
}

if len(sys.argv) != 2:
    raise SystemExit("usage: verify_wheel.py WHEEL")
wheel = Path(sys.argv[1])
with zipfile.ZipFile(wheel) as archive:
    names = set(archive.namelist())
missing = sorted(required - names)
if missing:
    raise SystemExit("wheel missing: " + ", ".join(missing))
print(f"wheel verified: {wheel.name}; required files present")
