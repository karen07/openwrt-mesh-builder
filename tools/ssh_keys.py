#!/usr/bin/env python3
"""OpenSSH access-key helpers backed by `ssh-keygen`."""

import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .process import need, run_checked
except ImportError:
    from process import need, run_checked


def generate_ed25519_key(path: Path, *, comment: str, mode: int) -> None:
    need("ssh-keygen")
    run_checked(
        [
            "ssh-keygen",
            "-t",
            "ed25519",
            "-f",
            str(path),
            "-N",
            "",
            "-C",
            comment,
        ],
        quiet=True,
    )
    path.chmod(mode)


def public_key_from_private(path: Path) -> str:
    need("ssh-keygen")
    return run_checked(["ssh-keygen", "-y", "-f", str(path)])
