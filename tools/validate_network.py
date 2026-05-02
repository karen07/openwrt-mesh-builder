#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import ipaddress

try:
    from .common import *
    from .tunnel_model import exit_hub_is_public, router_is_public_mesh_hub
    from .validate_context import vprint
except ImportError:
    from common import *  # type: ignore
    from tunnel_model import exit_hub_is_public, router_is_public_mesh_hub  # type: ignore
    from validate_context import vprint  # type: ignore


def validate_link_is_31_pair(server_ip: str, client_ip: str, where: str) -> None:
    try:
        server = ipaddress.IPv4Interface(server_ip)
        client = ipaddress.IPv4Interface(client_ip)
    except ValueError as e:
        die(f"{where}: bad IPv4 link address: {e}")

    if (
        server.network.prefixlen != P2P_LINK_PREFIXLEN
        or client.network.prefixlen != P2P_LINK_PREFIXLEN
    ):
        die(
            f"{where}: link addresses must both be /{P2P_LINK_PREFIXLEN}: "
            f"{server_ip} {client_ip}"
        )

    if server.network != client.network:
        die(
            f"{where}: link addresses are not in the same /{P2P_LINK_PREFIXLEN}: "
            f"{server_ip} {client_ip}"
        )

    if int(server.ip) != int(server.network.network_address):
        die(f"{where}: server address must be the first address in {server.network}")
    if int(client.ip) != int(server.ip) + 1:
        die(
            f"{where}: addresses do not form the expected /31 pair: "
            f"{server_ip} {client_ip}"
        )


def expected_mesh_exit_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return current_mesh_exit_ifaces(cfg, router_name)


def expected_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {group.name for group in cfg.access.get(router_name, [])}


def expected_wireguard_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {
        group.name
        for group in cfg.access.get(router_name, [])
        if group.protocol == PROTOCOL_WIREGUARD
    }


def expected_amneziawg_access_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return {
        group.name
        for group in cfg.access.get(router_name, [])
        if group.protocol == PROTOCOL_AMNEZIAWG
    }


def expected_babel_tunnel_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = mesh_iface_names_for_router(cfg, router_name)

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            names.add(exit_out_iface_name(hub.name))
        if router_is_public_mesh_hub(cfg, router_name):
            names.add(exit_in_iface_name(hub.name))

    return names


def expected_tunnel_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    # Babel should run only on the real AWG/WG mesh+exit links.
    # Router-side IPIP interfaces are data-path egress tunnels to exits,
    # not Babel neighbour links.
    return expected_babel_tunnel_ifaces(cfg, router_name)


def expected_managed_ifaces(cfg: ConfigData, router_name: str) -> set[str]:
    return expected_mesh_exit_ifaces(cfg, router_name) | expected_access_ifaces(
        cfg, router_name
    )


def validate_current_network_objects(
    cfg: ConfigData, existing: dict[str, dict[str, dict[str, object]]]
) -> None:
    for router_name in cfg.router_names:
        expected_ifaces = expected_managed_ifaces(cfg, router_name)
        parsed = existing[router_name]

        for block in parsed.values():
            typ = str(block.get("type", ""))
            name = str(block.get("name", ""))
            opts = block.get("options", {})

            if typ == "interface":
                proto = str(opts.get("proto", ""))
                if (
                    proto in {PROTOCOL_AMNEZIAWG, PROTOCOL_WIREGUARD}
                    and name not in expected_ifaces
                ):
                    die(
                        f"router {router_name}: "
                        f"unexpected managed tunnel interface {name}"
                    )
                continue

            if typ.startswith("amneziawg_"):
                iface = typ.removeprefix("amneziawg_")
                expected = expected_mesh_exit_ifaces(
                    cfg, router_name
                ) | expected_amneziawg_access_ifaces(cfg, router_name)
                if iface not in expected:
                    die(
                        f"router {router_name}: "
                        f"unexpected AmneziaWG peer section {typ}"
                    )

            if typ.startswith("wireguard_"):
                iface = typ.removeprefix("wireguard_")
                if iface not in expected_wireguard_access_ifaces(cfg, router_name):
                    die(
                        f"router {router_name}: "
                        f"unexpected WireGuard peer section {typ}"
                    )


def network4(value: str, where: str) -> ipaddress.IPv4Network:
    try:
        return ipaddress.ip_network(value, strict=False)
    except ValueError as e:
        die(f"{where}: invalid IPv4 network {value!r}: {e}")


