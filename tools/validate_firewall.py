#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

from .config_exit_model import router_exit_ipip_iface_name, router_required_exit_hubs
from .config_firewall_model import (
    expand_firewall_targets,
    firewall_allow_rule_name,
    mesh_firewall_rule_name,
)
from .config_model import ConfigData
from .config_schema import FIREWALL_ALLOW_KIND_LAN
from .default import (
    ACCESS_POLICY_TRANSIT,
    ACCESS_POLICY_TRUSTED,
    DNS_PORT,
    DNS_PROTOCOLS,
    EXIT_POLICY_BASE,
    FIREWALL_MARKER,
    FIREWALL_TARGET_ACCEPT,
    FIREWALL_TARGET_REJECT,
    FIREWALL_ZONE_LAN,
    FIREWALL_ZONE_WAN,
    PROTOCOL_OPENVPN,
    TRANSIT_ACCESS_DNS_RULE_NAME,
    TRANSPORT_TCP,
    TRANSPORT_UDP,
    ZONE_EXIT,
    ZONE_EXIT_IPIP,
    ZONE_MESH,
    ZONE_TRANSIT_ACCESS,
    ZONE_TRUSTED_ACCESS,
)
from .file_ops import read
from .generate_firewall import build_firewall_blocks
from .layout import router_path
from .link_model import (
    compute_mesh_link_params,
    exit_in_iface_name,
    exit_out_iface_name,
    mesh_iface_names_for_router,
    mesh_link_specs_for_hub,
)
from .process import die
from .tunnel_model import (
    exit_hub_is_public,
    exit_reverse_firewall_rule_name,
    router_exit_listen_port,
    router_is_public_mesh_hub,
)
from .uci import parse_uci_block, split_uci_blocks
from .validate_uci import (
    find_firewall_rule_by_name,
    parse_uci_file,
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


def require_firewall_overlay_source_rule(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    name: str,
    source_zone: str,
    source_ip: str,
    dest_zone: str | None,
) -> None:
    block = find_firewall_rule_by_name(parsed_blocks, name)
    if block is None:
        die(f"{path}: missing firewall rule {name}")
    opts = block.get("options", {})
    lists = block.get("lists", {})
    if opts.get("src") != source_zone:
        die(
            f"{path}: firewall rule {name}: bad src; "
            f"expected {source_zone!r}, got {opts.get('src')!r}"
        )
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


def require_shared_exit_mark_rules(
    parsed_blocks: list[dict[str, object]],
    path: Path,
    *,
    present_zones: set[str],
    initial_mode: str,
) -> None:
    mark_specs = {
        "Exitlan": FIREWALL_ZONE_LAN,
        "ExitTrustedAccess": ZONE_TRUSTED_ACCESS,
        "ExitTransitAccess": ZONE_TRANSIT_ACCESS,
    }

    for name, src in mark_specs.items():
        matches = [
            block
            for block in parsed_blocks
            if block.get("type") == "rule"
            and block.get("options", {}).get("name") == name
        ]
        if src not in present_zones:
            if matches:
                die(f"{path}: stale firewall rule for absent zone {src}")
            continue
        if len(matches) != 1:
            die(
                f"{path}: expected exactly one firewall rule {name}, got {len(matches)}"
            )
        opts = matches[0].get("options", {})
        lists = matches[0].get("lists", {})
        expected = {
            "src": src,
            "dest": "*",
            "mark": "0",
            "target": "MARK",
            "set_mark": str(EXIT_POLICY_BASE),
            "family": "ipv4",
        }
        for key, value in expected.items():
            if opts.get(key) != value:
                die(
                    f"{path}: firewall rule {name}: bad {key}; "
                    f"expected {value!r}, got {opts.get(key)!r}"
                )
        expected_ipset = initial_mode not in {"EXIT_FAIL_OPEN", "EXIT_FAIL_CLOSED"}
        if (opts.get("ipset") == "!direct") != expected_ipset:
            die(f"{path}: firewall rule {name}: bad direct policy")
        if opts.get("enabled") != ("0" if initial_mode == "DIRECT" else None):
            die(f"{path}: firewall rule {name}: bad initial state")
        if lists.get("proto", []) != ["all"]:
            die(f"{path}: firewall rule {name}: bad proto")


def validate_firewall(cfg: ConfigData) -> None:
    for router_name in cfg.router_names:
        path = router_path(cfg, router_name, "firewall")
        text = read(path)
        parsed = parse_uci_file(path)
        # Compare canonical parsed content rather than minor whitespace differences.
        # A generated firewall_part must contain no unmanaged or template sections.
        # Runtime UCI updates happen to /etc/config/firewall on the router.
        if FIREWALL_MARKER in text:
            die(f"{path}: unexpected template marker in generated firewall")

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
            for hub in router_required_exit_hubs(cfg, router_name)
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

        if mesh_ifaces:
            require_firewall_zone_policy(
                parsed,
                path,
                ZONE_MESH,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward_policy=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            )
        if exit_ifaces:
            require_firewall_zone_policy(
                parsed,
                path,
                ZONE_EXIT,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward_policy=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            )
        if exit_ipip_ifaces:
            require_firewall_zone_policy(
                parsed,
                path,
                ZONE_EXIT_IPIP,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward_policy=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            )

        present_zones = {FIREWALL_ZONE_LAN, FIREWALL_ZONE_WAN}
        for zones, name in (
            (mesh_ifaces, ZONE_MESH),
            (exit_ifaces, ZONE_EXIT),
            (exit_ipip_ifaces, ZONE_EXIT_IPIP),
            (trusted_access, ZONE_TRUSTED_ACCESS),
            (transit_access, ZONE_TRANSIT_ACCESS),
        ):
            if zones:
                present_zones.add(name)
        initial_mode = cfg.exit_routes_by_router[router_name].mode
        require_shared_exit_mark_rules(
            parsed,
            path,
            present_zones=present_zones,
            initial_mode=initial_mode,
        )

        generated = build_firewall_blocks(
            cfg,
            router_name,
            sorted(mesh_ifaces),
            sorted(exit_ifaces),
            sorted(exit_ipip_ifaces),
            cfg.access.get(router_name, []),
        )
        expected_parsed = [
            parse_uci_block(block)
            for part in generated
            for block in split_uci_blocks(part)
            if parse_uci_block(block)
        ]

        def canonical(block):
            return (
                block["type"],
                block["name"],
                tuple(sorted(block["options"].items())),
                tuple(sorted((k, tuple(sorted(v))) for k, v in block["lists"].items())),
            )

        if [canonical(block) for block in parsed] != [
            canonical(block) for block in expected_parsed
        ]:
            die(f"{path}: firewall_part does not match the generated model")

        # The clear-mark rule is generated along with all other firewall rules.
        # Do not require exact names here: this allows switching between
        # mark-to-main and clear-mark variants without touching validate.py.

        if trusted_access:
            require_firewall_zone_policy(
                parsed,
                path,
                ZONE_TRUSTED_ACCESS,
                input_policy=FIREWALL_TARGET_ACCEPT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward_policy=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            )
        if transit_access:
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
            require_firewall_dns_transit_access_rule(parsed, path)

        if router_name in cfg.mesh_hubs_by_name:
            hub = cfg.mesh_hubs_by_name[router_name]
            for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
                link = compute_mesh_link_params(cfg, hub, target_name)
                rule_name = mesh_firewall_rule_name(hub.name, target_name)
                require_firewall_rule_port(
                    parsed, path, rule_name, link.port, TRANSPORT_UDP
                )

            for exit_hub in cfg.exit_hubs:
                rule_name = exit_reverse_firewall_rule_name(exit_hub.name)
                require_firewall_rule_port(
                    parsed,
                    path,
                    rule_name,
                    router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                )

        for group in cfg.access.get(router_name, []):
            rule_name = f"Allow-{group.name}"
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

        overlay_src_zones: list[str] = []
        if mesh_ifaces:
            overlay_src_zones.append(ZONE_MESH)
        if exit_ifaces:
            overlay_src_zones.append(ZONE_EXIT)

        for allow in cfg.firewall_allows:
            if router_name not in expand_firewall_targets(cfg, allow):
                continue
            for src_zone in overlay_src_zones:
                rule_name = firewall_allow_rule_name(
                    allow.source_name, router_name, allow.kind, src_zone
                )
                require_firewall_overlay_source_rule(
                    parsed,
                    path,
                    rule_name,
                    src_zone,
                    allow.source_subnet,
                    (
                        FIREWALL_ZONE_LAN
                        if allow.kind == FIREWALL_ALLOW_KIND_LAN
                        else None
                    ),
                )
