#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
from pathlib import Path

from .default import OWMB_ENC_MATERIAL_MARKER
from .file_ops import has_any_owmb_marker, read, write
from .process import die
from .secrets import decrypt_value as decrypt_owmb_value
from .secrets import encrypt_material_value
from .wg_keys import (
    derive_public_key,
    generate_private_key,
    normalize_private_key,
)

PRIVATE_KEY_LINE_RE = re.compile(r"(?m)^\s*PrivateKey\s*=\s*(.*?)\s*$")
ENC_MATERIAL_RE = re.compile(
    rf"^\s*{re.escape(OWMB_ENC_MATERIAL_MARKER)}\s*\{{\s*"
    r"([A-Za-z0-9_\-\s]+?)\s*\}\s*$",
    re.S,
)

_ENCRYPTED_MATERIAL_BY_PLAINTEXT: dict[str, str] = {}


def remember_encrypted_material(value: str, plaintext: str) -> None:
    marker = value.strip()
    if "\n" in marker or "\r" in marker:
        return
    if ENC_MATERIAL_RE.fullmatch(marker):
        _ENCRYPTED_MATERIAL_BY_PLAINTEXT.setdefault(plaintext, marker)


def extract_tunnel_private_key_value(text: str) -> str | None:
    m = PRIVATE_KEY_LINE_RE.search(text)
    if not m:
        return None

    value = m.group(1).strip()
    if not value:
        return None

    # WireGuard-style config values are normally single-line, but OWMB markers
    # may be wrapped. Collect the full marker before decrypting its key.
    if has_any_owmb_marker(value) and "}" not in value:
        tail = text[m.end() :]
        extra: list[str] = []
        for line in tail.splitlines():
            extra.append(line)
            if "}" in line:
                break
        value = "\n".join([value, *extra]).strip()

    return value


def require_encrypted_material(value: str, where: str) -> None:
    if not isinstance(value, str) or not ENC_MATERIAL_RE.fullmatch(value.strip()):
        die(f"{where}: expected {OWMB_ENC_MATERIAL_MARKER} encrypted key material")


def wireguard_private_key_plaintext(value: str) -> str:
    try:
        return normalize_private_key(material_plaintext(value))
    except ValueError as e:
        die(f"bad WireGuard private key material: {e}")


def material_plaintext(value: str) -> str:
    # Standalone OWMB material values are often read from inline config blocks
    # with an artificial trailing newline added by extract_inline_block(). Strip
    # marker surrounding whitespace before decrypting so repeated OpenVPN runs do
    # not add one more newline to the decrypted private key on every generation.
    if has_any_owmb_marker(value):
        require_encrypted_material(value, "key material")
        plain = decrypt_owmb_value(value.strip())
        remember_encrypted_material(value, plain)
        return plain
    return value


def stored_key_material(value: str) -> str:
    # Newly generated plaintext keys are encrypted on output. Existing stored
    # keys must already use the only supported encrypted material format.
    plain = material_plaintext(value)
    cached_marker = _ENCRYPTED_MATERIAL_BY_PLAINTEXT.get(plain)
    if cached_marker is not None:
        return cached_marker
    return encrypt_material_value(plain)


def write_material_file(path: Path, plaintext: str) -> None:
    write(path, f"{stored_key_material(plaintext).rstrip()}\n")


def material_file_for_tool(path: Path, tmp_dir: Path, name: str) -> Path:
    source = read(path)
    require_encrypted_material(source, str(path))
    plain = material_plaintext(source)
    out = tmp_dir / name
    out.write_text(plain, encoding="utf-8")
    out.chmod(0o600)
    return out


def parse_existing_tunnel_conf(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    value = extract_tunnel_private_key_value(read(path))
    if value:
        require_encrypted_material(value, str(path))
    priv = wireguard_private_key_plaintext(value) if value else None
    return priv, (public_key_from_private(priv) if priv else None)


def gen_private_key() -> str:
    return generate_private_key()


def public_key_from_private(private_key: str) -> str:
    return derive_public_key(wireguard_private_key_plaintext(private_key))
