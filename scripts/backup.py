#!/usr/bin/env python3
"""Consistent MeshDock SQLite backup; preserve the matching encryption key separately."""

import argparse
import os
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description="Back up a MeshDock database.")
parser.add_argument("database", type=Path)
parser.add_argument("destination", type=Path)
arguments = parser.parse_args()
if arguments.destination.exists():
    parser.error("Destination already exists.")
os.umask(0o077)
with sqlite3.connect(f"file:{arguments.database}?mode=ro", uri=True) as source:
    with sqlite3.connect(arguments.destination) as target:
        source.backup(target)
print("MeshDock database backup complete. Back up the matching master.key separately and securely.")
