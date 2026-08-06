#!/usr/bin/env python3
from typing import Any

from .topology_svg_geometry import (
    build_overview_layout,
    overview_directed_link_points,
    overview_ring_wrap_points,
)


def _point_dicts(
    points: list[tuple[float, float]],
) -> list[dict[str, float]]:
    return [{"x": x, "y": y} for x, y in points]


def _line_paths(
    source_pos: tuple[int, int],
    target_pos: tuple[int, int],
    *,
    offset: float = 0.0,
) -> dict[str, list[dict[str, float]]]:
    topology = overview_directed_link_points(
        source_pos,
        target_pos,
        offset=offset,
        arrows=False,
    )
    from_points = overview_directed_link_points(
        source_pos,
        target_pos,
        offset=offset,
        arrows=True,
    )
    to_points = overview_directed_link_points(
        target_pos,
        source_pos,
        offset=-offset,
        arrows=True,
    )
    return {
        "topology": _point_dicts(topology),
        "from": _point_dicts(from_points),
        "to": _point_dicts(to_points),
    }


def _ring_wrap_paths(
    positions: dict[str, tuple[int, int]],
    first_id: str,
    last_id: str,
    source_id: str,
    target_id: str,
    wrap_side: str,
    outer_wrap: tuple[float, float, float] | None,
) -> dict[str, list[dict[str, float]]]:
    forward = overview_ring_wrap_points(
        positions,
        first_id,
        last_id,
        source_id,
        target_id,
        wrap_side,
        outer_wrap,
    )
    reverse = overview_ring_wrap_points(
        positions,
        first_id,
        last_id,
        target_id,
        source_id,
        wrap_side,
        outer_wrap,
    )
    return {
        "topology": _point_dicts(forward),
        "from": _point_dicts(forward),
        "to": _point_dicts(reverse),
    }


def _pair_key(group: str, left_id: str, right_id: str) -> tuple[str, str, str]:
    first, second = sorted((left_id, right_id))
    return group, first, second


