#!/usr/bin/env python3
"""WireGuard/AmneziaWG key helpers backed by the `wg` Unix tool."""

import sys

sys.dont_write_bytecode = True
import re

try:
    from .process import need, run_checked
except ImportError:
    from process import need, run_checked


WG_PRIVATE_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=$")
WG_PRIVATE_KEY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+/])([A-Za-z0-9+/]{43}=)(?![A-Za-z0-9+/=])"
)


def generate_private_key() -> str:
    need("wg")
    return run_checked(["wg", "genkey"]).strip()


def normalize_private_key(private_key: str) -> str:
    text = private_key.strip().strip("'\"")
    if WG_PRIVATE_KEY_RE.fullmatch(text):
        return text

    matches = WG_PRIVATE_KEY_TOKEN_RE.findall(text)
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]

    preview = text.replace("\n", "\\n")
    if len(preview) > 80:
        preview = preview[:77] + "..."
    raise ValueError(f"not a single WireGuard private key: {preview!r}")


def derive_public_key(private_key: str) -> str:
    need("wg")
    input_text = normalize_private_key(private_key) + "\n"
    return run_checked(["wg", "pubkey"], input_text=input_text).strip()
