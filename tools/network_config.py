#!/usr/bin/env python3
from pathlib import Path

from .config_model import ConfigData
from .default import (
    FIREWALL_MARKER,
    PROTOCOL_AMNEZIAWG,
    PROTOCOL_WIREGUARD,
)
from .file_ops import read
from .layout import router_path
from .materials import (
    require_encrypted_material,
    stored_key_material,
    wireguard_private_key_plaintext,
)
from .process import die
from .uci import parse_uci_block, render_uci_block, split_uci_blocks


def uci_block(
    kind: str,
    name: str | None = None,
    *,
    options: dict[str, str] | None = None,
    lists: dict[str, list[str]] | None = None,
) -> str:
    return render_uci_block(
        kind,
        name,
        options=options,
        lists=lists,
        private_key_transform=stored_key_material,
    )


def find_access_peer_block(
    cfg_by_name: dict[str, dict[str, object]],
    iface_name: str,
    user_name: str,
    protocol: str = PROTOCOL_WIREGUARD,
) -> dict[str, object] | None:
    prefix = (
        PROTOCOL_AMNEZIAWG if protocol == PROTOCOL_AMNEZIAWG else PROTOCOL_WIREGUARD
    )
    want_type = f"{prefix}_{iface_name}"
    want_desc = f"{user_name}.conf"

    for block in cfg_by_name.values():
        if block.get("type") != want_type:
            continue
        if block.get("options", {}).get("description") == want_desc:
            return block

    return None


def split_text_by_marker(text: str, path: Path) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.rstrip("\n") == FIREWALL_MARKER:
            return "".join(lines[:i]), "".join(lines[i:])
    die(f"marker not found in {path}: {FIREWALL_MARKER}")


def parse_network_part(cfg: ConfigData, router: str) -> dict[str, dict[str, object]]:
    path = router_path(cfg, router, "network")
    if not path.exists():
        return {}

    out: dict[str, dict[str, object]] = {}
    counter = 0
    for block in split_uci_blocks(read(path)):
        parsed = parse_uci_block(block)
        if parsed:
            key = str(parsed["name"])
            if key in out:
                counter += 1
                key = f"{key}#{counter}"
            out[key] = parsed
    return out


def load_existing_network_cfgs(
    cfg: ConfigData,
) -> dict[str, dict[str, dict[str, object]]]:
    return {router: parse_network_part(cfg, router) for router in cfg.router_names}


def get_interface_private_key(
    cfg_by_name: dict[str, dict[str, object]],
    iface: str,
) -> str | None:
    for block in cfg_by_name.values():
        if block.get("type") == "interface" and block.get("name") == iface:
            value = block["options"].get("private_key")
            if value:
                require_encrypted_material(value, f"network_part.{iface}.private_key")
            return wireguard_private_key_plaintext(value) if value else None
    return None


def get_interface_option(
    cfg_by_name: dict[str, dict[str, object]],
    iface: str,
    option_name: str,
) -> str | None:
    for block in cfg_by_name.values():
        if block.get("type") == "interface" and block.get("name") == iface:
            return block["options"].get(option_name)
    return None
