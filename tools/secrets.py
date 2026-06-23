#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import base64
import getpass
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

try:
    from .default import (
        CONFIG_KEY_SECRET_KEY,
        CONFIG_PATH,
        ROUTER_SECRET_MARKER as MARKER,
    )
except ImportError:
    from default import (
        CONFIG_KEY_SECRET_KEY,
        CONFIG_PATH,
        ROUTER_SECRET_MARKER as MARKER,
    )

MARKER_BYTES = MARKER.encode("ascii")
SECRET_RE = re.compile(
    rf"{re.escape(MARKER)}\s*\{{\s*([A-Za-z0-9_\-\s]+?)\s*\}}",
    re.S,
)


def die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)


def need(*names: str) -> None:
    for name in names:
        if shutil.which(name) is None:
            die(f"command not found: {name}")


def expand_config_path(raw: str, *, config_path: Path) -> Path:
    expanded = os.path.expandvars(os.path.expanduser(raw))
    path = Path(expanded)
    if not path.is_absolute():
        path = config_path.parent / path
    return path


def load_config(path: Path) -> dict[str, object]:
    if not path.exists():
        die(
            f"missing config file: {path}. "
            f"Secret encryption key path is read from config.{CONFIG_KEY_SECRET_KEY}"
        )

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"failed to parse JSON config {path}: {e}")

    if not isinstance(data, dict):
        die("config must be a JSON object")

    return data


def ensure_age_identity_file(path: Path) -> Path:
    if path.exists():
        if not path.is_file():
            die(f"age identity path exists but is not a file: {path}")
        return path

    need("age-keygen")
    path.parent.mkdir(parents=True, exist_ok=True)
    run_checked(["age-keygen", "-o", str(path)])
    path.chmod(0o600)
    print(f"Generated age identity: {path}")
    return path


def identity_path(config_path: Path = CONFIG_PATH) -> Path:
    config_path = config_path.expanduser()
    cfg = load_config(config_path)
    raw = cfg.get(CONFIG_KEY_SECRET_KEY)
    if not isinstance(raw, str) or not raw.strip():
        die(
            f"config.{CONFIG_KEY_SECRET_KEY} must be a non-empty path "
            "to an age identity file"
        )

    path = expand_config_path(raw.strip(), config_path=config_path)
    return ensure_age_identity_file(path)


def b64u_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64u_decode(text: str) -> bytes:
    pad = "=" * ((4 - len(text) % 4) % 4)
    try:
        return base64.urlsafe_b64decode((text + pad).encode("ascii"))
    except Exception as e:
        die(f"bad base64url secret payload: {e}")


def normalize_payload(text: str) -> str:
    payload = re.sub(r"\s+", "", text)
    if not payload:
        die("empty encrypted secret payload")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", payload):
        die("bad encrypted secret payload characters")
    return payload


def format_marker(payload: str, wrap: int | None = None) -> str:
    if wrap is None or wrap <= 0:
        return f"{MARKER}{{{payload}}}"

    lines = [payload[i : i + wrap] for i in range(0, len(payload), wrap)]
    return f"{MARKER}\n{{\n" + "\n".join(lines) + "\n}"


def run_checked(args: list[str], input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        args,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace").strip()
        die(err or f"command failed: {' '.join(args)}")
    return result.stdout


def public_recipient_from_identity(identity: Path) -> str:
    need("age-keygen")
    out = run_checked(["age-keygen", "-y", str(identity)]).decode(
        "utf-8", errors="replace"
    )
    recipient = out.strip()
    if not recipient.startswith("age1"):
        die(f"bad age recipient derived from identity: {recipient!r}")
    return recipient


def encrypt_bytes(
    plain: bytes,
    wrap: int | None = None,
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    if not plain:
        die("empty secret")

    need("age", "age-keygen")
    identity = identity_path(config_path)
    recipient = public_recipient_from_identity(identity)
    cipher = run_checked(["age", "-r", recipient], input_bytes=plain)
    return format_marker(b64u_encode(cipher), wrap)


def decrypt_payload(payload: str, *, config_path: Path = CONFIG_PATH) -> str:
    need("age")
    cipher = b64u_decode(normalize_payload(payload))
    plain = run_checked(
        ["age", "-d", "-i", str(identity_path(config_path))],
        input_bytes=cipher,
    )
    try:
        return plain.decode("utf-8")
    except UnicodeDecodeError:
        die("decrypted secret is not valid UTF-8")


def decrypt_text(
    text: str,
    where: str = "<text>",
    *,
    config_path: Path = CONFIG_PATH,
) -> str:
    def repl(match: re.Match[str]) -> str:
        payload = normalize_payload(match.group(1))
        try:
            return decrypt_payload(payload, config_path=config_path)
        except SystemExit:
            raise
        except Exception as e:
            die(f"{where}: failed to decrypt secret: {e}")

    return SECRET_RE.sub(repl, text)


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
    if MARKER_BYTES not in data:
        return False

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        die(f"{path}: encrypted marker found in non-UTF-8 file")

    new_text = decrypt_text(text, str(path), config_path=config_path)
    if new_text == text:
        return False

    path.write_text(new_text, encoding="utf-8")
    print(f"Decrypted secrets in {path}")
    return True


def decrypt_tree(paths: list[Path], *, config_path: Path = CONFIG_PATH) -> None:
    for path in iter_files(paths):
        decrypt_file(path, config_path=config_path)


def assert_no_markers(paths: list[Path]) -> None:
    found = False
    for path in iter_files(paths):
        data = path.read_bytes()
        if MARKER_BYTES in data:
            print(f"encrypted marker left in {path}", file=sys.stderr)
            found = True

    if found:
        die("encrypted secret markers are still present")


def cmd_encrypt(args: argparse.Namespace) -> None:
    if sys.stdin.isatty():
        secret = getpass.getpass("Secret: ").encode("utf-8")
    else:
        secret = sys.stdin.buffer.read()

    print(encrypt_bytes(secret, args.wrap, config_path=args.config))


def cmd_decrypt(args: argparse.Namespace) -> None:
    text = args.value if args.value is not None else sys.stdin.read()
    print(decrypt_text(text, config_path=args.config), end="")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description="Encrypt/decrypt ROUTER_SECRET_V1{ciphertext} markers"
    )
    ap.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help=(
            f"config file containing {CONFIG_KEY_SECRET_KEY!r}; "
            f"default: {CONFIG_PATH}"
        ),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("encrypt", help="read secret from stdin/TTY and print marker")
    p.add_argument(
        "--wrap",
        type=int,
        default=0,
        metavar="N",
        help="wrap encrypted payload to N columns inside marker; 0 disables wrapping",
    )
    p.set_defaults(func=cmd_encrypt)

    p = sub.add_parser("decrypt", help="decrypt markers in argument/stdin")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_decrypt)

    p = sub.add_parser("decrypt-tree", help="decrypt markers in files under paths")
    p.add_argument("paths", nargs="+", type=Path)
    p.set_defaults(func=lambda args: decrypt_tree(args.paths, config_path=args.config))

    p = sub.add_parser("assert-no-markers", help="fail if any marker remains")
    p.add_argument("paths", nargs="+", type=Path)
    p.set_defaults(func=lambda args: assert_no_markers(args.paths))

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
