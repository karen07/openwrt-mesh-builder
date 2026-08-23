#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .managed_blocks import (
        consume_expected_uci_block,
        generated_uci_management_keys,
        render_marked_uci_text,
        uci_counter_from_text,
        uci_management_key,
    )
except ImportError:
    from common import *  # type: ignore
    from managed_blocks import (  # type: ignore
        consume_expected_uci_block,
        generated_uci_management_keys,
        render_marked_uci_text,
        uci_counter_from_text,
        uci_management_key,
    )


def update_network_part(
    cfg: ConfigData,
    router_name: str,
    mesh_text: str,
    exit_text: str,
    ipip_text: str,
    exit_rule_text: str,
    access_text: str,
    access_names: set[str],
) -> None:
    path = router_path(cfg, router_name, "network")
    original = read(path)

    before_marker, marker_and_tail = split_text_by_marker(original, path)

    generated_parts = [access_text, mesh_text, exit_text, ipip_text, exit_rule_text]
    managed_keys = generated_uci_management_keys(generated_parts)
    anonymous_exit_blocks = uci_counter_from_text(
        exit_rule_text, where="generate_network"
    )

    def keep_block(parsed: dict[str, object]) -> bool:
        # Migrate the old named exit policy sections to anonymous UCI blocks.
        name = str(parsed.get("name", ""))
        typ = str(parsed.get("type", ""))
        if typ == "rule" and name.startswith(LEGACY_EXIT_RULE_SECTION_PREFIX):
            return False
        if typ == "route" and name.startswith(LEGACY_EXIT_RULE_ROUTE_SECTION_PREFIX):
            return False

        # Current exit rule/route sections are anonymous.  Consume an exact
        # generated match so repeated generation stays idempotent without
        # assigning artificial UCI section names.  Changed/obsolete anonymous
        # blocks remain unmanaged, matching the existing stale-object policy.
        raw = str(parsed.get("raw", ""))
        if raw and consume_expected_uci_block(
            anonymous_exit_blocks, raw, where="generate_network"
        ):
            return False
        return uci_management_key(parsed) not in managed_keys

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)

    updated = render_marked_uci_text(
        generated_parts,
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
