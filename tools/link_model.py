#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import ipaddress

try:
    from .config_model import (
        ConfigData,
        ExitExitLinkParams,
        ExitHub,
        LinkParams,
        MeshHub,
    )
    from .default import (
        INFRA_LINK_POOL,
        P2P_LINK_HOST_STRIDE,
        P2P_LINK_PREFIXLEN,
    )
    from .net_model import ipv4_to_link_local
    from .process import die
    from .stable_model import (
        ring_link_pairs,
        stable_port_avoiding_for,
        stable_port_for,
        stable_unique_values,
        stable_unique_values_avoiding,
    )
except ImportError:
    from config_model import (  # type: ignore
        ConfigData,
        ExitExitLinkParams,
        ExitHub,
        LinkParams,
        MeshHub,
    )
    from default import (  # type: ignore
        INFRA_LINK_POOL,
        P2P_LINK_HOST_STRIDE,
        P2P_LINK_PREFIXLEN,
    )
    from net_model import ipv4_to_link_local  # type: ignore
    from process import die  # type: ignore
    from stable_model import (  # type: ignore
        ring_link_pairs,
        stable_port_avoiding_for,
        stable_port_for,
        stable_unique_values,
        stable_unique_values_avoiding,
    )


def _router_or_die(cfg: ConfigData, name: str) -> None:
    if name not in cfg.router_by_name:
        die(f"unknown router: {name}")


def mesh_link_key(hub_name: str, target_name: str) -> str:
    return f"mesh:{hub_name}:{target_name}"


def mesh_link_specs(cfg: ConfigData) -> list[tuple[str, str]]:
    # Topology policy:
    #   * every leaf/router connects to every public spine hub;
    #   * spine-to-spine core is a ring with one full-duplex tunnel per edge.
    spine_names = {hub.name for hub in cfg.mesh_hubs}
    spine_order = [hub.name for hub in cfg.mesh_hubs]
    specs: list[tuple[str, str]] = []

    for hub in cfg.mesh_hubs:
        for router_name in cfg.router_names:
            if router_name not in spine_names:
                specs.append((hub.name, router_name))

    # Spine ring is expressed as clockwise client/Out -> server/In sessions.
    # compute_mesh_link_params(hub, target) treats hub as listener/server-side
    # and target as client/initiator-side, so reverse each clockwise edge.
    specs.extend(
        (server_name, client_name)
        for client_name, server_name in ring_link_pairs(spine_order)
    )
    return specs


def mesh_link_specs_for_hub(cfg: ConfigData, hub_name: str) -> list[tuple[str, str]]:
    return [(hub, target) for hub, target in mesh_link_specs(cfg) if hub == hub_name]


def mesh_link_specs_for_router(
    cfg: ConfigData, router_name: str
) -> list[tuple[str, str]]:
    return [
        (hub, target)
        for hub, target in mesh_link_specs(cfg)
        if hub == router_name or target == router_name
    ]


def mesh_iface_names_for_router(cfg: ConfigData, router_name: str) -> set[str]:
    names: set[str] = set()
    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        if router_name == hub_name:
            names.add(mesh_server_iface_name_for_target(target_name))
        if router_name == target_name:
            names.add(client_iface_name_for_target(cfg, router_name, hub_name))
    return names


def exit_link_key(hub_name: str, router_name: str) -> str:
    return f"exit:{hub_name}:{router_name}"


def exit_reverse_link_key(hub_name: str, router_name: str) -> str:
    return f"exit-reverse:{hub_name}:{router_name}"


def exit_exit_pair_names(left_name: str, right_name: str) -> tuple[str, str]:
    if left_name == right_name:
        die(f"bad exit-exit pair: {left_name} == {right_name}")
    return left_name, right_name


def exit_exit_link_key(client_name: str, server_name: str) -> str:
    client, server = exit_exit_pair_names(client_name, server_name)
    return f"exit-exit:{client}:{server}"


def mesh_link_keys(cfg: ConfigData, hub: MeshHub) -> list[str]:
    return [
        mesh_link_key(hub_name, target_name)
        for hub_name, target_name in mesh_link_specs_for_hub(cfg, hub.name)
    ]


