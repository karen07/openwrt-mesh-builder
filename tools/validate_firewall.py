#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .common import *
    from .tunnel_model import (
        exit_hub_is_public,
        exit_reverse_firewall_rule_name,
        router_exit_listen_port,
        router_is_public_mesh_hub,
    )
    from .validate_uci import (
        find_firewall_rule_by_name,
        parse_uci_file,
        require_firewall_rule_absent,
        require_firewall_rule_port,
    )
except ImportError:
    from common import *  # type: ignore
    from tunnel_model import (  # type: ignore
        exit_hub_is_public,
        exit_reverse_firewall_rule_name,
        router_exit_listen_port,
        router_is_public_mesh_hub,
    )
    from validate_uci import (  # type: ignore
        find_firewall_rule_by_name,
        parse_uci_file,
        require_firewall_rule_absent,
        require_firewall_rule_port,
    )


def find_firewall_zone_by_name(
    parsed_blocks: list[dict[str, object]], name: str
) -> dict[str, object] | None:
    for block in parsed_blocks:
        if block.get("type") != "zone":
            continue
        if block.get("options", {}).get("name") == name:
            return block
    return None


def require_firewall_zone_networks(
    parsed_blocks: list[dict[str, object]], path: Path, name: str, expected: set[str]
) -> None:
    block = find_firewall_zone_by_name(parsed_blocks, name)
    if not expected:
        if block is not None:
            die(f"{path}: stale firewall zone {name}")
        return
    if block is None:
        die(f"{path}: missing firewall zone {name}")

    actual_list = block.get("lists", {}).get("network", [])
    actual = set(actual_list)
    if len(actual) != len(actual_list):
        die(f"{path}: firewall zone {name}: duplicate network entry")
    if actual != expected:
        die(
            f"{path}: firewall zone {name}: "
            f"expected networks {sorted(expected)}, got {sorted(actual)}"
        )


def require_firewall_zone_policy(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    *,
    input_policy: str,
    output_policy: str,
    forward_policy: str,
    masq: bool = False,
    mtu_fix: bool | None = None,
) -> None:
    block = find_firewall_zone_by_name(parsed_blocks, name)
    if block is None:
        return

    opts = block.get("options", {})
    expected = {
        "input": input_policy,
        "output": output_policy,
        "forward": forward_policy,
    }
    for key, value in expected.items():
        if opts.get(key) != value:
            die(
                f"{path}: firewall zone {name}: bad {key}: "
                f"expected {value!r}, got {opts.get(key)!r}"
            )

    if masq:
        if opts.get("masq") != "1":
            die(f"{path}: firewall zone {name}: missing masq")
    elif "masq" in opts:
        die(f"{path}: firewall zone {name}: stale masq")

    expected_mtu_fix = masq if mtu_fix is None else mtu_fix
    if expected_mtu_fix:
        if opts.get("mtu_fix") != "1":
            die(f"{path}: firewall zone {name}: missing mtu_fix")
    elif "mtu_fix" in opts:
        die(f"{path}: firewall zone {name}: stale mtu_fix")


def require_firewall_mesh_source_rule(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    source_ip: str,
    dest_zone: str | None,
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")
    opts = block.get("options", {})
    lists = block.get("lists", {})
    if opts.get("src") != ZONE_MESH:
        die(f"{path}: firewall rule {name}: bad src")
    if dest_zone is None:
        if "dest" in opts:
            die(f"{path}: firewall rule {name}: unexpected dest")
    elif opts.get("dest") != dest_zone:
        die(f"{path}: firewall rule {name}: bad dest")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")
    if opts.get("family") != "ipv4":
        die(f"{path}: firewall rule {name}: bad family")
    if opts.get("proto") != "all":
        die(f"{path}: firewall rule {name}: bad proto")
    if lists.get("src_ip", []) != [source_ip]:
        die(f"{path}: firewall rule {name}: bad src_ip")


def require_firewall_dns_transit_access_rule(
    parsed_blocks: list[dict[str, object]], path: Path
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, TRANSIT_ACCESS_DNS_RULE_NAME)
    if block is None:
        die(f"{path}: missing firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}")

    opts = block.get("options", {})
    lists = block.get("lists", {})
    if opts.get("src") != ZONE_TRANSIT_ACCESS:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad src")
    if opts.get("dest_port") != str(DNS_PORT):
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad dest_port")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad target")
    if lists.get("proto", []) != DNS_PROTOCOLS:
        die(f"{path}: firewall rule {TRANSIT_ACCESS_DNS_RULE_NAME}: bad proto")


def require_firewall_ssh_from_exit_rule(
    parsed_blocks: list[dict[str, object]], path: Path
) -> None:
    name = "Allow-SSH-From-Exit-To-Router"
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")

    opts = block.get("options", {})
    if opts.get("src") != ZONE_EXIT:
        die(f"{path}: firewall rule {name}: bad src")
    if opts.get("proto") != TRANSPORT_TCP:
        die(f"{path}: firewall rule {name}: bad proto")
    if opts.get("dest_port") != "22":
        die(f"{path}: firewall rule {name}: bad dest_port")
    if opts.get("target") != FIREWALL_TARGET_ACCEPT:
        die(f"{path}: firewall rule {name}: bad target")


