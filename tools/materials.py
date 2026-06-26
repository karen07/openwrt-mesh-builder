#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re
from pathlib import Path

try:
    from .process import die
    from .default import OWMB_ENC_MATERIAL_MARKER
    from .file_ops import has_any_owmb_marker, read, write
    from .secrets import decrypt_value as decrypt_owmb_value
    from .secrets import encrypt_material_value
    from .wg_keys import (
        derive_public_key,
        generate_private_key,
        normalize_private_key,
    )
except ImportError:
    import importlib.util

    from process import die
    from default import OWMB_ENC_MATERIAL_MARKER
    from file_ops import has_any_owmb_marker, read, write
    from wg_keys import (
        derive_public_key,
        generate_private_key,
        normalize_private_key,
    )

    _secrets_path = Path(__file__).with_name("secrets.py")
    _secrets_spec = importlib.util.spec_from_file_location(
        "owmb_local_secrets", _secrets_path
    )
    if _secrets_spec is None or _secrets_spec.loader is None:
        raise ImportError(f"cannot load {_secrets_path}")
    _secrets_module = importlib.util.module_from_spec(_secrets_spec)
    _secrets_spec.loader.exec_module(_secrets_module)
    decrypt_owmb_value = _secrets_module.decrypt_value
    encrypt_material_value = _secrets_module.encrypt_material_value


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

    # WireGuard-style config values are normally single-line, but an OWMB marker
    # can be line-wrapped manually or by `secrets.py --wrap`. In that case the
    # old one-token regexp captured only `OWMB_ENC_MATERIAL_V1` and fed that to
    # `wg pubkey`, producing "Trailing characters found after key". Collect the
    # marker body until the closing brace before decrypting.
    if has_any_owmb_marker(value) and "}" not in value:
        tail = text[m.end() :]
        extra: list[str] = []
        for line in tail.splitlines():
            extra.append(line)
            if "}" in line:
                break
        value = "\n".join([value, *extra]).strip()

    return value


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
        plain = decrypt_owmb_value(value.strip())
        remember_encrypted_material(value, plain)
        return plain
    return value


def stored_key_material(value: str) -> str:
    # Store every known private/key-material value as an encrypted material marker.
    # This intentionally acts as a one-pass migration: legacy plaintext values and
    # OWMB_PLAIN_MATERIAL_V1 values are converted to OWMB_ENC_MATERIAL_V1 when the
    # generator rewrites the file.
    plain = material_plaintext(value)
    old_marker = _ENCRYPTED_MATERIAL_BY_PLAINTEXT.get(plain)
    if old_marker is not None:
        return old_marker
    return encrypt_material_value(plain)


def write_material_file(path: Path, plaintext: str) -> None:
    write(path, f"{stored_key_material(plaintext).rstrip()}\n")


def material_file_for_tool(path: Path, tmp_dir: Path, name: str) -> Path:
    plain = material_plaintext(read(path))
    out = tmp_dir / name
    out.write_text(plain, encoding="utf-8")
    out.chmod(0o600)
    return out


def parse_existing_tunnel_conf(path: Path) -> tuple[str | None, str | None]:
    if not path.exists():
        return None, None
    value = extract_tunnel_private_key_value(read(path))
    priv = wireguard_private_key_plaintext(value) if value else None
    return priv, (public_key_from_private(priv) if priv else None)


def gen_private_key() -> str:
    return generate_private_key()


def public_key_from_private(private_key: str) -> str:
    return derive_public_key(wireguard_private_key_plaintext(private_key))
