from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from tools.config_io import load_json_config
from tools.process import die
from tools.common import (
    ConfigData,
    build_config_data,
    build_exit_client_alias,
    build_exit_exit_alias,
    build_exit_reverse_client_alias,
    client_iface_name_for_target,
    exit_exit_link_pairs,
    exit_in_iface_name,
    exit_out_iface_name,
    mesh_link_specs,
    mesh_server_iface_name_for_target,
)
from tools.topology_index import load_generated_topology_index
from tools.topology_metrics import (
    DirectedMetric,
    PairMetric,
    STATUS_TARGET,
    SpeedIndex,
    SpeedRow,
    TopologyRoles,
    format_metric,
    format_ts,
    load_speed_rows,
    node_id,
)


def config_roles(cfg: ConfigData) -> TopologyRoles:
    routers = [r.name for r in cfg.routers]
    spines = [h.name for h in cfg.mesh_hubs]
    leafs = [name for name in routers if name not in set(spines)]
    public_exits = [h.name for h in cfg.exit_hubs if h.listen_ip]
    reverse_exits = [h.name for h in cfg.exit_hubs if not h.listen_ip]
    exits = public_exits + reverse_exits
    return TopologyRoles(
        routers=routers,
        spines=spines,
        leafs=leafs,
        exits=exits,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def add_topology_row(
    rows: list[SpeedRow],
    source_kind: str,
    source: str,
    link_type: str,
    peer_kind: str,
    peer: str,
    iface: str,
) -> None:
    rows.append(
        SpeedRow(
            source_kind=source_kind,
            source=source,
            link_type=link_type,
            peer_kind=peer_kind,
            peer=peer,
            iface=iface,
            peer_ip="configured",
            mbps=0.0,
            status=STATUS_TARGET,
        )
    )


def add_topology_bidirectional_rows(
    rows: list[SpeedRow],
    left_kind: str,
    left: str,
    link_type: str,
    right_kind: str,
    right: str,
    iface: str,
) -> None:
    add_topology_row(rows, left_kind, left, link_type, right_kind, right, iface)
    add_topology_row(rows, right_kind, right, link_type, left_kind, left, iface)


def topology_rows_from_config(cfg: ConfigData) -> list[SpeedRow]:
    rows: list[SpeedRow] = []

    # Mesh layer:
    #   * every leaf/router to every spine;
    #   * spine-spine ring with one full-duplex tunnel per ring edge.
    for hub_name, target_name in mesh_link_specs(cfg):
        add_topology_bidirectional_rows(
            rows,
            "router",
            hub_name,
            "mesh",
            "router",
            target_name,
            f"mesh:{hub_name}<->{target_name}",
        )

    # Direct exit-out layer: every router/spine/leaf to every public exit.
    for hub in cfg.exit_hubs:
        if not hub.listen_ip:
            continue
        for router_name in cfg.router_names:
            add_topology_bidirectional_rows(
                rows,
                "router",
                router_name,
                "exit",
                "server",
                hub.name,
                f"exit-out:{router_name}<->{hub.name}",
            )

    # Reverse exit-in layer: every exit, public or grey/NAT, to every spine.
    for hub in cfg.exit_hubs:
        for spine in cfg.mesh_hubs:
            add_topology_bidirectional_rows(
                rows,
                "server",
                hub.name,
                "exit-in",
                "router",
                spine.name,
                f"exit-in:{hub.name}<->{spine.name}",
            )

    # Exit layer: exit-exit ring with one full-duplex tunnel per ring edge.
    for left_name, right_name in exit_exit_link_pairs(cfg):
        add_topology_bidirectional_rows(
            rows,
            "server",
            left_name,
            "exit-exit",
            "server",
            right_name,
            f"exit-ring:{left_name}<->{right_name}",
        )

    return rows


def topology_rows_from_generated(cfg: ConfigData) -> tuple[list[SpeedRow], list[str]]:
    rows: list[SpeedRow] = []
    generated = load_generated_topology_index(cfg)
    warnings: list[str] = list(generated.warnings)
    router_ifaces = generated.router_ifaces
    exit_aliases = generated.exit_aliases

    for hub_name, target_name in mesh_link_specs(cfg):
        hub_iface = mesh_server_iface_name_for_target(target_name)
        target_iface = client_iface_name_for_target(cfg, target_name, hub_name)
        hub_has = hub_iface in router_ifaces.get(hub_name, set())
        target_has = target_iface in router_ifaces.get(target_name, set())
        if hub_has and target_has:
            add_topology_bidirectional_rows(
                rows,
                "router",
                hub_name,
                "mesh",
                "router",
                target_name,
                f"mesh:{hub_iface}/{target_iface}",
            )
        elif hub_has or target_has:
            warnings.append(
                f"half-generated mesh link {hub_name}<->{target_name}: "
                f"{hub_name}:{hub_iface}={'yes' if hub_has else 'no'}, "
                f"{target_name}:{target_iface}={'yes' if target_has else 'no'}"
            )

    for hub in cfg.exit_hubs:
        if hub.listen_ip:
            for router_name in cfg.router_names:
                router_iface = exit_out_iface_name(hub.name)
                alias = build_exit_client_alias(cfg, hub.name, router_name)
                router_has = router_iface in router_ifaces.get(router_name, set())
                server_has = alias in exit_aliases.get(hub.name, set())
                if router_has and server_has:
                    add_topology_bidirectional_rows(
                        rows,
                        "router",
                        router_name,
                        "exit",
                        "server",
                        hub.name,
                        f"exit-out:{router_iface}/{alias}",
                    )
                elif router_has or server_has:
                    warnings.append(
                        f"half-generated exit-out link {router_name}<->{hub.name}: "
                        f"{router_name}:{router_iface}={'yes' if router_has else 'no'}, "
                        f"{hub.name}:{alias}.conf={'yes' if server_has else 'no'}"
                    )

        for spine in cfg.mesh_hubs:
            router_iface = exit_in_iface_name(hub.name)
            alias = build_exit_reverse_client_alias(cfg, hub.name, spine.name)
            router_has = router_iface in router_ifaces.get(spine.name, set())
            server_has = alias in exit_aliases.get(hub.name, set())
            if router_has and server_has:
                add_topology_bidirectional_rows(
                    rows,
                    "server",
                    hub.name,
                    "exit-in",
                    "router",
                    spine.name,
                    f"exit-in:{alias}/{router_iface}",
                )
            elif router_has or server_has:
                warnings.append(
                    f"half-generated exit-in link {hub.name}<->{spine.name}: "
                    f"{hub.name}:{alias}.conf={'yes' if server_has else 'no'}, "
                    f"{spine.name}:{router_iface}={'yes' if router_has else 'no'}"
                )

    for left_name, right_name in exit_exit_link_pairs(cfg):
        left_alias = build_exit_exit_alias(cfg, left_name, right_name)
        right_alias = build_exit_exit_alias(cfg, right_name, left_name)
        left_has = left_alias in exit_aliases.get(left_name, set())
        right_has = right_alias in exit_aliases.get(right_name, set())
        if left_has and right_has:
            add_topology_bidirectional_rows(
                rows,
                "server",
                left_name,
                "exit-exit",
                "server",
                right_name,
                f"exit-ring:{left_alias}/{right_alias}",
            )
        elif left_has or right_has:
            warnings.append(
                f"half-generated exit-exit link {left_name}Out->{right_name}In: "
                f"{left_name}:{left_alias}.conf={'yes' if left_has else 'no'}, "
                f"{right_name}:{right_alias}.conf={'yes' if right_has else 'no'}"
            )

    if not rows:
        warnings.append(
            "no generated AWG links found; run generate_configs.py first or use "
            "--topology-source config for a hypothetical config-based diagram"
        )

    return rows, warnings


def load_config_roles(config_path: Path, rows: list[SpeedRow]) -> TopologyRoles | None:
    if not config_path.exists():
        return None

    raw_cfg = load_json_config(config_path)
    cfg: ConfigData = build_config_data(raw_cfg)
    roles = config_roles(cfg)
    routers = roles.routers
    spines = roles.spines
    leafs = roles.leafs
    exits = roles.exits
    public_exits = roles.public_exits
    reverse_exits = roles.reverse_exits

    row_routers, row_exits = node_names_from_rows(rows)
    routers = keep_ordered_union(routers, sorted(row_routers))

    # The config is the source of truth for exit kind.  If a speed JSON contains
    # an unknown server node, keep it visible in the top exit row, but do not put
    # it into the public-exit ring.
    unknown_exits = [name for name in sorted(row_exits) if name not in set(exits)]
    exits = keep_ordered_union(exits, unknown_exits)
    reverse_exits = keep_ordered_union(reverse_exits, unknown_exits)
    leafs = [name for name in routers if name not in set(spines)]

    return TopologyRoles(
        routers=routers,
        spines=spines,
        leafs=leafs,
        exits=exits,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def infer_roles_from_rows(rows: list[SpeedRow]) -> TopologyRoles:
    routers, exits = node_names_from_rows(rows)
    mesh_targets_by_router: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        if row.link_type != "mesh" or row.source_kind != "router":
            continue
        if row.peer_kind != "router":
            continue
        mesh_targets_by_router[row.source].add(row.peer)

    if mesh_targets_by_router:
        counts = {name: len(peers) for name, peers in mesh_targets_by_router.items()}
        max_count = max(counts.values())
        min_count = min(counts.values())
        if max_count > min_count:
            spines = sorted(
                name for name, count in counts.items() if count == max_count
            )
        else:
            spines = sorted(counts)
    else:
        spines = []

    routers_sorted = sorted(routers)
    leafs = [name for name in routers_sorted if name not in set(spines)]
    exits_sorted = sorted(exits)
    public_exits = sorted(
        name
        for name in exits
        if any(
            row.link_type in {"exit", "exit-exit"}
            and (
                (row.source_kind == "server" and row.source == name)
                or (row.peer_kind == "server" and row.peer == name)
            )
            for row in rows
        )
    )
    reverse_exits = [name for name in exits_sorted if name not in set(public_exits)]
    return TopologyRoles(
        routers=routers_sorted,
        spines=spines,
        leafs=leafs,
        exits=exits_sorted,
        public_exits=public_exits,
        reverse_exits=reverse_exits,
    )


def node_names_from_rows(rows: list[SpeedRow]) -> tuple[set[str], set[str]]:
    routers: set[str] = set()
    exits: set[str] = set()
    for row in rows:
        if row.source_kind == "router":
            routers.add(row.source)
        elif row.source_kind == "server":
            exits.add(row.source)
        if row.peer_kind == "router":
            routers.add(row.peer)
        elif row.peer_kind == "server":
            exits.add(row.peer)
    return routers, exits


def keep_ordered_union(primary: list[str], secondary: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for name in primary + secondary:
        if name in seen:
            continue
        seen.add(name)
        out.append(name)
    return out
