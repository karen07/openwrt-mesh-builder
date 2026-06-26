#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import base64
import json
import os
import re
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
except Exception as e:  # pragma: no cover - import-time dependency error
    print(f"ERROR: missing Python dependency cryptography: {e}", file=sys.stderr)
    sys.exit(1)

try:
    from .process import die
    from .default import (
        CONFIG_KEY_MATERIALS_KEY_PATH,
        CONFIG_KEY_SECRET_KEY,
        CONFIG_KEY_SECRETS_KEY_PATH,
        CONFIG_PATH,
        OWMB_ENC_MATERIAL_MARKER,
        OWMB_ENC_SECRET_MARKER,
        OWMB_MATERIALS_KEY_MARKER,
        OWMB_PLAIN_MATERIAL_MARKER,
        OWMB_PLAIN_SECRET_MARKER,
        OWMB_SECRETS_KEY_MARKER,
        ROUTER_SECRET_MARKER,
    )
except ImportError:
    from process import die
    from default import (
        CONFIG_KEY_MATERIALS_KEY_PATH,
        CONFIG_KEY_SECRET_KEY,
        CONFIG_KEY_SECRETS_KEY_PATH,
        CONFIG_PATH,
        OWMB_ENC_MATERIAL_MARKER,
        OWMB_ENC_SECRET_MARKER,
        OWMB_MATERIALS_KEY_MARKER,
        OWMB_PLAIN_MATERIAL_MARKER,
        OWMB_PLAIN_SECRET_MARKER,
        OWMB_SECRETS_KEY_MARKER,
        ROUTER_SECRET_MARKER,
    )

KEY_SIZE = 32
NONCE_SIZE = 12
B64_RE = re.compile(r"^[A-Za-z0-9_-]+$")

MARKERS = (
    OWMB_PLAIN_SECRET_MARKER,
    OWMB_ENC_SECRET_MARKER,
    OWMB_PLAIN_MATERIAL_MARKER,
    OWMB_ENC_MATERIAL_MARKER,
)
ENCRYPTED_MARKERS = (OWMB_ENC_SECRET_MARKER, OWMB_ENC_MATERIAL_MARKER)
PLAIN_MARKERS = (OWMB_PLAIN_SECRET_MARKER, OWMB_PLAIN_MATERIAL_MARKER)
LEGACY_MARKERS = (ROUTER_SECRET_MARKER,)