def validate_subnet_isolation(cfg: ConfigData) -> None:
    nets: list[tuple[str, ipaddress.IPv4Network]] = []

    for router in cfg.routers:
        nets.append(
            (f"LAN {router.name}", network4(router.lan_ipaddr, f"LAN {router.name}"))
        )

    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        nets.append(
            (
                f"mesh {hub.name}->{target_name}",
                network4(link.srv_ip4, f"mesh {hub.name}->{target_name}"),
            )
        )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                nets.append(
                    (
                        f"exit {hub.name}->{router_name}",
                        network4(link.srv_ip4, f"exit {hub.name}->{router_name}"),
                    )
                )

    for hub in cfg.exit_hubs:
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            label = f"exit-reverse {hub.name}->{mesh_hub.name}"
            nets.append((label, network4(link.srv_ip4, label)))

    for hub in cfg.exit_hubs:
        nets.append((f"exit-node {hub.name}", exit_node_network(hub)))

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        nets.append(
            (
                f"exit-exit {left_hub.name}<->{right_hub.name}",
                network4(
                    link.left_ip4, f"exit-exit {left_hub.name}<->{right_hub.name}"
                ),
            )
        )

    for router_name, groups in cfg.access.items():
        for group in groups:
            nets.append(
                (
                    f"access {router_name}/{group.name}",
                    network4(
                        f"{group.subnet}.0/{ACCESS_SUBNET_CIDR}",
                        f"access {router_name}/{group.name}",
                    ),
                )
            )

    for i, (left_name, left_net) in enumerate(nets):
        for right_name, right_net in nets[i + 1 :]:
            if left_net.overlaps(right_net):
                die(
                    f"subnet overlap: {left_name} {left_net} vs {right_name} {right_net}"
                )

    vprint(f"[SUBNETS] ok ({len(nets)} networks)")


def validate_link_local_matches_ipv4(cfg: ConfigData) -> None:
    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
            die(f"mesh {hub.name}->{target_name}: bad server link-local")
        if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
            die(f"mesh {hub.name}->{target_name}: bad client link-local")

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
                    die(f"exit {hub.name}->{router_name}: bad server link-local")
                if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
                    die(f"exit {hub.name}->{router_name}: bad client link-local")
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            if link.srv_ll != ipv4_to_link_local(link.srv_ip4):
                die(f"exit-reverse {hub.name}->{mesh_hub.name}: bad server link-local")
            if link.cli_ll != ipv4_to_link_local(link.cli_ip4):
                die(f"exit-reverse {hub.name}->{mesh_hub.name}: bad client link-local")

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        if link.left_ll != ipv4_to_link_local(link.left_ip4):
            die(f"exit-exit {left_hub.name}<->{right_hub.name}: bad left link-local")
        if link.right_ll != ipv4_to_link_local(link.right_ip4):
            die(f"exit-exit {left_hub.name}<->{right_hub.name}: bad right link-local")


def validate_unique_tunnel_addresses(cfg: ConfigData) -> None:
    used: dict[str, str] = {}

    def add_addr(addr: str, where: str) -> None:
        ip = ipv4_without_prefix(addr)
        if ip in used:
            die(f"duplicate tunnel address {ip}: {used[ip]} vs {where}")
        used[ip] = where

    def add_pair(server_ip: str, client_ip: str, where: str) -> None:
        validate_link_is_31_pair(server_ip, client_ip, where)
        add_addr(server_ip, f"{where} server")
        add_addr(client_ip, f"{where} client")

    for hub_name, target_name in mesh_link_specs(cfg):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        add_pair(link.srv_ip4, link.cli_ip4, f"mesh {hub.name}->{target_name}")

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            for router_name in cfg.router_names:
                link = compute_exit_link_params(cfg, hub, router_name)
                add_pair(link.srv_ip4, link.cli_ip4, f"exit {hub.name}->{router_name}")
        for mesh_hub in cfg.mesh_hubs:
            link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
            add_pair(
                link.srv_ip4,
                link.cli_ip4,
                f"exit-reverse {hub.name}->{mesh_hub.name}",
            )

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_hub = cfg.exit_hubs_by_name[left_name]
        right_hub = cfg.exit_hubs_by_name[right_name]
        link = compute_exit_exit_link_params(cfg, left_hub, right_hub)
        add_pair(
            link.left_ip4,
            link.right_ip4,
            f"exit-exit {left_hub.name}<->{right_hub.name}",
        )

    vprint(f"[ADDR] tunnel IPv4 ok ({len(used)} addresses)")
