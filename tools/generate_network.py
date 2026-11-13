#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

from .config_model import ConfigData
from .default import (
    BABELD_LAN_IFACE,
    BABELD_LOG_FILE,
    BABELD_SPLIT_HORIZON,
    BABELD_TUNNEL_TYPE,
    BABELD_UBUS_BINDINGS,
)
from .file_ops import write
from .layout import router_path
from .stable_model import stable_babel_intervals
from .uci import normalize_uci


def update_network_part(
    cfg: ConfigData,
    router_name: str,
    mesh_text: str,
    exit_text: str,
    ipip_text: str,
    exit_rule_text: str,
    access_text: str,
) -> None:
    # The existing file is also read earlier for tunnel key reuse.
    path = router_path(cfg, router_name, "network")
    parts = [access_text, mesh_text, exit_text, ipip_text, exit_rule_text]
    blocks = [part.strip() for part in parts if part.strip()]
    generated = normalize_uci("\n\n".join(blocks)).strip("\n")
    write(path, "\n" + generated + "\n")


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
        hello_interval, update_interval = stable_babel_intervals(router_name, iface)
        lines += [
            "config interface",
            f"    option ifname '{iface}'",
            f"    option type '{BABELD_TUNNEL_TYPE}'",
            f"    option split_horizon '{BABELD_SPLIT_HORIZON}'",
            f"    option hello_interval '{hello_interval}'",
            f"    option update_interval '{update_interval}'",
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
