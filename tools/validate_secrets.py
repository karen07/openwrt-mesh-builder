#!/usr/bin/env python3
from pathlib import Path

from .config_io import MARKER_NAME_RE
from .secrets import decrypt_text as decrypt_owmb_text


def validate_encrypted_config_secrets(
    value: object, where: str, config_path: Path
) -> None:
    if isinstance(value, str):
        if MARKER_NAME_RE.search(value):
            decrypt_owmb_text(value, where, config_path=config_path)
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            validate_encrypted_config_secrets(item, f"{where}[{idx}]", config_path)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            validate_encrypted_config_secrets(item, f"{where}.{key}", config_path)
        return


# ============================================================
# UCI / CONF PARSERS
# ============================================================
