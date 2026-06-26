#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .managed_blocks import render_marked_uci_text
except ImportError:
    from common import *  # type: ignore
    from managed_blocks import render_marked_uci_text  # type: ignore


def update_network_part(
    cfg: ConfigData,
    router_name: str,
    mesh_text: str,
    exit_text: str,
    ipip_text: str,
    access_text: str,
    access_names: set[str],
) -> None:
    path = router_path(cfg, router_name, "network")
    original = read(path)

    before_marker, marker_and_tail = split_text_by_marker(original, path)

    mesh_exit_names = managed_mesh_exit_ifaces(cfg, router_name)

    def keep_block(parsed: dict[str, object]) -> bool:
        if is_managed_network(parsed, mesh_exit_names):
            return False
        if is_managed_access(parsed, access_names):
            return False
        return True

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)

    updated = render_marked_uci_text(
        [access_text, mesh_text, exit_text, ipip_text],
        preserved_before,
        marker_and_tail,
    )
    write(path, updated)


def build_babeld_text(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
) -> str:
    lines = [
        "config general",
        f"    option log_file '{BABELD_LOG_FILE}'",
        f"    option ubus_bindings '{BABELD_UBUS_BINDINGS}'",
        "",
    ]

    for iface in mesh_ifaces + exit_ifaces:
        lines += [
            "config interface",
            f"    option ifname '{iface}'",
            f"    option type '{BABELD_TUNNEL_TYPE}'",
            f"    option split_horizon '{BABELD_SPLIT_HORIZON}'",
            f"    option hello_interval '{BABELD_HELLO_INTERVAL}'",
            f"    option update_interval '{BABELD_UPDATE_INTERVAL}'",
            "",
        ]

    lines += [
        "config filter",
        "    option type 'redistribute'",
        f"    option if '{BABELD_LAN_IFACE}'",
        "    option action 'allow'",
        "",
    ]

    for iface in list_access_interfaces(cfg, router_name):
        lines += [
            "config filter",
            "    option type 'redistribute'",
            f"    option if '{iface}'",
            "    option action 'allow'",
            "",
        ]

    lines += [
        "config filter",
        "    option type 'redistribute'",
        "    option local 'true'",
        "    option action 'deny'",
        "",
        "config filter",
        "    option type 'redistribute'",
        "    option action 'deny'",
        "",
    ]

    return "\n" + "\n".join(lines).rstrip() + "\n"


def update_babeld(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
) -> None:
    path = router_path(cfg, router_name, "babeld")
    write(path, build_babeld_text(cfg, router_name, mesh_ifaces, exit_ifaces))


def list_access_interfaces(cfg: ConfigData, router_name: str) -> list[str]:
    return sorted(group.name for group in cfg.access.get(router_name, []))
