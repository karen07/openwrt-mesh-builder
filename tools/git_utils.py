#!/usr/bin/env python3
"""Small Git helpers backed by the `git` Unix tool."""

import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .process import output_or_none
except ImportError:
    from process import output_or_none


def git_short(cwd: Path | None = None) -> str:
    return output_or_none(["git", "rev-parse", "--short", "HEAD"], cwd=cwd) or "unknown"