def build_topology_2d_layout(data: dict[str, Any]) -> dict[str, Any]:
    nodes = list(data["nodes"])
    edges = list(data["edges"])
    public_exits = [node for node in nodes if node["layer"] == "public-exit"]
    reverse_exits = [node for node in nodes if node["layer"] == "reverse-exit"]
    spines = [node for node in nodes if node["layer"] == "spine"]
    leafs = [node for node in nodes if node["layer"] == "leaf"]
    top_exits = public_exits + reverse_exits

    layout = build_overview_layout(
        [node["id"] for node in spines],
        [node["id"] for node in public_exits],
        [node["id"] for node in reverse_exits],
        [node["id"] for node in leafs],
    )

    visual_nodes: list[dict[str, Any]] = []

    def add_nodes(
        row_nodes: list[dict[str, Any]],
        positions: dict[str, tuple[int, int]],
        row: str,
        *,
        direct_view: bool = False,
    ) -> None:
        for node in row_nodes:
            position = positions.get(node["id"])
            if position is None:
                continue
            x, y = position
            visual_nodes.append(
                {
                    "visual_id": f"{row}:{node['id']}",
                    "node_id": node["id"],
                    "x": x,
                    "y": y,
                    "row": row,
                    "direct_view": direct_view,
                }
            )

    add_nodes(top_exits, layout.exit_pos, "exit")
    add_nodes(spines, layout.spine_pos, "spine")
    add_nodes(leafs, layout.leaf_pos, "leaf")
    add_nodes(
        public_exits,
        layout.direct_exit_pos,
        "direct-exit",
        direct_view=True,
    )

    edge_by_key = {
        _pair_key(edge["group"], edge["a"], edge["b"]): edge for edge in edges
    }
    measured_edge_ids = {edge["id"] for edge in edges}
    visual_edges: list[dict[str, Any]] = []

    def edge_reference(edge: dict[str, Any]) -> dict[str, Any]:
        reference: dict[str, Any] = {"edge_id": edge["id"]}
        if edge["id"] not in measured_edge_ids:
            reference["edge"] = edge
        return reference

    def edge_for(
        group: str,
        link_type: str,
        left_id: str,
        right_id: str,
    ) -> dict[str, Any]:
        edge = edge_by_key.get(_pair_key(group, left_id, right_id))
        if edge is not None:
            return edge

        a_id, b_id = sorted((left_id, right_id))
        return {
            "id": f"{link_type}:{a_id}<->{b_id}",
            "link_type": link_type,
            "group": group,
            "a": a_id,
            "b": b_id,
            "a_to_b": None,
            "b_to_a": None,
        }

    def add_line(
        edge: dict[str, Any],
        source_id: str,
        target_id: str,
        source_pos: tuple[int, int] | None,
        target_pos: tuple[int, int] | None,
        row_key: str,
        *,
        offset: float = 0.0,
    ) -> None:
        if source_pos is None or target_pos is None:
            return
        visual_edges.append(
            {
                "visual_id": f"{edge['id']}:{row_key}",
                **edge_reference(edge),
                "group": edge["group"],
                "source_id": source_id,
                "target_id": target_id,
                "paths": _line_paths(
                    source_pos,
                    target_pos,
                    offset=offset,
                ),
            }
        )

    # Match render_topology_overview_svg exactly: build expected topology from
    # the node roles, then attach measured metrics when a matching edge exists.
    # Missing measurements must not remove a configured line from the canvas.
    for leaf in leafs:
        leaf_id = leaf["id"]
        leaf_pos = layout.leaf_pos.get(leaf_id)
        for spine in spines:
            spine_id = spine["id"]
            add_line(
                edge_for("leaf-spine", "mesh", leaf_id, spine_id),
                leaf_id,
                spine_id,
                leaf_pos,
                layout.spine_pos.get(spine_id),
                "leaf:spine",
            )

        for exit_node in public_exits:
            exit_id = exit_node["id"]
            add_line(
                edge_for("leaf-exit", "exit", leaf_id, exit_id),
                leaf_id,
                exit_id,
                leaf_pos,
                layout.direct_exit_pos.get(exit_id),
                "leaf:direct-exit",
            )

    for spine in spines:
        spine_id = spine["id"]
        spine_pos = layout.spine_pos.get(spine_id)
        for exit_node in top_exits:
            exit_id = exit_node["id"]
            exit_pos = layout.exit_pos.get(exit_id)
            add_line(
                edge_for("spine-exit", "exit", spine_id, exit_id),
                spine_id,
                exit_id,
                spine_pos,
                exit_pos,
                "spine:exit",
                offset=-4.0,
            )
            add_line(
                edge_for("exit-spine", "exit-in", exit_id, spine_id),
                exit_id,
                spine_id,
                exit_pos,
                spine_pos,
                "exit:spine",
                offset=-4.0,
            )

    def add_ring(
        ring_nodes: list[dict[str, Any]],
        group: str,
        link_type: str,
        positions: dict[str, tuple[int, int]],
        row: str,
        outer_wrap: tuple[float, float, float] | None,
    ) -> None:
        if len(ring_nodes) < 2:
            return

        def add_pair(
            left: dict[str, Any],
            right: dict[str, Any],
            *,
            wrap: bool = False,
            wrap_first: dict[str, Any] | None = None,
            wrap_last: dict[str, Any] | None = None,
        ) -> None:
            edge = edge_for(group, link_type, left["id"], right["id"])
            if wrap:
                if wrap_first is None or wrap_last is None:
                    return
                paths = _ring_wrap_paths(
                    positions,
                    wrap_first["id"],
                    wrap_last["id"],
                    left["id"],
                    right["id"],
                    "top",
                    outer_wrap,
                )
            else:
                left_pos = positions.get(left["id"])
                right_pos = positions.get(right["id"])
                if left_pos is None or right_pos is None:
                    return
                paths = _line_paths(left_pos, right_pos)
            visual_edges.append(
                {
                    "visual_id": f"{edge['id']}:{row}:{'wrap' if wrap else 'pair'}",
                    **edge_reference(edge),
                    "group": edge["group"],
                    "source_id": left["id"],
                    "target_id": right["id"],
                    "paths": paths,
                }
            )

        if len(ring_nodes) == 2:
            add_pair(ring_nodes[0], ring_nodes[1])
            return

        for index in range(len(ring_nodes) - 1):
            add_pair(ring_nodes[index], ring_nodes[index + 1])
        add_pair(
            ring_nodes[-1],
            ring_nodes[0],
            wrap=True,
            wrap_first=ring_nodes[0],
            wrap_last=ring_nodes[-1],
        )

    add_ring(
        spines,
        "spine-spine",
        "mesh",
        layout.spine_pos,
        "spine",
        layout.spine_ring_envelope,
    )
    add_ring(
        public_exits,
        "exit-exit",
        "exit-exit",
        layout.exit_pos,
        "exit",
        layout.exit_ring_envelope,
    )

    return {
        "width": layout.width,
        "height": layout.height,
        "row_labels": [
            {"text": "exit", "x": 35, "y": layout.exit_y},
            {"text": "spine", "x": 35, "y": layout.spine_y},
            {"text": "leaf", "x": 35, "y": layout.leaf_y},
            *(
                [{"text": "exit", "x": 35, "y": layout.direct_exit_y}]
                if public_exits
                else []
            ),
        ],
        "nodes": visual_nodes,
        "edges": visual_edges,
    }
