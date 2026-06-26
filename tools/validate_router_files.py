#!/usr/bin/env python3
import re
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .generated_files import exit_server_aliases_for_hub
    from .validate_network import (
        expected_amneziawg_access_ifaces,
        expected_tunnel_ifaces,
    )
    from .validate_uci import parse_uci_block, parse_uci_file
except ImportError:
    from common import *  # type: ignore
    from generated_files import exit_server_aliases_for_hub  # type: ignore
    from validate_network import (  # type: ignore
        expected_amneziawg_access_ifaces,
        expected_tunnel_ifaces,
    )
    from validate_uci import parse_uci_block, parse_uci_file  # type: ignore


def validate_babeld(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "babeld")
        parsed = parse_uci_file(path)
        actual: list[str] = []
        for block in parsed:
            if block.get("type") != "interface":
                continue
            ifname = block.get("options", {}).get("ifname")
            if not ifname:
                die(f"{path}: babel interface without ifname")
            if ifname in actual:
                die(f"{path}: duplicate babel interface {ifname}")
            actual.append(str(ifname))

        expected = expected_tunnel_ifaces(cfg, router_name)
        if set(actual) != expected:
            die(
                f"{path}: bad babel tunnel interfaces: "
                f"expected {sorted(expected)}, got {sorted(actual)}"
            )

    for hub in cfg.exit_hubs:
        path = server_babeld_conf_path(hub.name)
        if not path.exists():
            die(f"missing file: {path}")
        actual = set(
            re.findall(r"(?m)^interface\s+(\S+)\s+type\s+tunnel\b", read(path))
        )
        expected = set(exit_server_aliases_for_hub(cfg, hub))
        if actual != expected:
            die(
                f"{path}: bad Exit hub server babel interfaces: "
                f"expected {sorted(expected)}, got {sorted(actual)}"
            )

        lines = read(path).splitlines()

        if "install allow" not in lines:
            die(f"{path}: missing 'install allow'")

        stale_server_babel_lines = {
            "in allow",
            "install deny",
            f"redistribute ip {hub.announce}",
            f"out ip {hub.announce}",
            "out deny",
        }
        for stale in sorted(stale_server_babel_lines):
            if stale in lines:
                die(f"{path}: stale server babel line {stale!r}")

        unexpected_node_redistribute = f"redistribute ip {exit_node_prefix(hub)} allow"
        if unexpected_node_redistribute in lines:
            die(f"{path}: stale server babel line {unexpected_node_redistribute!r}")

        expected_node_redistribute = f"redistribute if {NODE_SERVER_IFACE} allow"
        if expected_node_redistribute not in lines:
            die(f"{path}: missing {expected_node_redistribute!r}")

        expected_redistribute = f"redistribute if {IPIP_SERVER_IFACE} allow"
        if expected_redistribute not in lines:
            die(f"{path}: missing {expected_redistribute!r}")


def validate_router_network_parse_clean(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "network")
        seen_interfaces: set[str] = set()
        seen_amnezia_peers: set[str] = set()
        wg_peer_descriptions: dict[str, set[str]] = {}

        for block_text in split_uci_blocks(read(path)):
            parsed = parse_uci_block(block_text)
            if not parsed:
                continue

            typ = str(parsed.get("type", ""))
            name = str(parsed.get("name", ""))
            opts = parsed.get("options", {})

            if typ == "interface":
                if name in seen_interfaces:
                    die(f"{path}: duplicate interface section {name}")
                seen_interfaces.add(name)

            if typ.startswith("amneziawg_"):
                iface = typ.removeprefix("amneziawg_")
                if iface in expected_amneziawg_access_ifaces(cfg, router_name):
                    desc = str(opts.get("description", ""))
                    if not desc:
                        die(
                            f"{path}: AmneziaWG access peer section {typ} without description"
                        )
                    seen = wg_peer_descriptions.setdefault(typ, set())
                    if desc in seen:
                        die(
                            f"{path}: duplicate AmneziaWG access peer description {typ}/{desc}"
                        )
                    seen.add(desc)
                else:
                    if typ in seen_amnezia_peers:
                        die(f"{path}: duplicate AmneziaWG peer section {typ}")
                    seen_amnezia_peers.add(typ)

            if typ.startswith("wireguard_"):
                desc = str(opts.get("description", ""))
                if not desc:
                    die(f"{path}: WireGuard peer section {typ} without description")
                seen = wg_peer_descriptions.setdefault(typ, set())
                if desc in seen:
                    die(f"{path}: duplicate WireGuard peer description {typ}/{desc}")
                seen.add(desc)