def validate_firewall(cfg: ConfigData) -> None:
    expected_rule_names_by_router: dict[str, set[str]] = {
        name: set() for name in cfg.router_names
    }

    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "firewall")
        parsed = parse_uci_file(path)

        mesh_ifaces = mesh_iface_names_for_router(cfg, router_name)

        exit_ifaces = {
            exit_out_iface_name(hub.name)
            for hub in cfg.exit_hubs
            if exit_hub_is_public(hub)
        }
        if router_is_public_mesh_hub(cfg, router_name):
            exit_ifaces |= {exit_in_iface_name(hub.name) for hub in cfg.exit_hubs}
        exit_ipip_ifaces = {
            router_exit_ipip_iface_name(hub.name)
            for hub in router_exit_order_hubs(cfg, router_name)
        }
        trusted_access = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.policy == ACCESS_POLICY_TRUSTED
        }
        transit_access = {
            g.name
            for g in cfg.access.get(router_name, [])
            if g.policy == ACCESS_POLICY_TRANSIT
        }

        require_firewall_zone_networks(parsed, path, ZONE_MESH, mesh_ifaces)
        require_firewall_zone_networks(parsed, path, ZONE_EXIT, exit_ifaces)
        require_firewall_zone_networks(parsed, path, ZONE_EXIT_IPIP, exit_ipip_ifaces)
        require_firewall_zone_networks(
            parsed, path, ZONE_TRUSTED_ACCESS, trusted_access
        )
        require_firewall_zone_networks(
            parsed, path, ZONE_TRANSIT_ACCESS, transit_access
        )

        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_MESH,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_EXIT,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_EXIT_IPIP,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )

        # ExitIPIP rule/forwarding entries live in the shared firewall tail.
        # Do not require exact names here: this allows switching between
        # mark-to-main and clear-mark variants without touching validate.py.

        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_TRUSTED_ACCESS,
            input_policy=FIREWALL_TARGET_ACCEPT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )
        require_firewall_zone_policy(
            parsed,
            path,
            ZONE_TRANSIT_ACCESS,
            input_policy=FIREWALL_TARGET_REJECT,
            output_policy=FIREWALL_TARGET_ACCEPT,
            forward_policy=FIREWALL_TARGET_ACCEPT,
            mtu_fix=True,
        )

        if transit_access:
            expected_rule_names_by_router[router_name].add(TRANSIT_ACCESS_DNS_RULE_NAME)
            require_firewall_dns_transit_access_rule(parsed, path)
        else:
            require_firewall_rule_absent(parsed, path, TRANSIT_ACCESS_DNS_RULE_NAME)

        if config_has_allow_to_router_all(cfg):
            require_firewall_rule_absent(parsed, path, "Allow-SSH-From-Exit-To-Router")
        else:
            expected_rule_names_by_router[router_name].add(
                "Allow-SSH-From-Exit-To-Router"
            )
            require_firewall_ssh_from_exit_rule(parsed, path)

        require_firewall_rule_absent(parsed, path, FIREWALL_RULE_ALLOW_MESH)

        if router_name in cfg.mesh_hubs_by_name:
            hub = cfg.mesh_hubs_by_name[router_name]
            for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
                link = compute_mesh_link_params(cfg, hub, target_name)
                rule_name = mesh_firewall_rule_name(hub.name, target_name)
                expected_rule_names_by_router[router_name].add(rule_name)
                require_firewall_rule_port(
                    parsed, path, rule_name, link.port, TRANSPORT_UDP
                )

            for exit_hub in cfg.exit_hubs:
                rule_name = exit_reverse_firewall_rule_name(exit_hub.name)
                expected_rule_names_by_router[router_name].add(rule_name)
                require_firewall_rule_port(
                    parsed,
                    path,
                    rule_name,
                    router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                )

        for group in cfg.access.get(router_name, []):
            rule_name = f"Allow-{group.name}"
            expected_rule_names_by_router[router_name].add(rule_name)
            require_firewall_rule_port(
                parsed,
                path,
                rule_name,
                group.port,
                (
                    TRANSPORT_TCP
                    if group.protocol == PROTOCOL_OPENVPN
                    else TRANSPORT_UDP
                ),
            )

        for allow in cfg.firewall_allows:
            if router_name not in expand_firewall_targets(cfg, allow):
                continue
            rule_name = firewall_allow_rule_name(
                allow.source_name, router_name, allow.kind
            )
            expected_rule_names_by_router[router_name].add(rule_name)
            require_firewall_mesh_source_rule(
                parsed,
                path,
                rule_name,
                allow.source_subnet,
                FIREWALL_ZONE_LAN if allow.kind == FIREWALL_ALLOW_KIND_LAN else None,
            )

        managed_zones = set(MANAGED_FIREWALL_ZONES) | {ZONE_EXIT_IPIP}
        seen_zones: set[str] = set()
        for block in parsed:
            if block.get("type") == "zone":
                zone_name = str(block.get("options", {}).get("name", ""))
                if zone_name in managed_zones:
                    if zone_name in seen_zones:
                        die(f"{path}: duplicate managed firewall zone {zone_name}")
                    seen_zones.add(zone_name)

            if block.get("type") == "rule":
                rule_name = str(block.get("options", {}).get("name", ""))
                looks_managed = (
                    rule_name.startswith("Allow-Mesh-")
                    or rule_name.startswith("Allow-Exit-Reverse-")
                    or (rule_name.startswith("Allow-") and "-To-" in rule_name)
                    or rule_name == TRANSIT_ACCESS_DNS_RULE_NAME
                    or rule_name
                    in {f"Allow-{g.name}" for g in cfg.access.get(router_name, [])}
                )
                if (
                    looks_managed
                    and rule_name not in expected_rule_names_by_router[router_name]
                ):
                    die(f"{path}: stale managed firewall rule {rule_name}")
