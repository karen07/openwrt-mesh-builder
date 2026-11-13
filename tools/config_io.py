#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import json
import re
from pathlib import Path

from .process import die


def unique_json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


# Plaintext markers are only an explicit editing format for the secrets CLI.
# They are not a supported input format for generated configurations.
VALID_CONFIG_MARKERS = {"OWMB_ENC_SECRET_V1", "OWMB_ENC_MATERIAL_V1"}
# Recognize marker-shaped tokens generically. Only the current names below are
# permitted in config.json; every other marker is a normal input error.
MARKER_NAME_RE = re.compile(r"\b((?:OWMB_[A-Z0-9_]+|[A-Z][A-Z0-9_]*_V[0-9]+))\s*\{")


def validate_config_markers(value: object, where: str = "config") -> None:
    if isinstance(value, str):
        for match in MARKER_NAME_RE.finditer(value):
            marker = match.group(1)
            if marker not in VALID_CONFIG_MARKERS:
                die(f"{where}: unsupported secret/key marker: {marker}")
    elif isinstance(value, dict):
        for name, item in value.items():
            validate_config_markers(item, f"{where}.{name}")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            validate_config_markers(item, f"{where}[{i}]")


def load_json_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(f"missing config file: {path}")
    try:
        raw = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=unique_json_pairs,
        )
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")
    if not isinstance(raw, dict):
        die("config must be a JSON object")
    validate_config_markers(raw)
    return raw
