#!/usr/bin/env python3

from .default import TOPOLOGY_NODE_R as NODE_R
from .topology_data import SpeedIndex, TopologyRoles, node_id


def resolve_link_positions(
    source_id: str,
    peer_id: str,
    left_id: str,
    left_xy: tuple[int, int],
    right_id: str,
    right_xy: tuple[int, int],
) -> tuple[tuple[int, int], tuple[int, int]]:
    if source_id == left_id and peer_id == right_id:
        return left_xy, right_xy
    if source_id == right_id and peer_id == left_id:
        return right_xy, left_xy
    raise ValueError(
        f"link endpoints do not match positions: {source_id=} {peer_id=} "
        f"{left_id=} {right_id=}"
    )


def canonical_offset(
    offset: float,
    source_id: str,
    left_id: str,
    right_id: str,
) -> float:
    if source_id == left_id:
        return offset
    if source_id == right_id:
        return -offset
    raise ValueError(
        f"link source does not match canonical endpoints: {source_id=} "
        f"{left_id=} {right_id=}"
    )


from .topology_svg_geometry import (
    add_overview_directed_link,
    add_overview_ring_links,
    layout_leaf_row,
    layout_spine_row,
    overview_directed_metric,
    overview_ring_wrap_envelope,
)
from .topology_svg_theme import (
    SvgFile,
    add_node,
    add_speed_legend,
    add_topology_link_legend,
    finish_svg,
    start_svg,
    topology_link_color,
)