def exit_link_keys(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [exit_link_key(hub.name, name) for name in cfg.router_names]


def exit_reverse_link_keys(cfg: ConfigData) -> list[str]:
    return [
        exit_reverse_link_key(hub.name, mesh_hub.name)
        for hub in cfg.exit_hubs
        for mesh_hub in cfg.mesh_hubs
    ]


def public_exit_hub_names(cfg: ConfigData) -> list[str]:
    hubs_by_name = cfg.exit_hubs_by_name
    order = cfg.exit_order or [hub.name for hub in cfg.exit_hubs]
    return [name for name in order if hubs_by_name[name].listen_ip]


def exit_exit_link_pairs(cfg: ConfigData) -> list[tuple[str, str]]:
    # Exit-to-exit layer is a clockwise ring over public exits only.
    # A grey/NAT exit is skipped here; it still connects to every spine through
    # exit-in/reverse links, but it is not used as an exit-exit listener.
    #
    # Pair direction is part of the generated session semantics:
    #   client/Out -> server/In
    return ring_link_pairs(public_exit_hub_names(cfg))


def exit_exit_link_pair_for_hubs(
    cfg: ConfigData, left_name: str, right_name: str
) -> tuple[str, str]:
    for client_name, server_name in exit_exit_link_pairs(cfg):
        if (left_name, right_name) in (
            (client_name, server_name),
            (server_name, client_name),
        ):
            return client_name, server_name
    die(f"exit-exit link is not configured: {left_name}<->{right_name}")


def exit_exit_peer_names_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    peers: list[str] = []
    for client_name, server_name in exit_exit_link_pairs(cfg):
        if hub.name == client_name:
            peers.append(server_name)
        elif hub.name == server_name:
            peers.append(client_name)
    return sorted(peers)


def exit_exit_link_keys(cfg: ConfigData) -> list[str]:
    return [
        exit_exit_link_key(client_name, server_name)
        for client_name, server_name in exit_exit_link_pairs(cfg)
    ]


def exit_exit_link_keys_for_hub(cfg: ConfigData, hub: ExitHub) -> list[str]:
    return [
        exit_exit_link_key(*exit_exit_link_pair_for_hubs(cfg, hub.name, peer_name))
        for peer_name in exit_exit_peer_names_for_hub(cfg, hub)
    ]


def infra_link_keys(cfg: ConfigData) -> list[str]:
    # Mesh-mesh and router-exit link keys are kept unchanged so adding
    # exit-exit links does not move existing /31 allocations.
    keys: list[str] = []

    for hub in cfg.mesh_hubs:
        keys.extend(mesh_link_keys(cfg, hub))

    for hub in cfg.exit_hubs:
        keys.extend(exit_link_keys(cfg, hub))

    return sorted(keys)


def stable_infra_link_pair_indices(
    cfg: ConfigData,
) -> tuple[ipaddress.IPv4Network, int, dict[str, int]]:
    pool = ipaddress.IPv4Network(INFRA_LINK_POOL, strict=True)
    if pool.prefixlen > P2P_LINK_PREFIXLEN:
        die(f"infra link pool {pool} is too small for /{P2P_LINK_PREFIXLEN} links")

    pair_count = pool.num_addresses // P2P_LINK_HOST_STRIDE
    allocated = stable_unique_values(
        infra_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"infra link addresses in {pool}",
    )
    return pool, pair_count, allocated


def infra_link_network_from_pair_index(
    pool: ipaddress.IPv4Network,
    pair_index: int,
    where: str,
) -> ipaddress.IPv4Network:
    first_ip = int(pool.network_address) + pair_index * P2P_LINK_HOST_STRIDE
    network = ipaddress.IPv4Network((first_ip, P2P_LINK_PREFIXLEN), strict=True)
    if network.network_address not in pool or network.broadcast_address not in pool:
        die(f"{where}: generated link {network} is outside infra pool {pool}")
    return network


def stable_infra_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, _pair_count, allocated = stable_infra_link_pair_indices(cfg)
    return infra_link_network_from_pair_index(pool, allocated[key], where)


def stable_exit_exit_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, pair_count, existing_allocated = stable_infra_link_pair_indices(cfg)
    pair_index = stable_unique_values_avoiding(
        exit_exit_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-exit link addresses in {pool}",
        reserved=set(existing_allocated.values()),
    )[key]
    return infra_link_network_from_pair_index(pool, pair_index, where)


def stable_exit_reverse_link_network_for(
    cfg: ConfigData, key: str, where: str
) -> ipaddress.IPv4Network:
    pool, pair_count, existing_allocated = stable_infra_link_pair_indices(cfg)
    exit_exit_allocated = stable_unique_values_avoiding(
        exit_exit_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-exit link addresses in {pool}",
        reserved=set(existing_allocated.values()),
    )
    reserved = set(existing_allocated.values()) | set(exit_exit_allocated.values())
    pair_index = stable_unique_values_avoiding(
        exit_reverse_link_keys(cfg),
        start=0,
        end=pair_count - 1,
        purpose="infra-link",
        where=f"exit-reverse link addresses in {pool}",
        reserved=reserved,
    )[key]
    return infra_link_network_from_pair_index(pool, pair_index, where)


def link_network_addresses(network: ipaddress.IPv4Network) -> tuple[str, str]:
    addrs = list(network.hosts())
    if len(addrs) != P2P_LINK_HOST_STRIDE:
        die(f"generated link {network} is not a two-address /{P2P_LINK_PREFIXLEN}")
    return (
        f"{addrs[0]}/{P2P_LINK_PREFIXLEN}",
        f"{addrs[1]}/{P2P_LINK_PREFIXLEN}",
    )


def compute_mesh_link_params(
    cfg: ConfigData, hub: MeshHub, target_name: str
) -> LinkParams:
    key = mesh_link_key(hub.name, target_name)
    keys = mesh_link_keys(cfg, hub)
    network = stable_infra_link_network_for(cfg, key, f"mesh {hub.name}->{target_name}")
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=stable_port_for(
            hub.port_range,
            keys,
            key,
            f"mesh hub {hub.name} ports",
        ),
    )


