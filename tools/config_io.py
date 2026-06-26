#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import json
from pathlib import Path

try:
    from .process import die
except ImportError:
    from process import die  # type: ignore


def load_json_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(f"missing config file: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")
    if not isinstance(raw, dict):
        die("config must be a JSON object")
    return raw
