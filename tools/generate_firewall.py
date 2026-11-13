#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

from .config_exit_model import routing_exit_policy_ids
from .config_firewall_model import (
    expand_firewall_targets,
    firewall_allow_rule_name,
    mesh_firewall_rule_name,
)
from .config_model import AccessGroup, ConfigData
from .config_schema import FIREWALL_ALLOW_KIND_LAN
from .default import (
    ACCESS_POLICY_TRANSIT,
    ACCESS_POLICY_TRUSTED,
    DNS_PORT,
    DNS_PROTOCOLS,
    EXIT_POLICY_BASE,
    FIREWALL_TARGET_ACCEPT,
    FIREWALL_TARGET_REJECT,
    FIREWALL_ZONE_LAN,
    FIREWALL_ZONE_WAN,
    PROTOCOL_OPENVPN,
    ROUTING_WAN_MARK_TEXT,
    RUNTIME_DIRECT_OUT_NAME,
    RUNTIME_DIRECT_STATIC_NAME,
    RUNTIME_IPSETS_DIR,
    TRANSIT_ACCESS_DNS_RULE_NAME,
    TRANSPORT_TCP,
    TRANSPORT_UDP,
    ZONE_EXIT,
    ZONE_EXIT_IPIP,
    ZONE_MESH,
    ZONE_TRANSIT_ACCESS,
    ZONE_TRUSTED_ACCESS,
)
from .file_ops import write
from .generate_runtime import build_exit_route_config
from .layout import router_path
from .link_model import compute_mesh_link_params, mesh_link_specs_for_hub
from .network_config import uci_block
from .tunnel_model import (
    exit_reverse_firewall_rule_name,
    router_exit_listen_port,
)
from .uci import parse_uci_block, split_uci_blocks


def build_zone(
    name: str,
    ifaces: list[str],
    *,
    forward: str,
    masq: bool = False,
    mtu_fix: bool = False,
    input_policy: str = FIREWALL_TARGET_REJECT,
    output_policy: str = FIREWALL_TARGET_ACCEPT,
) -> str:
    options = {
        "name": name,
        "input": input_policy,
        "output": output_policy,
        "forward": forward,
    }
    if masq:
        options["masq"] = "1"
    if masq or mtu_fix:
        options["mtu_fix"] = "1"
    return uci_block("zone", None, options=options, lists={"network": ifaces})


def build_rule_allow_port_wan(name: str, port: int, proto: str) -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": name,
            "src": FIREWALL_ZONE_WAN,
            "dest_port": str(port),
            "target": FIREWALL_TARGET_ACCEPT,
            "proto": proto,
        },
    )


def build_rule_allow_overlay_src_ip(
    name: str,
    src_zone: str,
    src_ip: str,
    dest_zone: str | None,
) -> str:
    options = {
        "name": name,
        "src": src_zone,
        "target": FIREWALL_TARGET_ACCEPT,
        "family": "ipv4",
        "proto": "all",
    }
    if dest_zone is not None:
        options["dest"] = dest_zone

    return uci_block(
        "rule",
        None,
        options=options,
        lists={"src_ip": [src_ip]},
    )


def build_rule_allow_dns_transit_access() -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": TRANSIT_ACCESS_DNS_RULE_NAME,
            "src": ZONE_TRANSIT_ACCESS,
            "dest_port": str(DNS_PORT),
            "target": FIREWALL_TARGET_ACCEPT,
        },
        lists={"proto": DNS_PROTOCOLS},
    )


