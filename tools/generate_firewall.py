#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .managed_blocks import (
        generated_uci_management_keys,
        render_marked_uci_text,
        uci_management_key,
    )
    from .uci import parse_uci_block, split_uci_blocks
    from .tunnel_model import (
        exit_reverse_firewall_rule_name,
        router_exit_listen_port,
    )
except ImportError:
    from common import *  # type: ignore
    from managed_blocks import (  # type: ignore
        generated_uci_management_keys,
        render_marked_uci_text,
        uci_management_key,
    )
    from uci import parse_uci_block, split_uci_blocks  # type: ignore
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


def routing_firewall_rule_name(rule: RoutingRule) -> str:
    src = rule.src_ip.split("/", 1)[0].replace(".", "_")
    if rule.mode == ROUTING_MODE_WAN:
        return f"{ROUTING_FIREWALL_RULE_PREFIX}WAN-{src}"
    assert rule.exit_name is not None
    mode = rule.mode.capitalize()
    return f"{ROUTING_FIREWALL_RULE_PREFIX}{mode}-{rule.exit_name}-{src}"


def build_routing_firewall_blocks(cfg: ConfigData, router_name: str) -> list[str]:
    policy_ids = routing_exit_policy_ids(cfg)
    blocks: list[str] = []

    for rule in cfg.routing_rules_by_router.get(router_name, []):
        src_ip = rule.src_ip.split("/", 1)[0]
        options = {
            "name": routing_firewall_rule_name(rule),
            "src": FIREWALL_ZONE_LAN,
            "src_ip": src_ip,
            "dest": "*",
            "target": "MARK",
            "family": "ipv4",
        }

        if rule.mode == ROUTING_MODE_WAN:
            options["set_mark"] = ROUTING_WAN_MARK_TEXT
        else:
            assert rule.exit_name is not None
            options["set_mark"] = str(policy_ids[rule.exit_name])
            if rule.mode == ROUTING_MODE_SPLIT:
                options["ipset"] = "!direct"

        blocks.append(
            uci_block(
                "rule",
                None,
                options=options,
                lists={"proto": ["all"]},
            ).strip()
        )

    return blocks


def validate_firewall_shared_tail(marker_and_tail: str, path: Path) -> None:
    for block in split_uci_blocks(marker_and_tail):
        parsed = parse_uci_block(block)
        if parsed.get("type") != "rule":
            continue

        name = str(parsed.get("options", {}).get("name", ""))
        if name.startswith(ROUTING_FIREWALL_RULE_PREFIX):
            die(
                f"router-specific firewall rule {name!r} found after "
                f"{FIREWALL_MARKER!r} in {path}; the shared tail is owned "
                "by routers/example"
            )


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

    blocks.extend(build_routing_firewall_blocks(cfg, router_name))

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
    validate_firewall_shared_tail(marker_and_tail, path)
    blocks = build_firewall_blocks(
        cfg=cfg,
        router_name=router_name,
        mesh_ifaces=mesh_ifaces,
        exit_ifaces=exit_ifaces,
        exit_ipip_ifaces=exit_ipip_ifaces,
        access_groups_for_router=access_groups_for_router,
    )
    managed_keys = generated_uci_management_keys(blocks)

    # Migration: allow rules used to omit the ingress suffix for Mesh, e.g.
    # Allow-Devices-To-Anna-Router.  Since generated UCI ownership is keyed by
    # option name, a plain rename would otherwise preserve that old generated
    # section as unmanaged.  Remove only legacy names that correspond to an
    # allow which is still present in the current config for this target.
    legacy_allow_names: set[str] = set()
    for allow in cfg.firewall_allows:
        if router_name not in expand_firewall_targets(cfg, allow):
            continue
        legacy_allow_names.add(
            legacy_firewall_allow_rule_name(allow.source_name, router_name, allow.kind)
        )

    def keep_block(parsed: dict[str, object]) -> bool:
        options = parsed.get("options", {})
        if (
            parsed.get("type") == "rule"
            and isinstance(options, dict)
            and str(options.get("name", "")) in legacy_allow_names
        ):
            return False
        return uci_management_key(parsed) not in managed_keys

    preserved_before = filter_preserved_before_marker(before_marker, keep_block)

    # Render only the router-specific part.  The marker and everything after
    # it are owned by routers/example and sync_rules.py, so append that text
    # exactly as it was read instead of passing it through a UCI renderer.
    rendered_before = render_marked_uci_text(
        blocks,
        preserved_before,
        "",
        leading_newline=True,
        normalize_result=False,
    )
    if rendered_before:
        updated = rendered_before.rstrip("\n") + "\n\n" + marker_and_tail
    else:
        updated = marker_and_tail

    _updated_before, updated_tail = split_text_by_marker(updated, path)
    if updated_tail != marker_and_tail:
        die(f"internal error: shared firewall tail changed for {path}")

    write(path, updated)
