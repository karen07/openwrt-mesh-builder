#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .common import *
except ImportError:
    from common import *  # type: ignore


def parse_uci_file(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        die(f"missing file: {path}")
    return [
        parsed
        for parsed in (parse_uci_block(block) for block in split_uci_blocks(read(path)))
        if parsed
    ]


def find_firewall_rule_by_name(
    parsed_blocks: list[dict[str, object]], name: str
) -> dict[str, object] | None:
    for block in parsed_blocks:
        if block.get("type") != "rule":
            continue
        options = block.get("options", {})
        if options.get("name") == name:
            return block
    return None


def require_firewall_rule_port(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    port: int,
    proto: str,
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")

    options = block.get("options", {})
    if options.get("src") != FIREWALL_ZONE_WAN:
        die(f"{path}: firewall rule {name}: bad src")
    if options.get("dest_port") != str(port):
        die(f"{path}: firewall rule {name}: bad dest_port")
    if options.get("proto") != proto:
        die(f"{path}: firewall rule {name}: bad proto")
    if options.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")


def require_firewall_rule_absent(
    parsed_blocks: list[dict[str, object]], path: Path, name: str
) -> None:
    if find_firewall_rule_by_name(parsed_blocks, name) is not None:
        die(f"{path}: stale firewall rule {name}")