def build_common_firewall_blocks(
    present_zones: set[str] | None = None,
    *,
    initial_mode: str = "AUTO",
) -> list[str]:
    if present_zones is None:
        present_zones = {
            FIREWALL_ZONE_LAN,
            FIREWALL_ZONE_WAN,
            ZONE_MESH,
            ZONE_EXIT,
            ZONE_EXIT_IPIP,
            ZONE_TRUSTED_ACCESS,
            ZONE_TRANSIT_ACCESS,
        }
    blocks: list[str] = []
    for zone in (ZONE_MESH, ZONE_EXIT):
        if zone not in present_zones:
            continue
        for port, proto, label in (
            (6696, ["udp"], "Babel"),
            (5201, ["tcp", "udp"], "Iperf"),
        ):
            options = {
                "name": f"Allow-{label}-{zone}",
                "src": zone,
                "dest_port": str(port),
                "target": FIREWALL_TARGET_ACCEPT,
            }
            if len(proto) == 1:
                options["proto"] = proto[0]
            blocks.append(
                uci_block(
                    "rule",
                    None,
                    options=options,
                    lists={"proto": proto} if len(proto) > 1 else None,
                ).strip()
            )

    for zone, name in (
        (FIREWALL_ZONE_LAN, "Exitlan"),
        (ZONE_TRUSTED_ACCESS, "ExitTrustedAccess"),
        (ZONE_TRANSIT_ACCESS, "ExitTransitAccess"),
    ):
        if zone not in present_zones:
            continue
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": name,
                    "src": zone,
                    "dest": "*",
                    **(
                        {"ipset": "!direct"}
                        if initial_mode not in {"EXIT_FAIL_OPEN", "EXIT_FAIL_CLOSED"}
                        else {}
                    ),
                    **({"enabled": "0"} if initial_mode == "DIRECT" else {}),
                    "mark": "0",
                    "target": "MARK",
                    "set_mark": str(EXIT_POLICY_BASE),
                    "family": "ipv4",
                },
                lists={"proto": ["all"]},
            ).strip()
        )

    blocks.append(
        uci_block(
            "ipset",
            None,
            options={
                "name": "main",
                "family": "ipv4",
                "loadfile": f"{RUNTIME_IPSETS_DIR}/{RUNTIME_DIRECT_STATIC_NAME}",
                "timeout": "0",
                "counters": "0",
            },
            lists={"match": ["dest_net"]},
        ).strip()
    )

    blocks.append(
        uci_block(
            "ipset",
            None,
            options={
                "name": "direct",
                "family": "ipv4",
                "loadfile": f"{RUNTIME_IPSETS_DIR}/{RUNTIME_DIRECT_OUT_NAME}",
                "timeout": "0",
                "counters": "0",
            },
            lists={"match": ["dest_net"]},
        ).strip()
    )

    for zone, name in (
        (FIREWALL_ZONE_LAN, "ExitRouteDirectDropLan"),
        (ZONE_TRUSTED_ACCESS, "ExitRouteDirectDropTrustedAccess"),
        (ZONE_TRANSIT_ACCESS, "ExitRouteDirectDropTransitAccess"),
    ):
        if zone not in present_zones:
            continue
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": name,
                    "src": zone,
                    "dest": "*",
                    "mark": str(EXIT_POLICY_BASE),
                    "ipset": "direct",
                    "target": "DROP",
                    "family": "ipv4",
                    "proto": "all",
                    **(
                        {"enabled": "0"}
                        if initial_mode not in {"EXIT_FAIL_OPEN", "EXIT_FAIL_CLOSED"}
                        else {}
                    ),
                },
            ).strip()
        )

    # Fixed strict policies without a Babel route must not fall back to WAN.
    # The global mark is assigned in prerouting; individual DIRECT/SPLIT
    # overrides use a different mark and are not affected by this DROP.
    for zone, name in (
        (FIREWALL_ZONE_LAN, "ExitRouteUnavailableLan"),
        (ZONE_TRUSTED_ACCESS, "ExitRouteUnavailableTrustedAccess"),
        (ZONE_TRANSIT_ACCESS, "ExitRouteUnavailableTransitAccess"),
    ):
        if zone not in present_zones:
            continue
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": name,
                    "src": zone,
                    "dest": "*",
                    "mark": str(EXIT_POLICY_BASE),
                    "ipset": "!main",
                    "target": "DROP",
                    "family": "ipv4",
                    "proto": "all",
                    "enabled": "0",
                },
            ).strip()
        )

    # Reject a strict-policy packet if a missing IPIP route resolves to WAN.
    # The main and direct exceptions are marked 9999 and do not match.
    for zone, name in (
        (FIREWALL_ZONE_LAN, "ExitRouteWanGuardLan"),
        (ZONE_TRUSTED_ACCESS, "ExitRouteWanGuardTrustedAccess"),
        (ZONE_TRANSIT_ACCESS, "ExitRouteWanGuardTransitAccess"),
    ):
        if zone not in present_zones:
            continue
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": name,
                    "src": zone,
                    "dest": FIREWALL_ZONE_WAN,
                    "mark": str(EXIT_POLICY_BASE),
                    "target": "DROP",
                    "family": "ipv4",
                    "proto": "all",
                    **(
                        {}
                        if initial_mode in {"SPLIT_FAIL_CLOSED", "EXIT_FAIL_CLOSED"}
                        else {"enabled": "0"}
                    ),
                },
            ).strip()
        )

    for src, destinations in (
        (FIREWALL_ZONE_LAN, (ZONE_EXIT_IPIP, ZONE_EXIT, ZONE_MESH)),
        (ZONE_MESH, (ZONE_EXIT,)),
        (ZONE_EXIT, (ZONE_MESH,)),
        (
            ZONE_TRUSTED_ACCESS,
            (
                FIREWALL_ZONE_LAN,
                ZONE_MESH,
                ZONE_EXIT,
                ZONE_EXIT_IPIP,
                FIREWALL_ZONE_WAN,
            ),
        ),
        (
            ZONE_TRANSIT_ACCESS,
            (ZONE_MESH, ZONE_EXIT, ZONE_EXIT_IPIP, FIREWALL_ZONE_WAN),
        ),
    ):
        if src not in present_zones:
            continue
        for dest in destinations:
            if dest not in present_zones:
                continue
            blocks.append(
                uci_block("forwarding", None, options={"src": src, "dest": dest})
            )

    return blocks