def exit_out_iface_name(hub_name: str) -> str:
    return f"{hub_name}Out"


def exit_in_iface_name(hub_name: str) -> str:
    return f"{hub_name}In"


def mesh_server_iface_name_for_target(target_name: str) -> str:
    return f"{target_name}In"


def client_iface_name_for_target(
    cfg: ConfigData,
    target_name: str,
    hub_name: str,
) -> str:
    _ = cfg, target_name
    return f"{hub_name}Out"


def compute_exit_link_params(
    cfg: ConfigData, hub: ExitHub, router_name: str
) -> LinkParams:
    key = exit_link_key(hub.name, router_name)
    keys = exit_link_keys(cfg, hub)
    network = stable_infra_link_network_for(cfg, key, f"exit {hub.name}->{router_name}")
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=stable_port_for(
            hub.port_range,
            keys,
            key,
            f"Exit hub {hub.name} ports",
        ),
    )


def exit_reverse_listen_port(cfg: ConfigData, hub: ExitHub, router_name: str) -> int:
    if router_name not in cfg.mesh_hubs_by_name:
        die(f"router {router_name} is not a public mesh hub")

    mesh_hub = cfg.mesh_hubs_by_name[router_name]
    mesh_reserved = set(
        stable_unique_values(
            mesh_link_keys(cfg, mesh_hub),
            start=mesh_hub.port_range.start,
            end=mesh_hub.port_range.end,
            purpose="port",
            where=f"mesh hub {mesh_hub.name} ports",
        ).values()
    )

    key = exit_reverse_link_key(hub.name, router_name)
    keys = [
        exit_reverse_link_key(exit_hub.name, router_name) for exit_hub in cfg.exit_hubs
    ]
    return stable_port_avoiding_for(
        hub.port_range,
        keys,
        key,
        f"router {router_name} reverse exit ports",
        mesh_reserved,
    )


def compute_exit_reverse_link_params(
    cfg: ConfigData, hub: ExitHub, router_name: str
) -> LinkParams:
    key = exit_reverse_link_key(hub.name, router_name)
    network = stable_exit_reverse_link_network_for(
        cfg, key, f"exit-reverse {hub.name}->{router_name}"
    )
    srv_ip4, cli_ip4 = link_network_addresses(network)

    return LinkParams(
        srv_ip4=srv_ip4,
        cli_ip4=cli_ip4,
        srv_ll=ipv4_to_link_local(srv_ip4),
        cli_ll=ipv4_to_link_local(cli_ip4),
        port=exit_reverse_listen_port(cfg, hub, router_name),
    )


def compute_exit_exit_link_params(
    cfg: ConfigData, left_hub: ExitHub, right_hub: ExitHub
) -> ExitExitLinkParams:
    left_name, right_name = exit_exit_link_pair_for_hubs(
        cfg, left_hub.name, right_hub.name
    )
    hubs_by_name = {left_hub.name: left_hub, right_hub.name: right_hub}
    left = hubs_by_name[left_name]
    right = hubs_by_name[right_name]

    key = exit_exit_link_key(left.name, right.name)
    network = stable_exit_exit_link_network_for(
        cfg, key, f"exit-exit {left.name}Out->{right.name}In"
    )
    left_ip4, right_ip4 = link_network_addresses(network)

    left_reserved_ports = set(
        stable_unique_values(
            exit_link_keys(cfg, left),
            start=left.port_range.start,
            end=left.port_range.end,
            purpose="port",
            where=f"Exit hub {left.name} ports",
        ).values()
    )
    right_reserved_ports = set(
        stable_unique_values(
            exit_link_keys(cfg, right),
            start=right.port_range.start,
            end=right.port_range.end,
            purpose="port",
            where=f"Exit hub {right.name} ports",
        ).values()
    )

    return ExitExitLinkParams(
        left_name=left.name,
        right_name=right.name,
        left_ip4=left_ip4,
        right_ip4=right_ip4,
        left_ll=ipv4_to_link_local(left_ip4),
        right_ll=ipv4_to_link_local(right_ip4),
        left_port=stable_port_avoiding_for(
            left.port_range,
            exit_exit_link_keys_for_hub(cfg, left),
            key,
            f"Exit hub {left.name} exit-exit ports",
            left_reserved_ports,
        ),
        right_port=stable_port_avoiding_for(
            right.port_range,
            exit_exit_link_keys_for_hub(cfg, right),
            key,
            f"Exit hub {right.name} exit-exit ports",
            right_reserved_ports,
        ),
    )
