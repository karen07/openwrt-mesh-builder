#!/usr/bin/env python3
import argparse
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .topology_data import (
    SpeedIndex,
    SpeedRow,
    config_roles,
    infer_roles_from_rows,
    load_speed_rows,
    node_id,
    topology_rows_from_config,
    topology_rows_from_generated,
)
from .config_io import load_json_config
from .process import die
from .common import ConfigData, build_config_data
from .topology_metrics import display_link_text

LINK_GROUPS = (
    ("spine-spine", "spine <-> spine"),
    ("leaf-spine", "leaf <-> spine"),
    ("exit-spine", "exit -> spine"),
    ("spine-exit", "spine -> exit"),
    ("exit-exit", "exit <-> exit"),
    ("leaf-exit", "leaf -> exit"),
)


@dataclass(frozen=True)
class GraphNode:
    id: str
    kind: str
    name: str
    layer: str
    x: float
    y: float
    z: float


@dataclass(frozen=True)
class GraphEdge:
    id: str
    link_type: str
    group: str
    a: str
    b: str
    a_to_b: dict[str, Any] | None
    b_to_a: dict[str, Any] | None


def metric_to_dict(metric: object | None) -> dict[str, Any] | None:
    if metric is None:
        return None
    return {
        "mbps": getattr(metric, "mbps", 0.0),
        "status": getattr(metric, "status", "missing"),
        "iface": display_link_text(getattr(metric, "iface", "")),
        "peer_ip": getattr(metric, "peer_ip", ""),
    }


def keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def layer_positions(
    names: list[str],
    *,
    kind: str,
    layer: str,
    y: float,
    radius: float,
    phase: float,
) -> list[GraphNode]:
    if not names:
        return []

    out: list[GraphNode] = []
    count = len(names)
    for idx, name in enumerate(names):
        angle = phase + idx * 6.283185307179586 / count
        out.append(
            GraphNode(
                id=node_id(kind, name),
                kind=kind,
                name=name,
                layer=layer,
                x=radius * math.cos(angle),
                y=y,
                z=radius * math.sin(angle),
            )
        )
    return out


def public_and_reverse_exits(
    cfg: ConfigData | None,
    exits: list[str],
) -> tuple[list[str], list[str]]:
    if cfg is None:
        return exits, []

    public = [hub.name for hub in cfg.exit_hubs if hub.listen_ip]
    reverse = [hub.name for hub in cfg.exit_hubs if not hub.listen_ip]
    public = keep_order([name for name in public if name in set(exits)])
    reverse = keep_order([name for name in reverse if name in set(exits)])

    known = set(public) | set(reverse)
    unknown = [name for name in exits if name not in known]
    return keep_order(public + unknown), reverse


def graph_nodes(rows: list[SpeedRow], cfg: ConfigData | None) -> list[GraphNode]:
    row_roles = infer_roles_from_rows(rows)

    if cfg is None:
        routers = row_roles.routers
        spines = row_roles.spines
        exits = row_roles.exits
        role_cfg = None
    else:
        cfg_roles = config_roles(cfg)
        cfg_names = set(cfg_roles.routers + cfg_roles.exits)
        row_names = set(row_roles.routers + row_roles.exits)

        if row_names and not (row_names & cfg_names):
            # The default sample config does not describe an imported speed JSON.
            # In that case prefer the measured rows instead of adding wrong nodes.
            routers = row_roles.routers
            spines = row_roles.spines
            exits = row_roles.exits
            role_cfg = None
        else:
            routers = keep_order(cfg_roles.routers + row_roles.routers)
            spines = keep_order(cfg_roles.spines + row_roles.spines)
            exits = keep_order(cfg_roles.exits + row_roles.exits)
            role_cfg = cfg

    leafs = [name for name in routers if name not in set(spines)]
    public_exits, reverse_exits = public_and_reverse_exits(role_cfg, exits)

    public_phase = -math.pi / 2.0
    reverse_exit_phase = public_phase + math.pi / 5.0
    spine_phase = public_phase + math.pi / 3.0
    leaf_phase = public_phase + math.pi / 18.0

    nodes: list[GraphNode] = []
    nodes.extend(
        layer_positions(
            public_exits,
            kind="server",
            layer="public-exit",
            y=260.0,
            radius=340.0,
            phase=public_phase,
        )
    )
    nodes.extend(
        layer_positions(
            reverse_exits,
            kind="server",
            layer="reverse-exit",
            y=260.0,
            radius=220.0,
            phase=reverse_exit_phase,
        )
    )
    nodes.extend(
        layer_positions(
            spines,
            kind="router",
            layer="spine",
            y=60.0,
            radius=240.0,
            phase=spine_phase,
        )
    )
    nodes.extend(
        layer_positions(
            leafs,
            kind="router",
            layer="leaf",
            y=-180.0,
            radius=470.0,
            phase=leaf_phase,
        )
    )
    return nodes