def build_initial_device_firewall_blocks(
    cfg: ConfigData, router_name: str
) -> list[str]:
    effective = build_exit_route_config(cfg, router_name)
    sections = [parse_uci_block(block) for block in split_uci_blocks(effective)]
    policy_ids = routing_exit_policy_ids(cfg)
    blocks: list[str] = []

    def add_mark_rule(ip: str, suffix: str, mark: str, ipset: str = "") -> None:
        section = "exit_route_dev_" + ip.replace(".", "_") + "_" + suffix
        options = {
            "name": f"ExitRoute-{section}",
            "src": FIREWALL_ZONE_LAN,
            "src_ip": ip,
            "dest": "*",
            "target": "MARK",
            "family": "ipv4",
            "proto": "all",
            "set_mark": mark,
        }
        if ipset:
            options["ipset"] = ipset
        blocks.append(uci_block("rule", None, options=options).strip())

    def add_drop_rule(ip: str, mark: str) -> None:
        section = "exit_route_dev_" + ip.replace(".", "_") + "_drop"
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": f"ExitRoute-{section}",
                    "src": FIREWALL_ZONE_LAN,
                    "src_ip": ip,
                    "dest": "*",
                    "target": "DROP",
                    "mark": mark,
                    "ipset": "direct",
                    "family": "ipv4",
                    "proto": "all",
                },
            ).strip()
        )

    def add_block_rule(ip: str, mark: str | None = None) -> None:
        section = "exit_route_dev_" + ip.replace(".", "_") + "_block"
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": f"ExitRoute-{section}",
                    "src": FIREWALL_ZONE_LAN,
                    "src_ip": ip,
                    "dest": "*",
                    "target": "DROP",
                    "ipset": "!main",
                    "family": "ipv4",
                    "proto": "all",
                    **({"mark": mark} if mark else {}),
                },
            ).strip()
        )

    def add_wan_guard(ip: str, mark: str) -> None:
        section = "exit_route_dev_" + ip.replace(".", "_") + "_guard"
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": f"ExitRoute-{section}",
                    "src": FIREWALL_ZONE_LAN,
                    "src_ip": ip,
                    "dest": FIREWALL_ZONE_WAN,
                    "target": "DROP",
                    "mark": mark,
                    "family": "ipv4",
                    "proto": "all",
                },
            ).strip()
        )

    for section in sections:
        if section.get("type") != "device":
            continue
        options = section["options"]
        if options.get("disabled") == "1":
            continue
        ip = options["ip"]
        mode = options["mode"]
        exit_name = options.get("exit", "")
        if mode == "DIRECT":
            add_mark_rule(ip, "exit", ROUTING_WAN_MARK_TEXT)
        elif (
            mode
            in {
                "SPLIT_FAIL_OPEN",
                "SPLIT_FAIL_CLOSED",
                "EXIT_FAIL_OPEN",
                "EXIT_FAIL_CLOSED",
            }
            and exit_name in policy_ids
        ):
            if mode in {"SPLIT_FAIL_OPEN", "SPLIT_FAIL_CLOSED"}:
                add_mark_rule(ip, "direct", ROUTING_WAN_MARK_TEXT, "direct")
            add_mark_rule(
                ip,
                "exit",
                str(policy_ids[exit_name]),
                "!direct" if mode in {"SPLIT_FAIL_OPEN", "SPLIT_FAIL_CLOSED"} else "",
            )
            if mode in {"EXIT_FAIL_OPEN", "EXIT_FAIL_CLOSED"}:
                add_drop_rule(ip, str(policy_ids[exit_name]))
            if mode in {"SPLIT_FAIL_CLOSED", "EXIT_FAIL_CLOSED"}:
                # Initial state is fail-closed until Babel reachability is known.
                add_block_rule(
                    ip,
                    str(policy_ids[exit_name]) if mode == "SPLIT_FAIL_CLOSED" else None,
                )
                add_wan_guard(ip, str(policy_ids[exit_name]))
    return blocks


