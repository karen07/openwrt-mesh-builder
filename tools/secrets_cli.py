#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import getpass
from pathlib import Path

try:
    from .default import (
        CONFIG_PATH,
        OWMB_ENC_MATERIAL_MARKER,
        OWMB_ENC_SECRET_MARKER,
    )
    from .secrets import (
        assert_no_markers,
        decrypt_text,
        decrypt_tree,
        encrypt_payload,
        transform_tree,
    )
except ImportError:
    import importlib.util

    from default import (  # type: ignore
        CONFIG_PATH,
        OWMB_ENC_MATERIAL_MARKER,
        OWMB_ENC_SECRET_MARKER,
    )

    _secrets_path = Path(__file__).with_name("secrets.py")
    _secrets_spec = importlib.util.spec_from_file_location(
        "_owmb_secrets_impl",
        _secrets_path,
    )
    if _secrets_spec is None or _secrets_spec.loader is None:
        raise ImportError(f"cannot load OWMB secrets helper: {_secrets_path}")
    _secrets_impl = importlib.util.module_from_spec(_secrets_spec)
    sys.modules[_secrets_spec.name] = _secrets_impl
    _secrets_spec.loader.exec_module(_secrets_impl)

    assert_no_markers = _secrets_impl.assert_no_markers
    decrypt_text = _secrets_impl.decrypt_text
    decrypt_tree = _secrets_impl.decrypt_tree
    encrypt_payload = _secrets_impl.encrypt_payload
    transform_tree = _secrets_impl.transform_tree


def cmd_encrypt_value(args: argparse.Namespace, marker: str) -> None:
    if sys.stdin.isatty():
        value = getpass.getpass("Value: ").encode("utf-8")
    else:
        value = sys.stdin.buffer.read()
    print(encrypt_payload(value, marker, config_path=args.config, wrap=args.wrap))


def cmd_decrypt_value(args: argparse.Namespace) -> None:
    text = args.value if args.value is not None else sys.stdin.read()
    print(decrypt_text(text, config_path=args.config), end="")


def add_transform_subcommand(
    sub,
    name: str,
    *,
    direction: str,
    secrets: bool,
    materials: bool,
    help_text: str,
) -> None:
    p = sub.add_parser(name, help=help_text)
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--wrap", type=int, default=0, metavar="N")
    p.set_defaults(
        func=lambda args: transform_tree(
            args.paths,
            direction=direction,
            include_secrets=secrets,
            include_materials=materials,
            config_path=args.config,
            wrap=args.wrap,
        )
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Encrypt/decrypt OWMB secret markers")
    ap.add_argument(
        "--config",
        type=Path,
        default=CONFIG_PATH,
        help=f"config file; default: {CONFIG_PATH}",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser(
        "encrypt",
        help="read ordinary secret from stdin/TTY and print OWMB_ENC_SECRET_V1 marker",
    )
    p.add_argument("--wrap", type=int, default=0, metavar="N")
    p.set_defaults(func=lambda args: cmd_encrypt_value(args, OWMB_ENC_SECRET_MARKER))

    p = sub.add_parser("encrypt-secret", help="alias for encrypt")
    p.add_argument("--wrap", type=int, default=0, metavar="N")
    p.set_defaults(func=lambda args: cmd_encrypt_value(args, OWMB_ENC_SECRET_MARKER))

    p = sub.add_parser(
        "encrypt-material",
        help="read key material from stdin and print OWMB_ENC_MATERIAL_V1 marker",
    )
    p.add_argument("--wrap", type=int, default=0, metavar="N")
    p.set_defaults(func=lambda args: cmd_encrypt_value(args, OWMB_ENC_MATERIAL_MARKER))

    p = sub.add_parser("decrypt", help="decrypt markers in argument/stdin")
    p.add_argument("value", nargs="?")
    p.set_defaults(func=cmd_decrypt_value)

    add_transform_subcommand(
        sub,
        "encrypt-secrets",
        direction="encrypt",
        secrets=True,
        materials=False,
        help_text="OWMB_PLAIN_SECRET_V1 -> OWMB_ENC_SECRET_V1",
    )
    add_transform_subcommand(
        sub,
        "decrypt-secrets",
        direction="decrypt",
        secrets=True,
        materials=False,
        help_text="decrypt secret markers and remove OWMB marker wrappers",
    )
    add_transform_subcommand(
        sub,
        "encrypt-materials",
        direction="encrypt",
        secrets=False,
        materials=True,
        help_text="OWMB_PLAIN_MATERIAL_V1 -> OWMB_ENC_MATERIAL_V1",
    )
    add_transform_subcommand(
        sub,
        "decrypt-materials",
        direction="decrypt",
        secrets=False,
        materials=True,
        help_text="decrypt material markers and remove OWMB marker wrappers",
    )
    add_transform_subcommand(
        sub,
        "encrypt-all",
        direction="encrypt",
        secrets=True,
        materials=True,
        help_text="encrypt all plaintext OWMB markers",
    )
    add_transform_subcommand(
        sub,
        "decrypt-all",
        direction="decrypt",
        secrets=True,
        materials=True,
        help_text="decrypt all OWMB markers and remove OWMB marker wrappers",
    )
    add_transform_subcommand(
        sub,
        "decrypt-marked-secrets",
        direction="decrypt-marked",
        secrets=True,
        materials=False,
        help_text="OWMB_ENC_SECRET_V1 -> OWMB_PLAIN_SECRET_V1",
    )
    add_transform_subcommand(
        sub,
        "decrypt-marked-materials",
        direction="decrypt-marked",
        secrets=False,
        materials=True,
        help_text="OWMB_ENC_MATERIAL_V1 -> OWMB_PLAIN_MATERIAL_V1",
    )
    add_transform_subcommand(
        sub,
        "decrypt-marked-all",
        direction="decrypt-marked",
        secrets=True,
        materials=True,
        help_text="decrypt encrypted OWMB markers into plaintext OWMB markers",
    )

    p = sub.add_parser("decrypt-tree", help="alias-like raw decrypt for staging paths")
    p.add_argument("paths", nargs="+", type=Path)
    p.set_defaults(func=lambda args: decrypt_tree(args.paths, config_path=args.config))

    p = sub.add_parser(
        "assert-no-markers", help="fail if any OWMB/legacy marker remains"
    )
    p.add_argument("paths", nargs="+", type=Path)
    p.set_defaults(func=lambda args: assert_no_markers(args.paths))

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
