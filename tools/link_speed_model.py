#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from dataclasses import asdict, dataclass
from typing import Any

from tools.process import die
from tools.remote_hosts import server_ssh_hosts
from tools.common import (
    ConfigData,
    ExitHub,
    build_exit_client_alias,
    build_exit_exit_alias,
    build_exit_reverse_client_alias,
    client_iface_name_for_target,
    compute_exit_exit_link_params,
    compute_exit_link_params,
    compute_exit_reverse_link_params,
    compute_mesh_link_params,
    exit_exit_peer_names_for_hub,
    exit_in_iface_name,
    exit_out_iface_name,
    ipv4_without_prefix,
    mesh_link_specs_for_router,
    mesh_server_iface_name_for_target,
)
from tools.topology_index import GeneratedTopologyIndex
from tools.tunnel_model import exit_hub_is_public, router_is_public_mesh_hub

STATUS_TARGET = "target"


@dataclass(frozen=True)
class NodeRef:
    kind: str
    name: str
    ssh_hosts: tuple[str, ...]


@dataclass(frozen=True)
class IperfTarget:
    link_type: str
    peer_kind: str
    peer_name: str
    iface: str
    peer_ip: str

    @property
    def label(self) -> str:
        return f"{self.link_type}|{self.peer_kind}|{self.peer_name}|{self.iface}"


@dataclass(frozen=True)
class LinkSpeedRow:
    source_kind: str
    source: str
    source_ssh: str
    link_type: str
    peer_kind: str
    peer: str
    iface: str
    peer_ip: str
    mbps: float
    status: str


def ipv4_addr(value: str) -> str:
    return ipv4_without_prefix(value)


def sort_targets(targets: list[IperfTarget]) -> list[IperfTarget]:
    return sorted(
        targets, key=lambda t: (t.link_type, t.peer_kind, t.peer_name, t.iface)
    )


def sort_rows(rows: list[LinkSpeedRow]) -> list[LinkSpeedRow]:
    return sorted(
        rows,
        key=lambda r: (
            r.source_kind,
            r.source,
            r.link_type,
            r.peer_kind,
            r.peer,
            r.iface,
        ),
    )


def row_from_target(
    source: NodeRef,
    target: IperfTarget,
    *,
    source_ssh: str,
    mbps: float = 0.0,
    status: str = STATUS_TARGET,
) -> LinkSpeedRow:
    return LinkSpeedRow(
        source_kind=source.kind,
        source=source.name,
        source_ssh=source_ssh,
        link_type=target.link_type,
        peer_kind=target.peer_kind,
        peer=target.peer_name,
        iface=target.iface,
        peer_ip=target.peer_ip,
        mbps=mbps,
        status=status,
    )


def router_targets_from_config(cfg: ConfigData, router_name: str) -> list[IperfTarget]:
    targets: list[IperfTarget] = []

    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        if router_name == hub_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=target_name,
                    iface=mesh_server_iface_name_for_target(target_name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )
        elif router_name == target_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=hub_name,
                    iface=client_iface_name_for_target(cfg, router_name, hub_name),
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="server",
                    peer_name=hub.name,
                    iface=exit_out_iface_name(hub.name),
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

        if router_is_public_mesh_hub(cfg, router_name):
            link = compute_exit_reverse_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit-in",
                    peer_kind="server",
                    peer_name=hub.name,
                    iface=exit_in_iface_name(hub.name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    return sort_targets(targets)


def router_targets_from_generated(
    cfg: ConfigData,
    generated: GeneratedTopologyIndex,
    router_name: str,
) -> list[IperfTarget]:
    targets: list[IperfTarget] = []

    for hub_name, target_name in mesh_link_specs_for_router(cfg, router_name):
        hub = cfg.mesh_hubs_by_name[hub_name]
        link = compute_mesh_link_params(cfg, hub, target_name)
        hub_iface = mesh_server_iface_name_for_target(target_name)
        target_iface = client_iface_name_for_target(cfg, target_name, hub_name)
        hub_has = hub_iface in generated.router_ifaces.get(hub_name, set())
        target_has = target_iface in generated.router_ifaces.get(target_name, set())
        if not (hub_has and target_has):
            continue

        if router_name == hub_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=target_name,
                    iface=hub_iface,
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )
        elif router_name == target_name:
            targets.append(
                IperfTarget(
                    link_type="mesh",
                    peer_kind="router",
                    peer_name=hub_name,
                    iface=target_iface,
                    peer_ip=ipv4_addr(link.srv_ip4),
                )
            )

    for hub in cfg.exit_hubs:
        if exit_hub_is_public(hub):
            router_iface = exit_out_iface_name(hub.name)
            alias = build_exit_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if router_has and server_has:
                link = compute_exit_link_params(cfg, hub, router_name)
                targets.append(
                    IperfTarget(
                        link_type="exit",
                        peer_kind="server",
                        peer_name=hub.name,
                        iface=router_iface,
                        peer_ip=ipv4_addr(link.srv_ip4),
                    )
                )

        if router_is_public_mesh_hub(cfg, router_name):
            router_iface = exit_in_iface_name(hub.name)
            alias = build_exit_reverse_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if router_has and server_has:
                link = compute_exit_reverse_link_params(cfg, hub, router_name)
                targets.append(
                    IperfTarget(
                        link_type="exit-in",
                        peer_kind="server",
                        peer_name=hub.name,
                        iface=router_iface,
                        peer_ip=ipv4_addr(link.cli_ip4),
                    )
                )

    return sort_targets(targets)