def build_firewall_blocks(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
    exit_ipip_ifaces: list[str],
    access_groups_for_router: list[AccessGroup],
) -> list[str]:
    blocks: list[str] = []

    if mesh_ifaces:
        blocks.append(
            build_zone(
                ZONE_MESH,
                mesh_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ifaces:
        blocks.append(
            build_zone(
                ZONE_EXIT,
                exit_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if exit_ipip_ifaces:
        blocks.append(
            build_zone(
                ZONE_EXIT_IPIP,
                exit_ipip_ifaces,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    trusted_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRUSTED}
    )
    transit_access_ifaces = sorted(
        {g.name for g in access_groups_for_router if g.policy == ACCESS_POLICY_TRANSIT}
    )

    if trusted_access_ifaces:
        blocks.append(
            build_zone(
                ZONE_TRUSTED_ACCESS,
                trusted_access_ifaces,
                input_policy=FIREWALL_TARGET_ACCEPT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )

    if transit_access_ifaces:
        blocks.append(
            build_zone(
                ZONE_TRANSIT_ACCESS,
                transit_access_ifaces,
                input_policy=FIREWALL_TARGET_REJECT,
                output_policy=FIREWALL_TARGET_ACCEPT,
                forward=FIREWALL_TARGET_ACCEPT,
                mtu_fix=True,
            ).strip()
        )
        blocks.append(build_rule_allow_dns_transit_access().strip())

    if router_name in cfg.mesh_hubs_by_name:
        hub = cfg.mesh_hubs_by_name[router_name]

        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            link = compute_mesh_link_params(cfg, hub, target_name)
            blocks.append(
                build_rule_allow_port_wan(
                    mesh_firewall_rule_name(hub.name, target_name),
                    link.port,
                    TRANSPORT_UDP,
                ).strip()
            )

        for exit_hub in cfg.exit_hubs:
            blocks.append(
                build_rule_allow_port_wan(
                    exit_reverse_firewall_rule_name(exit_hub.name),
                    router_exit_listen_port(cfg, exit_hub, router_name),
                    TRANSPORT_UDP,
                ).strip()
            )

    for group in access_groups_for_router:
        proto = TRANSPORT_TCP if group.protocol == PROTOCOL_OPENVPN else TRANSPORT_UDP
        blocks.append(
            build_rule_allow_port_wan(f"Allow-{group.name}", group.port, proto).strip()
        )

    overlay_src_zones: list[str] = []
    if mesh_ifaces:
        overlay_src_zones.append(ZONE_MESH)
    if exit_ifaces:
        overlay_src_zones.append(ZONE_EXIT)

    for allow in cfg.firewall_allows:
        targets = expand_firewall_targets(cfg, allow)
        if router_name not in targets:
            continue

        for src_zone in overlay_src_zones:
            blocks.append(
                build_rule_allow_overlay_src_ip(
                    firewall_allow_rule_name(
                        allow.source_name, router_name, allow.kind, src_zone
                    ),
                    src_zone,
                    allow.source_subnet,
                    (
                        FIREWALL_ZONE_LAN
                        if allow.kind == FIREWALL_ALLOW_KIND_LAN
                        else None
                    ),
                ).strip()
            )

    present_zones = {FIREWALL_ZONE_LAN, FIREWALL_ZONE_WAN}
    if mesh_ifaces:
        present_zones.add(ZONE_MESH)
    if exit_ifaces:
        present_zones.add(ZONE_EXIT)
    if exit_ipip_ifaces:
        present_zones.add(ZONE_EXIT_IPIP)
    if trusted_access_ifaces:
        present_zones.add(ZONE_TRUSTED_ACCESS)
    if transit_access_ifaces:
        present_zones.add(ZONE_TRANSIT_ACCESS)

    initial_mode = cfg.exit_routes_by_router[router_name].mode
    blocks.extend(
        build_common_firewall_blocks(
            present_zones,
            initial_mode=initial_mode,
        )
    )
    blocks.extend(build_initial_device_firewall_blocks(cfg, router_name))

    # A final main MARK overrides both global and per-device policy marks.
    # It is deliberately last, and runtime maintains this ordering.
    for zone, name in (
        (FIREWALL_ZONE_LAN, "ExitRouteMainLan"),
        (ZONE_TRUSTED_ACCESS, "ExitRouteMainTrustedAccess"),
        (ZONE_TRANSIT_ACCESS, "ExitRouteMainTransitAccess"),
    ):
        if zone not in present_zones:
            continue
        blocks.append(
            uci_block(
                "rule",
                None,
                options={
                    "name": name,
                    "src": zone,
                    "dest": "*",
                    "ipset": "main",
                    "target": "MARK",
                    "set_mark": ROUTING_WAN_MARK_TEXT,
                    "family": "ipv4",
                    "proto": "all",
                },
            ).strip()
        )

    return blocks


def update_firewall_part(
    cfg: ConfigData,
    router_name: str,
    mesh_ifaces: list[str],
    exit_ifaces: list[str],
    exit_ipip_ifaces: list[str],
    access_groups_for_router: list[AccessGroup],
) -> None:
    # This file is entirely generated; the example template is not consulted.
    blocks = build_firewall_blocks(
        cfg,
        router_name,
        mesh_ifaces,
        exit_ifaces,
        exit_ipip_ifaces,
        access_groups_for_router,
    )
    write(router_path(cfg, router_name, "firewall"), "\n" + "\n\n".join(blocks) + "\n")
