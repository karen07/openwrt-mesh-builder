#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .validate_context import vprint
    from .tunnel_model import (
        exit_hub_is_public,
        router_exit_listen_port,
        router_is_public_mesh_hub,
    )
except ImportError:
    from common import *  # type: ignore
    from validate_context import vprint  # type: ignore
    from tunnel_model import (  # type: ignore
        exit_hub_is_public,
        router_exit_listen_port,
        router_is_public_mesh_hub,
    )


def add_port(used: dict[int, str], port: int, desc: str, scope: str) -> None:
    if port in used:
        die(f"{scope}: local port collision on {port}: {used[port]} vs {desc}")
    used[port] = desc


def expected_router_uci_listeners(cfg: ConfigData, router_name: str) -> dict[str, int]:
    expected: dict[str, int] = {}

    if router_name in cfg.mesh_hubs_by_name:
        hub = cfg.mesh_hubs_by_name[router_name]
        for _hub_name, target_router in mesh_link_specs_for_hub(cfg, router_name):
            iface = mesh_server_iface_name_for_target(target_router)
            expected[iface] = compute_mesh_link_params(cfg, hub, target_router).port

    if router_is_public_mesh_hub(cfg, router_name):
        for hub in cfg.exit_hubs:
            expected[exit_in_iface_name(hub.name)] = router_exit_listen_port(
                cfg, hub, router_name
            )

    for group in cfg.access.get(router_name, []):
        if group.protocol in {PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG}:
            expected[group.name] = group.port

    return expected


def expected_router_host_ports(cfg: ConfigData, router_name: str) -> dict[str, int]:
    expected = dict(expected_router_uci_listeners(cfg, router_name))

    for group in cfg.access.get(router_name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            expected[group.name] = group.port

    return expected


def openvpn_server_port_if_present(
    cfg: ConfigData,
    router_name: str,
    group: AccessGroup,
) -> int | None:
    path = router_openvpn_server_conf_path(cfg, router_name, group.name)
    if not path.exists():
        return None

    for line in read(path).splitlines():
        m = re.fullmatch(r"\s*port\s+(\d+)\s*", line)
        if not m:
            continue
        return int(m.group(1))

    return None


def validate_router_local_ports(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for router_name in cfg.router_names:
        parsed = existing[router_name]
        expected_uci = expected_router_uci_listeners(cfg, router_name)
        expected_host = expected_router_host_ports(cfg, router_name)
        expected_used: dict[int, str] = {}
        actual_used: dict[int, str] = {}

        for name, port in expected_host.items():
            add_port(
                expected_used,
                port,
                f"expected listener:{name}",
                f"router {router_name}",
            )

        for group in cfg.access.get(router_name, []):
            if group.protocol != PROTOCOL_OPENVPN:
                continue
            port = openvpn_server_port_if_present(cfg, router_name, group)
            if port is not None:
                add_port(
                    actual_used,
                    port,
                    f"actual openvpn:{group.name}",
                    f"router {router_name}",
                )

        for block in parsed.values():
            if block.get("type") != "interface":
                continue

            iface = str(block.get("name", ""))
            opts = block.get("options", {})
            lp = opts.get("listen_port")
            if not lp:
                continue

            try:
                port = int(str(lp))
            except ValueError:
                die(f"router {router_name}: bad listen_port on {iface}: {lp!r}")
            if port < PORT_MIN or port > PORT_MAX:
                die(
                    f"router {router_name}: listen_port out of range on {iface}: {port}"
                )

            add_port(
                actual_used, port, f"actual iface:{iface}", f"router {router_name}"
            )

            if iface in expected_uci and expected_uci[iface] != port:
                die(
                    f"router {router_name}: bad listen_port on {iface}: "
                    f"expected {expected_uci[iface]}, got {port}"
                )

        actual_uci_listeners = {
            str(block.get("name", ""))
            for block in parsed.values()
            if block.get("type") == "interface"
            and block.get("options", {}).get("listen_port")
        }
        missing = sorted(set(expected_uci) - actual_uci_listeners)
        if missing:
            die(
                f"router {router_name}: missing expected UCI listeners: {', '.join(missing)}"
            )

        vprint(
            f"[PORTS] router={router_name} ok ({len(actual_used)} unique local ports)"
        )


def validate_exit_server_local_ports(cfg: ConfigData) -> None:
    for hub in cfg.exit_hubs:
        used: dict[int, str] = {}

        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                client_alias = build_exit_client_alias(cfg, hub.name, router_name)
                link = compute_exit_link_params(cfg, hub, router_name)
                add_port(
                    used,
                    link.port,
                    f"wg-server:{client_alias}",
                    f"exit hub server {hub.name}",
                )

        for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
            other = cfg.exit_hubs_by_name[peer_name]
            alias = build_exit_exit_alias(cfg, hub.name, other.name)
            link = compute_exit_exit_link_params(cfg, hub, other)
            port = link.left_port if hub.name == link.left_name else link.right_port
            add_port(
                used,
                port,
                f"exit-exit:{alias}:{other.name}",
                f"exit hub server {hub.name}",
            )

        vprint(f"[PORTS] exit-server={hub.name} ok ({len(used)} unique local ports)")