def exit_exit_peer_target(
    cfg: ConfigData, source: ExitHub, peer: ExitHub
) -> IperfTarget:
    link = compute_exit_exit_link_params(cfg, source, peer)

    if source.name == link.left_name:
        peer_ip = ipv4_addr(link.right_ip4)
    elif source.name == link.right_name:
        peer_ip = ipv4_addr(link.left_ip4)
    else:
        die(
            f"bad exit-exit source mapping: "
            f"{source.name} vs {link.left_name}<->{link.right_name}"
        )

    return IperfTarget(
        link_type="exit-exit",
        peer_kind="server",
        peer_name=peer.name,
        iface=build_exit_exit_alias(cfg, source.name, peer.name),
        peer_ip=peer_ip,
    )


def server_targets_from_config(cfg: ConfigData, exit_name: str) -> list[IperfTarget]:
    hub = cfg.exit_hubs_by_name.get(exit_name)
    if hub is None:
        die(f"unknown exit hub: {exit_name}")

    targets: list[IperfTarget] = []

    if exit_hub_is_public(hub):
        for router_name in cfg.router_names:
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="router",
                    peer_name=router_name,
                    iface=build_exit_client_alias(cfg, hub.name, router_name),
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    for mesh_hub in cfg.mesh_hubs:
        link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
        targets.append(
            IperfTarget(
                link_type="exit-in",
                peer_kind="router",
                peer_name=mesh_hub.name,
                iface=build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name),
                peer_ip=ipv4_addr(link.srv_ip4),
            )
        )

    for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
        targets.append(
            exit_exit_peer_target(cfg, hub, cfg.exit_hubs_by_name[peer_name])
        )

    return sort_targets(targets)