def sorted_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def graph_edge_group(
    *,
    link_type: str,
    a: str,
    b: str,
    node_by_id: dict[str, GraphNode],
) -> str:
    a_layer = node_by_id.get(a).layer if a in node_by_id else ""
    b_layer = node_by_id.get(b).layer if b in node_by_id else ""
    layers = {a_layer, b_layer}

    if link_type == "mesh" and layers == {"spine"}:
        return "spine-spine"
    if link_type == "mesh" and layers == {"leaf", "spine"}:
        return "leaf-spine"
    if link_type == "exit-exit":
        return "exit-exit"
    if link_type == "exit-in":
        return "exit-spine"
    if link_type == "exit" and layers == {"leaf", "public-exit"}:
        return "leaf-exit"
    if link_type == "exit" and layers == {"spine", "public-exit"}:
        return "spine-exit"

    return link_type


def group_metadata(edges: list[GraphEdge]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for edge in edges:
        counts[edge.group] = counts.get(edge.group, 0) + 1

    out = [
        {"id": group_id, "label": label, "count": counts.get(group_id, 0)}
        for group_id, label in LINK_GROUPS
    ]

    known = {group_id for group_id, _label in LINK_GROUPS}
    for group_id in sorted(set(counts) - known):
        out.append({"id": group_id, "label": group_id, "count": counts[group_id]})

    return out


def graph_edges(
    rows: list[SpeedRow],
    node_by_id: dict[str, GraphNode],
) -> list[GraphEdge]:
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        a, b = sorted_pair(row.source_id, row.peer_id)
        seen.add((row.link_type, a, b))

    speeds = SpeedIndex(rows)
    out: list[GraphEdge] = []
    for link_type, a, b in sorted(seen):
        pair = speeds.pair(link_type, a, b)
        out.append(
            GraphEdge(
                id=f"{link_type}:{a}<->{b}",
                link_type=link_type,
                group=graph_edge_group(
                    link_type=link_type,
                    a=a,
                    b=b,
                    node_by_id=node_by_id,
                ),
                a=a,
                b=b,
                a_to_b=metric_to_dict(pair.a_to_b),
                b_to_a=metric_to_dict(pair.b_to_a),
            )
        )
    return out


def graph_from_rows(
    *,
    rows: list[SpeedRow],
    cfg: ConfigData | None,
    title: str,
    topology_only: bool,
    source_text: str,
) -> dict[str, Any]:
    nodes = graph_nodes(rows, cfg)
    node_by_id = {node.id: node for node in nodes}
    node_ids = set(node_by_id)
    edges = [
        edge
        for edge in graph_edges(rows, node_by_id)
        if edge.a in node_ids and edge.b in node_ids
    ]

    return {
        "title": title,
        "topology_only": topology_only,
        "source": source_text,
        "nodes": [asdict(node) for node in nodes],
        "edges": [asdict(edge) for edge in edges],
        "groups": group_metadata(edges),
        "layers": [
            {"id": "public-exit", "label": "public exit", "y": 260.0},
            {"id": "spine", "label": "spine", "y": 60.0},
            {"id": "leaf", "label": "leaf", "y": -180.0},
            {"id": "reverse-exit", "label": "reverse exit", "y": 260.0},
        ],
    }


def load_graph_data(args: argparse.Namespace) -> dict[str, Any]:
    cfg: ConfigData | None = None
    config_path = Path(args.config)
    if config_path.exists():
        cfg = build_config_data(load_json_config(config_path))

    if args.topology_only:
        if cfg is None:
            die(f"missing config file: {config_path}")
        if args.topology_source == "config":
            rows = topology_rows_from_config(cfg)
            source_text = "config topology only"
        else:
            rows, warnings = topology_rows_from_generated(cfg)
            for warning in warnings:
                print(f"topology warning: {warning}", file=sys.stderr)
            if not rows:
                die("no generated topology links found")
            source_text = "generated AWG/UCI topology"
        topology_only = True
    else:
        rows, generated_at, iperf_time = load_speed_rows(Path(args.speeds_json))
        if not rows:
            die(f"{args.speeds_json}: no rows found")
        parts = []
        if generated_at:
            parts.append(f"generated_at={generated_at}")
        if iperf_time:
            parts.append(f"iperf_time={iperf_time}s")
        source_text = ", ".join(parts) or str(args.speeds_json)
        topology_only = False

    return graph_from_rows(
        rows=rows,
        cfg=cfg,
        title=args.title,
        topology_only=topology_only,
        source_text=source_text,
    )
