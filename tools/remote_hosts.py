#!/usr/bin/env python3
"""Remote host alias helpers."""

import sys

sys.dont_write_bytecode = True

try:
    from .process import die
    from .default import SERVER_SSH_PREFIX
except ImportError:
    from process import die  # type: ignore
    from default import SERVER_SSH_PREFIX  # type: ignore


SERVER_SSH_MODE_CHOICES = ("auto", "node", "public")


def server_ssh_alias(name: str) -> str:
    return f"{SERVER_SSH_PREFIX}{name.lower()}"


def server_ssh_node_alias(name: str) -> str:
    return f"{server_ssh_alias(name)}_node"


def server_ssh_hosts(name: str, mode: str = "auto") -> tuple[str, ...]:
    public = server_ssh_alias(name)
    node = server_ssh_node_alias(name)

    if mode == "auto":
        return (node, public)
    if mode == "node":
        return (node,)
    if mode == "public":
        return (public,)

    die(f"bad server SSH mode: {mode}")
