#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re

try:
    from .default import FIREWALL_MARKER
except ImportError:
    from default import FIREWALL_MARKER  # type: ignore


def split_uci_blocks(text: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    blocks: list[str] = []
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("".join(current))
            current = []

    for line in lines:
        stripped = line.strip()

        if line.startswith("config "):
            flush()
            current = [line]
            continue

        if stripped == FIREWALL_MARKER:
            flush()
            blocks.append(line)
            continue

        if current:
            current.append(line)
        else:
            blocks.append(line)

    flush()
    return blocks


def parse_uci_block(block: str) -> dict[str, object]:
    lines = block.splitlines()
    if not lines:
        return {}

    first = lines[0]
    m = re.match(r"^config\s+(\S+)\s+'([^']+)'\s*$", first)
    if m:
        cfg_type, cfg_name = m.group(1), m.group(2)
    else:
        m = re.match(r"^config\s+(\S+)\s*$", first)
        if not m:
            return {}
        cfg_type, cfg_name = m.group(1), m.group(1)

    options: dict[str, str] = {}
    lists: dict[str, list[str]] = {}

    for line in lines[1:]:
        m = re.match(r"^\s*option\s+(\S+)\s+'([^']*)'\s*$", line)
        if m:
            options[m.group(1)] = m.group(2)
            continue
        m = re.match(r"^\s*list\s+(\S+)\s+'([^']*)'\s*$", line)
        if m:
            lists.setdefault(m.group(1), []).append(m.group(2))

    return {
        "type": cfg_type,
        "name": cfg_name,
        "options": options,
        "lists": lists,
        "raw": block,
    }


def normalize_uci(text: str) -> str:
    blocks = [b.strip("\n") for b in split_uci_blocks(text) if b.strip("\n")]
    return "" if not blocks else "\n" + "\n\n".join(blocks) + "\n"


def render_uci_block(
    kind: str,
    name: str | None = None,
    *,
    options: dict[str, str] | None = None,
    lists: dict[str, list[str]] | None = None,
    private_key_transform: object | None = None,
) -> str:
    lines = [f"config {kind}" + (f" '{name}'" if name else "")]
    for k, v in (options or {}).items():
        if k == "private_key" and private_key_transform is not None:
            v = private_key_transform(v)  # type: ignore[operator]
        lines.append(f"    option {k} '{v}'")
    for k, vals in (lists or {}).items():
        for v in vals:
            lines.append(f"    list {k} '{v}'")
    return "\n".join(lines)