# Payloads are either base64url ciphertext or simple plaintext/import values.
# Keep plaintext marker parsing intentionally simple; values containing a literal
# closing brace should be supplied through stdin to the encrypt-* commands.
MARKER_RE = re.compile(
    rf"({'|'.join(re.escape(m) for m in MARKERS)})\s*\{{\s*(.*?)\s*\}}",
    re.S,
)
LEGACY_RE = re.compile(rf"{re.escape(ROUTER_SECRET_MARKER)}\s*\{{", re.S)


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    payload = re.sub(r"\s+", "", text)
    if not payload:
        die("empty base64url payload")
    if not B64_RE.fullmatch(payload):
        die("bad base64url payload characters")
    pad = "=" * ((4 - len(payload) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((payload + pad).encode("ascii"))
    except Exception as e:
        die(f"bad base64url payload: {e}")


def expand_config_path(raw: str, *, config_path: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw))
    path = Path(expanded)
    if not path.is_absolute():
        path = config_path.parent / path
    return path


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(f"missing config file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")
    if not isinstance(data, dict):
        die("config must be a JSON object")
    return data


def config_key_path(config_key: str, *, config_path: Path) -> Path:
    cfg = load_config(config_path)
    if CONFIG_KEY_SECRET_KEY in cfg:
        die(
            f"legacy config.{CONFIG_KEY_SECRET_KEY} is not supported; "
            f"use {CONFIG_KEY_SECRETS_KEY_PATH!r} and {CONFIG_KEY_MATERIALS_KEY_PATH!r}"
        )
    raw = cfg.get(config_key)
    if not isinstance(raw, str) or not raw.strip():
        die(f"config.{config_key} must be a non-empty path")
    return expand_config_path(raw.strip(), config_path=config_path)


def _marker_for_key_path(config_key: str) -> str:
    if config_key == CONFIG_KEY_SECRETS_KEY_PATH:
        return OWMB_SECRETS_KEY_MARKER
    if config_key == CONFIG_KEY_MATERIALS_KEY_PATH:
        return OWMB_MATERIALS_KEY_MARKER
    die(f"unknown master-key config key: {config_key}")


def ensure_master_key_file(path: Path, marker: str) -> bytes:
    if path.exists():
        if not path.is_file():
            die(f"master-key path exists but is not a file: {path}")
        text = path.read_text(encoding="utf-8").strip()
        m = re.fullmatch(
            rf"{re.escape(marker)}\s*\{{\s*([A-Za-z0-9_\-\s]+?)\s*\}}", text, re.S
        )
        if not m:
            die(f"bad master-key file format in {path}; expected {marker}{{...}}")
        key = b64u_decode(m.group(1))
        if len(key) != KEY_SIZE:
            die(f"bad master-key size in {path}: expected {KEY_SIZE} bytes")
        return key

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except PermissionError:
        pass
    key = os.urandom(KEY_SIZE)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(f"{marker}{{{b64u_encode(key)}}}\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)
    print(f"Generated master key: {path}", file=sys.stderr)
    return key


def master_key(config_key: str, *, config_path: Path = CONFIG_PATH) -> bytes:
    path = config_key_path(config_key, config_path=config_path)
    return ensure_master_key_file(path, _marker_for_key_path(config_key))


def marker_config_key(marker: str) -> str:
    if marker in (OWMB_PLAIN_SECRET_MARKER, OWMB_ENC_SECRET_MARKER):
        return CONFIG_KEY_SECRETS_KEY_PATH
    if marker in (OWMB_PLAIN_MATERIAL_MARKER, OWMB_ENC_MATERIAL_MARKER):
        return CONFIG_KEY_MATERIALS_KEY_PATH
    die(f"unknown marker: {marker}")


def encrypted_marker_for_plain(marker: str) -> str:
    if marker == OWMB_PLAIN_SECRET_MARKER:
        return OWMB_ENC_SECRET_MARKER
    if marker == OWMB_PLAIN_MATERIAL_MARKER:
        return OWMB_ENC_MATERIAL_MARKER
    die(f"not a plaintext marker: {marker}")


def plaintext_marker_for_encrypted(marker: str) -> str:
    if marker == OWMB_ENC_SECRET_MARKER:
        return OWMB_PLAIN_SECRET_MARKER
    if marker == OWMB_ENC_MATERIAL_MARKER:
        return OWMB_PLAIN_MATERIAL_MARKER
    die(f"not an encrypted marker: {marker}")


def format_marker(marker: str, payload: str, wrap: int | None = None) -> str:
    if wrap is None or wrap <= 0:
        return f"{marker}{{{payload}}}"
    lines = [payload[i : i + wrap] for i in range(0, len(payload), wrap)]
    return f"{marker}\n{{\n" + "\n".join(lines) + "\n}"


def encrypt_payload(
    plain: bytes, marker: str, *, config_path: Path, wrap: int = 0
) -> str:
    if not plain:
        die("empty value")
    key = master_key(marker_config_key(marker), config_path=config_path)
    nonce = os.urandom(NONCE_SIZE)
    cipher = ChaCha20Poly1305(key).encrypt(nonce, plain, marker.encode("ascii"))
    return format_marker(marker, b64u_encode(nonce + cipher), wrap)


def decrypt_payload(payload: str, marker: str, *, config_path: Path) -> str:
    data = b64u_decode(payload)
    if len(data) <= NONCE_SIZE:
        die("encrypted payload is too short")
    nonce, cipher = data[:NONCE_SIZE], data[NONCE_SIZE:]
    key = master_key(marker_config_key(marker), config_path=config_path)
    try:
        plain = ChaCha20Poly1305(key).decrypt(nonce, cipher, marker.encode("ascii"))
    except Exception as e:
        die(f"failed to decrypt {marker}: {e}")
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        die(f"decrypted {marker} value is not valid UTF-8")


def encrypt_material_value(
    value: str,
    *,
    config_path: Path = CONFIG_PATH,
    wrap: int = 0,
) -> str:
    if contains_any_marker(value):
        return value
    return encrypt_payload(
        value.encode("utf-8"),
        OWMB_ENC_MATERIAL_MARKER,
        config_path=config_path,
        wrap=wrap,
    )


def decrypt_text(
    text: str,
    where: str = "<text>",
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    if LEGACY_RE.search(text):
        die(f"{where}: legacy {ROUTER_SECRET_MARKER} marker is not supported")

    def repl(match: re.Match[str]) -> str:
        marker = match.group(1)
        payload = match.group(2)
        if marker == OWMB_PLAIN_SECRET_MARKER:
            return payload
        if marker == OWMB_PLAIN_MATERIAL_MARKER:
            return payload
        if marker in ENCRYPTED_MARKERS:
            return decrypt_payload(payload, marker, config_path=config_path)
        die(f"{where}: unknown marker {marker}")

    return MARKER_RE.sub(repl, text)


def decrypt_value(value: str, *, config_path: Path = CONFIG_PATH) -> str:
    return decrypt_text(value, config_path=config_path)


def contains_any_marker_text(text: str) -> bool:
    return any(marker in text for marker in MARKERS) or ROUTER_SECRET_MARKER in text


def contains_any_marker(value: str) -> bool:
    return contains_any_marker_text(value)


def ensure_final_newline(text: str) -> str:
    if text and not text.endswith("\n"):
        return text + "\n"
    return text


def iter_files(paths: list[Path]):
    for path in paths:
        if path.is_symlink():
            continue
        if path.is_file():
            yield path
            continue
        if path.is_dir():
            for item in path.rglob("*"):
                if item.is_symlink():
                    continue
                if item.is_file():
                    yield item
            continue
        die(f"path does not exist: {path}")


def decrypt_file(path: Path, *, config_path: Path = CONFIG_PATH) -> bool:
    data = path.read_bytes()
    has_marker = any(marker.encode("ascii") in data for marker in MARKERS)
    has_legacy_marker = ROUTER_SECRET_MARKER.encode("ascii") in data
    if not has_marker and not has_legacy_marker:
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        die(f"{path}: marker found in non-UTF-8 file")
    new_text = decrypt_text(text, str(path), config_path=config_path)
    if new_text == text:
        return False
    path.write_text(ensure_final_newline(new_text), encoding="utf-8")
    print(f"Decrypted OWMB markers in {path}")
    return True


def decrypt_tree(paths: list[Path], *, config_path: Path = CONFIG_PATH) -> None:
    for path in iter_files(paths):
        decrypt_file(path, config_path=config_path)


def assert_no_markers(paths: list[Path]) -> None:
    found = False
    marker_bytes = [m.encode("ascii") for m in MARKERS + LEGACY_MARKERS]
    for path in iter_files(paths):
        data = path.read_bytes()
        if any(m in data for m in marker_bytes):
            print(f"OWMB marker left in {path}", file=sys.stderr)
            found = True
    if found:
        die("secret/key-material markers are still present")


def transform_markers(
    text: str,
    *,
    direction: str,
    include_secrets: bool,
    include_materials: bool,
    config_path: Path,
    wrap: int,
) -> str:
    if LEGACY_RE.search(text):
        die(f"legacy {ROUTER_SECRET_MARKER} marker is not supported")

    def repl(match: re.Match[str]) -> str:
        marker = match.group(1)
        payload = match.group(2)
        is_secret = marker in (OWMB_PLAIN_SECRET_MARKER, OWMB_ENC_SECRET_MARKER)
        is_material = marker in (OWMB_PLAIN_MATERIAL_MARKER, OWMB_ENC_MATERIAL_MARKER)
        if (is_secret and not include_secrets) or (
            is_material and not include_materials
        ):
            return match.group(0)
        if direction == "encrypt":
            if marker in ENCRYPTED_MARKERS:
                return match.group(0)
            enc_marker = encrypted_marker_for_plain(marker)
            return encrypt_payload(
                payload.encode("utf-8"),
                enc_marker,
                config_path=config_path,
                wrap=wrap,
            )
        if direction == "decrypt-marked":
            if marker in PLAIN_MARKERS:
                return match.group(0)
            plain_marker = plaintext_marker_for_encrypted(marker)
            plain = decrypt_payload(payload, marker, config_path=config_path)
            return format_marker(plain_marker, plain, 0)
        if direction == "decrypt":
            if marker in PLAIN_MARKERS:
                return payload
            if marker in ENCRYPTED_MARKERS:
                return decrypt_payload(payload, marker, config_path=config_path)
            return match.group(0)
        die(f"bad transform direction: {direction}")

    return MARKER_RE.sub(repl, text)


def transform_file(path: Path, **kwargs) -> bool:
    data = path.read_bytes()
    marker_bytes = [m.encode("ascii") for m in MARKERS + LEGACY_MARKERS]
    if not any(m in data for m in marker_bytes):
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        die(f"{path}: marker found in non-UTF-8 file")
    new_text = transform_markers(text, config_path=kwargs.pop("config_path"), **kwargs)
    if new_text == text:
        return False
    path.write_text(ensure_final_newline(new_text), encoding="utf-8")
    print(f"Updated markers in {path}")
    return True


def transform_tree(paths: list[Path], **kwargs) -> None:
    for path in iter_files(paths):
        transform_file(path, **kwargs)


def main(argv: list[str] | None = None) -> None:
    try:
        from .secrets_cli import main as cli_main
    except ImportError:
        from secrets_cli import main as cli_main  # type: ignore

    cli_main(argv)


if __name__ == "__main__":
    main()