def server_targets_from_generated(
    cfg: ConfigData,
    generated: GeneratedTopologyIndex,
    exit_name: str,
) -> list[IperfTarget]:
    hub = cfg.exit_hubs_by_name.get(exit_name)
    if hub is None:
        die(f"unknown exit hub: {exit_name}")

    targets: list[IperfTarget] = []

    if exit_hub_is_public(hub):
        for router_name in cfg.router_names:
            router_iface = exit_out_iface_name(hub.name)
            alias = build_exit_client_alias(cfg, hub.name, router_name)
            router_has = router_iface in generated.router_ifaces.get(router_name, set())
            server_has = alias in generated.exit_aliases.get(hub.name, set())
            if not (router_has and server_has):
                continue
            link = compute_exit_link_params(cfg, hub, router_name)
            targets.append(
                IperfTarget(
                    link_type="exit",
                    peer_kind="router",
                    peer_name=router_name,
                    iface=alias,
                    peer_ip=ipv4_addr(link.cli_ip4),
                )
            )

    for mesh_hub in cfg.mesh_hubs:
        router_iface = exit_in_iface_name(hub.name)
        alias = build_exit_reverse_client_alias(cfg, hub.name, mesh_hub.name)
        router_has = router_iface in generated.router_ifaces.get(mesh_hub.name, set())
        server_has = alias in generated.exit_aliases.get(hub.name, set())
        if not (router_has and server_has):
            continue
        link = compute_exit_reverse_link_params(cfg, hub, mesh_hub.name)
        targets.append(
            IperfTarget(
                link_type="exit-in",
                peer_kind="router",
                peer_name=mesh_hub.name,
                iface=alias,
                peer_ip=ipv4_addr(link.srv_ip4),
            )
        )

    for peer_name in exit_exit_peer_names_for_hub(cfg, hub):
        peer = cfg.exit_hubs_by_name[peer_name]
        alias = build_exit_exit_alias(cfg, hub.name, peer.name)
        peer_alias = build_exit_exit_alias(cfg, peer.name, hub.name)
        server_has = alias in generated.exit_aliases.get(hub.name, set())
        peer_has = peer_alias in generated.exit_aliases.get(peer.name, set())
        if server_has and peer_has:
            targets.append(exit_exit_peer_target(cfg, hub, peer))

    return sort_targets(targets)


def source_nodes(cfg: ConfigData, server_ssh_mode: str = "auto") -> list[NodeRef]:
    out: list[NodeRef] = []
    for router in cfg.routers:
        out.append(
            NodeRef(kind="router", name=router.name, ssh_hosts=(router.ssh_host,))
        )
    for hub in cfg.exit_hubs:
        out.append(
            NodeRef(
                kind="server",
                name=hub.name,
                ssh_hosts=server_ssh_hosts(hub.name, server_ssh_mode),
            )
        )
    return out


def targets_for_source(
    cfg: ConfigData,
    source: NodeRef,
    *,
    topology_source: str,
    generated: GeneratedTopologyIndex | None,
) -> list[IperfTarget]:
    if source.kind == "router":
        if topology_source == "generated":
            assert generated is not None
            return router_targets_from_generated(cfg, generated, source.name)
        return router_targets_from_config(cfg, source.name)

    if source.kind == "server":
        if topology_source == "generated":
            assert generated is not None
            return server_targets_from_generated(cfg, generated, source.name)
        return server_targets_from_config(cfg, source.name)

    die(f"unknown source kind: {source.kind}")


def format_table(rows: list[LinkSpeedRow]) -> str:
    headers = ["source", "link", "peer", "iface", "peer_ip", "mbps", "status"]
    body = [
        [
            f"{r.source_kind}:{r.source}",
            r.link_type,
            f"{r.peer_kind}:{r.peer}",
            r.iface,
            r.peer_ip,
            f"{r.mbps:.1f}",
            r.status,
        ]
        for r in rows
    ]

    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def render(row: list[str]) -> str:
        return "  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()

    lines = [render(headers), render(["-" * w for w in widths])]
    lines.extend(render(row) for row in body)
    return "\n".join(lines)


def format_tsv(rows: list[LinkSpeedRow]) -> str:
    lines = [
        "source_kind\tsource\tlink_type\tpeer_kind\tpeer\tiface\tpeer_ip\tmbps\tstatus"
    ]
    for row in rows:
        lines.append(
            "\t".join(
                [
                    row.source_kind,
                    row.source,
                    row.link_type,
                    row.peer_kind,
                    row.peer,
                    row.iface,
                    row.peer_ip,
                    f"{row.mbps:.3f}",
                    row.status,
                ]
            )
        )
    return "\n".join(lines)


def speed_rows_payload(
    rows: list[LinkSpeedRow],
    *,
    generated_at: int,
    iperf_time: int,
    iperf_bitrate: str,
    topology_source: str,
    server_ssh_mode: str,
) -> dict[str, Any]:
    return {
        "generated_at": generated_at,
        "iperf_time": iperf_time,
        "iperf_bitrate": iperf_bitrate,
        "topology_source": topology_source,
        "server_ssh_mode": server_ssh_mode,
        "rows": [asdict(row) for row in rows],
    }