def render_topology_overview_svg(
    roles: TopologyRoles,
    speeds: SpeedIndex,
    title: str,
    generated_text: str,
    topology_only_data: bool,
    mode: str = "topology",
) -> str:
    if mode not in {"topology", "from", "to"}:
        raise ValueError(f"unsupported topology SVG mode: {mode}")

    speed_direction = None if mode == "topology" else mode
    topology_colors = mode == "topology"
    spines = list(roles.spines)
    public_exits = list(roles.public_exits)
    reverse_exits = list(roles.reverse_exits)
    exits = public_exits + reverse_exits
    leafs = roles.leafs
    max_count = max(len(spines), len(exits), len(public_exits), len(leafs), 2)
    width = max(1000, 128 * max_count + 220)
    height = 930
    margin = 135
    # Keep enough header room for wrapped subtitles and the outer spine ring.
    # The spine ring is drawn above the exit row, so the diagram starts lower
    # than a normal four-row layout.
    exit_y = 190
    spine_y = 355
    leaf_y = 585
    direct_exit_y = 780

    exit_pos = layout_spine_row(exits, exit_y, width, margin)
    spine_pos = layout_spine_row(spines, spine_y, width, margin)
    leaf_pos = layout_leaf_row(leafs, leaf_y, width, margin)
    direct_exit_pos = layout_spine_row(public_exits, direct_exit_y, width, margin)

    exit_ring_envelope = overview_ring_wrap_envelope(
        public_exits,
        exit_pos,
        "top",
    )
    all_exit_envelope = overview_ring_wrap_envelope(
        exits,
        exit_pos,
        "top",
    )

    if exits:
        # The spine ring is an outer envelope for the whole visible exit row,
        # including reverse exits.  If the public-exit ring is present, place
        # the spine wrap slightly above it; otherwise place it slightly above
        # the exit nodes.
        exit_xs = [x for x, _ in exit_pos.values()]
        if all_exit_envelope is not None:
            exit_left, exit_right, _ = all_exit_envelope
        else:
            exit_left = min(exit_xs) - NODE_R - 28
            exit_right = max(exit_xs) + NODE_R + 28

        if exit_ring_envelope is not None:
            _, _, exit_wrap_y = exit_ring_envelope
            spine_wrap_y = exit_wrap_y - 30
        else:
            spine_wrap_y = exit_y - NODE_R - 30

        spine_ring_envelope = (
            exit_left - 36,
            exit_right + 36,
            spine_wrap_y,
        )
    else:
        spine_ring_envelope = None

    if topology_only_data:
        origin = "Topology from generated AWG/UCI topology"
        direction_text = "configured links"
    elif mode == "topology":
        origin = "Measured topology overview"
        direction_text = "measured links with topology colors"
    else:
        origin = "Measured topology overview"
        direction_text = (
            "speeds from row nodes to peers; arrows show shown direction"
            if mode == "from"
            else "speeds to row nodes from peers; arrows show shown direction"
        )

    subtitle = (
        f"{origin} at {generated_text}; {direction_text}; "
        "real/generated links; spine ring, exit ring, leaf-spine, "
        "spine-exit / exit-spine lanes, leaf-exit direct, mirrored exit ring; "
        "wrap stubs shown"
    )
    out = start_svg(width, height, f"{title}: {mode}", subtitle)
    if mode in {"from", "to"} and not topology_only_data:
        add_speed_legend(out, width, 118)

    out.append(f'<text x="35" y="{exit_y + 4}" class="row-label">exit</text>')
    out.append(f'<text x="35" y="{spine_y + 4}" class="row-label">spine</text>')
    out.append(f'<text x="35" y="{leaf_y + 4}" class="row-label">leaf</text>')
    if public_exits:
        out.append(
            f'<text x="35" y="{direct_exit_y + 4}" class="row-label">exit</text>'
        )

    # Light background links first.
    for leaf, leaf_xy in leaf_pos.items():
        leaf_id = node_id("router", leaf)
        for spine, spine_xy in spine_pos.items():
            spine_id = node_id("router", spine)
            metric, metric_source, metric_peer = overview_directed_metric(
                speeds, "mesh", leaf_id, spine_id, speed_direction
            )
            source_xy, peer_xy = resolve_link_positions(
                metric_source,
                metric_peer,
                leaf_id,
                leaf_xy,
                spine_id,
                spine_xy,
            )
            add_overview_directed_link(
                out,
                source_xy,
                peer_xy,
                metric_source,
                metric_peer,
                "mesh",
                metric,
                "topology-link",
                arrows=speed_direction is not None,
                stroke_override=topology_link_color(
                    "leaf-spine",
                    topology_colors,
                ),
            )

        for exit_name, exit_xy in direct_exit_pos.items():
            exit_id = node_id("server", exit_name)
            metric, metric_source, metric_peer = overview_directed_metric(
                speeds, "exit", leaf_id, exit_id, speed_direction
            )
            source_xy, peer_xy = resolve_link_positions(
                metric_source,
                metric_peer,
                leaf_id,
                leaf_xy,
                exit_id,
                exit_xy,
            )
            add_overview_directed_link(
                out,
                source_xy,
                peer_xy,
                metric_source,
                metric_peer,
                "exit",
                metric,
                "topology-primary-link",
                arrows=speed_direction is not None,
                stroke_override=topology_link_color(
                    "leaf-exit",
                    topology_colors,
                ),
            )

    for spine, spine_xy in spine_pos.items():
        spine_id = node_id("router", spine)
        for exit_name, exit_xy in exit_pos.items():
            exit_id = node_id("server", exit_name)
            out_metric, out_source, out_peer = overview_directed_metric(
                speeds, "exit", spine_id, exit_id, speed_direction
            )
            source_xy, peer_xy = resolve_link_positions(
                out_source,
                out_peer,
                spine_id,
                spine_xy,
                exit_id,
                exit_xy,
            )
            add_overview_directed_link(
                out,
                source_xy,
                peer_xy,
                out_source,
                out_peer,
                "exit",
                out_metric,
                "topology-primary-link",
                offset=canonical_offset(
                    -4.0,
                    out_source,
                    spine_id,
                    exit_id,
                ),
                arrows=speed_direction is not None,
                stroke_override=topology_link_color(
                    "spine-exit",
                    topology_colors,
                ),
            )

            if speed_direction == "to":
                in_metric = speeds.directed("exit-in", spine_id, exit_id)
                in_source, in_peer = spine_id, exit_id
            else:
                in_metric = speeds.directed("exit-in", exit_id, spine_id)
                in_source, in_peer = exit_id, spine_id

            # Draw ExitIn on the same visual segment as ExitOut, but on the
            # other side of it.  This keeps the two logical tunnels visible
            # without arrows or fixed red/blue colors.
            source_xy, peer_xy = resolve_link_positions(
                in_source,
                in_peer,
                spine_id,
                spine_xy,
                exit_id,
                exit_xy,
            )
            add_overview_directed_link(
                out,
                source_xy,
                peer_xy,
                in_source,
                in_peer,
                "exit-in",
                in_metric,
                "topology-primary-link topology-reverse-link",
                offset=canonical_offset(
                    4.0,
                    in_source,
                    spine_id,
                    exit_id,
                ),
                arrows=speed_direction is not None,
                stroke_override=topology_link_color(
                    "exit-spine",
                    topology_colors,
                ),
            )

    # Ring links are drawn above the full-mesh background.
    add_overview_ring_links(
        out,
        spines,
        "router",
        "mesh",
        spine_pos,
        width,
        "top",
        speeds,
        speed_direction,
        outer_wrap=spine_ring_envelope,
        stroke_override=topology_link_color("spine-spine", topology_colors),
    )
    add_overview_ring_links(
        out,
        public_exits,
        "server",
        "exit-exit",
        exit_pos,
        width,
        "top",
        speeds,
        speed_direction,
        stroke_override=topology_link_color("exit-exit", topology_colors),
    )
    # The bottom exit row is a direct leaf->public-exit view.  Do not draw
    # the exit-exit ring there; the public-exit ring is shown only on the top
    # exit row, where reverse exits are also visible as non-ring nodes.

    for name, (x, y) in exit_pos.items():
        add_node(out, x, y, name, "exit-node", title=node_id("server", name))
    for name, (x, y) in spine_pos.items():
        add_node(out, x, y, name, "spine-node", title=node_id("router", name))
    for name, (x, y) in leaf_pos.items():
        add_node(out, x, y, name, "leaf-node", title=node_id("router", name))
    for name, (x, y) in direct_exit_pos.items():
        add_node(
            out,
            x,
            y,
            name,
            "exit-node",
            title=f"{node_id('server', name)} (direct view)",
        )

    if topology_colors:
        add_topology_link_legend(out, 35, height - 55)

    return finish_svg(out)
