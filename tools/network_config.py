#!/usr/bin/env python3
from pathlib import Path

try:
    from .process import die
    from .default import FIREWALL_MARKER, PROTOCOL_AMNEZIAWG, PROTOCOL_WIREGUARD
    from .config_model import ConfigData
    from .layout import router_path
    from .link_model import (
        exit_in_iface_name,
        exit_out_iface_name,
        mesh_iface_names_for_router,
    )
    from .materials import (
        material_plaintext,
        stored_key_material,
        wireguard_private_key_plaintext,
    )
    from .file_ops import read
    from .uci import parse_uci_block, render_uci_block, split_uci_blocks
    from .config_builder import router_exit_ipip_iface_name
except ImportError:
    from process import die  # type: ignore
    from default import FIREWALL_MARKER, PROTOCOL_AMNEZIAWG, PROTOCOL_WIREGUARD  # type: ignore
    from config_model import ConfigData  # type: ignore
    from layout import router_path  # type: ignore
    from link_model import (  # type: ignore
        exit_in_iface_name,
        exit_out_iface_name,
        mesh_iface_names_for_router,
    )
    from materials import (  # type: ignore
        material_plaintext,
        stored_key_material,
        wireguard_private_key_plaintext,
    )
    from file_ops import read  # type: ignore
    from uci import parse_uci_block, render_uci_block, split_uci_blocks  # type: ignore
    from config_builder import router_exit_ipip_iface_name  # type: ignore


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


def current_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = mesh_iface_names_for_router(cfg, router_name)

    for hub in cfg.exit_hubs:
        names.add(exit_out_iface_name(hub.name))
        names.add(exit_in_iface_name(hub.name))
        names.add(router_exit_ipip_iface_name(hub.name))

    return names


def managed_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return current_mesh_exit_ifaces(cfg, router_name)


def is_managed_network(
    parsed: dict[str, object],
    mesh_exit_ifaces: set[str] | None = None,
) -> bool:
    typ = str(parsed.get("type", ""))
    name = str(parsed.get("name", ""))
    mesh_exit_ifaces = mesh_exit_ifaces or set()

    # Current mesh/exit generated sections.
    if typ == "interface" and name in mesh_exit_ifaces:
        return True
    if name in {f"amneziawg_{iface}" for iface in mesh_exit_ifaces} | {
        f"wireguard_{iface}" for iface in mesh_exit_ifaces
    }:
        return True

    return False


def is_managed_access(parsed: dict[str, object], access_names: set[str]) -> bool:
    typ = str(parsed.get("type", ""))
    name = str(parsed.get("name", ""))

    if typ == "interface" and name in access_names:
        return True

    if typ.startswith("wireguard_") and typ == name:
        iface = typ.removeprefix("wireguard_")
        if iface in access_names:
            return True

    if typ.startswith("amneziawg_") and typ == name:
        iface = typ.removeprefix("amneziawg_")
        if iface in access_names:
            return True

    return False


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


def filter_preserved_before_marker(text_before_marker: str, keep) -> str:
    out: list[str] = []
    for block in split_uci_blocks(text_before_marker):
        parsed = parse_uci_block(block)
        if not parsed:
            out.append(block)
            continue
        if keep(parsed):
            out.append(block)
    joined = "".join(out).rstrip()
    return joined + "\n" if joined else ""


def parse_network_part(cfg: ConfigData, router: str) -> dict[str, dict[str, object]]:
    path = router_path(cfg, router, "network")
    if not path.exists():
        die(f"missing file: {path}")

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
