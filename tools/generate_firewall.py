#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .managed_blocks import render_marked_uci_text
    from .tunnel_model import (
        exit_reverse_firewall_rule_name,
        router_exit_listen_port,
    )
except ImportError:
    from common import *  # type: ignore
    from managed_blocks import render_marked_uci_text  # type: ignore
    from tunnel_model import (  # type: ignore
        exit_reverse_firewall_rule_name,
        router_exit_listen_port,
    )


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


def build_rule_allow_mesh_src_ip(
    name: str,
    src_ip: str,
    dest_zone: str | None,
) -> str:
    options = {
        "name": name,
        "src": ZONE_MESH,
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


def build_rule_allow_ssh_from_exit_to_router() -> str:
    return uci_block(
        "rule",
        None,
        options={
            "name": "Allow-SSH-From-Exit-To-Router",
            "src": ZONE_EXIT,
            "proto": TRANSPORT_TCP,
            "dest_port": "22",
            "target": FIREWALL_TARGET_ACCEPT,
        },
    )


def managed_firewall_rule_names(
    cfg: ConfigData,
    router_name: str,
    access_groups_for_router: list[AccessGroup],
) -> set[str]:
    names: set[str] = {
        TRANSIT_ACCESS_DNS_RULE_NAME,
        "Allow-SSH-From-Exit-To-Router",
    }

    if router_name in cfg.mesh_hubs_by_name:
        names.add(FIREWALL_RULE_ALLOW_MESH)
        hub = cfg.mesh_hubs_by_name[router_name]
        for _hub_name, target_name in mesh_link_specs_for_hub(cfg, router_name):
            names.add(mesh_firewall_rule_name(hub.name, target_name))
        for exit_hub in cfg.exit_hubs:
            names.add(exit_reverse_firewall_rule_name(exit_hub.name))

    for group in access_groups_for_router:
        names.add(f"Allow-{group.name}")

    for allow in cfg.firewall_allows:
        for target_name in expand_firewall_targets(cfg, allow):
            if target_name == router_name:
                names.add(
                    firewall_allow_rule_name(allow.source_name, target_name, allow.kind)
                )

    return names


def managed_firewall_zone_names() -> set[str]:
    return set(MANAGED_FIREWALL_ZONES) | {ZONE_EXIT_IPIP}


def is_managed_firewall_block(
    parsed: dict[str, object],
    *,
    rule_names: set[str],
    zone_names: set[str],
) -> bool:
    typ = str(parsed.get("type", ""))
    options = parsed.get("options", {})

    if typ == "zone" and str(options.get("name", "")) in zone_names:
        return True

    if typ == "rule" and str(options.get("name", "")) in rule_names:
        return True

    return False


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

    if exit_ifaces and not config_has_allow_to_router_all(cfg):
        blocks.append(build_rule_allow_ssh_from_exit_to_router().strip())

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

    for allow in cfg.firewall_allows:
        targets = expand_firewall_targets(cfg, allow)
        if router_name not in targets:
            continue

        blocks.append(
            build_rule_allow_mesh_src_ip(
                firewall_allow_rule_name(allow.source_name, router_name, allow.kind),
                allow.source_subnet,
                FIREWALL_ZONE_LAN if allow.kind == FIREWALL_ALLOW_KIND_LAN else None,
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
    path = router_path(cfg, router_name, "firewall")
    original = read(path)

    before_marker, marker_and_tail = split_text_by_marker(original, path)
    rule_names = managed_firewall_rule_names(cfg, router_name, access_groups_for_router)
    zone_names = managed_firewall_zone_names()

    def keep_block(parsed: dict[str, object]) -> bool:
        return not is_managed_firewall_block(
            parsed,
            rule_names=rule_names,
            zone_names=zone_names,
        )

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)
    blocks = build_firewall_blocks(
        cfg=cfg,
        router_name=router_name,
        mesh_ifaces=mesh_ifaces,
        exit_ifaces=exit_ifaces,
        exit_ipip_ifaces=exit_ipip_ifaces,
        access_groups_for_router=access_groups_for_router,
    )

    # Keep the shared section after FIREWALL_MARKER byte-stable with
    # routers/example.  sync_rules.py owns that tail; normalizing the whole
    # file here makes sync_rules.py and generate.py rewrite firewall_part on
    # every run.  Keep the historical leading blank line too: existing
    # firewall_part files intentionally start with an empty first line, and
    # sync_rules.py preserves the generated part byte-for-byte.
    updated = render_marked_uci_text(
        blocks,
        preserved_before,
        marker_and_tail,
        leading_newline=True,
        normalize_result=False,
    )
    write(path, updated)
