#!/usr/bin/env python3

from dataclasses import dataclass

from .default import TOPOLOGY_NODE_R as NODE_R
from .topology_data import DirectedMetric, SpeedIndex, format_metric, node_id
from .topology_svg_theme import (
    esc,
    marker_id_for_color,
    metric_color,
    pair_color,
)


def layout_leaf_row(
    names: list[str], y: int, width: int, margin: int
) -> dict[str, tuple[int, int]]:
    if not names:
        return {}
    if len(names) == 1:
        return {names[0]: (width // 2, y)}
    step = (width - 2 * margin) / (len(names) - 1)
    return {name: (round(margin + i * step), y) for i, name in enumerate(names)}


def layout_spine_row(
    names: list[str], y: int, width: int, margin: int
) -> dict[str, tuple[int, int]]:
    if not names:
        return {}
    usable = width - 2 * margin
    step = usable / (len(names) + 1)
    return {name: (round(margin + (i + 1) * step), y) for i, name in enumerate(names)}


@dataclass(frozen=True)
class OverviewLayout:
    width: int
    height: int
    margin: int
    exit_y: int
    spine_y: int
    leaf_y: int
    direct_exit_y: int
    exit_pos: dict[str, tuple[int, int]]
    spine_pos: dict[str, tuple[int, int]]
    leaf_pos: dict[str, tuple[int, int]]
    direct_exit_pos: dict[str, tuple[int, int]]
    exit_ring_envelope: tuple[float, float, float] | None
    spine_ring_envelope: tuple[float, float, float] | None


def build_overview_layout(
    spines: list[str],
    public_exits: list[str],
    reverse_exits: list[str],
    leafs: list[str],
) -> OverviewLayout:
    exits = public_exits + reverse_exits
    max_count = max(len(spines), len(exits), len(public_exits), len(leafs), 2)
    width = max(1000, 128 * max_count + 220)
    height = 930
    margin = 135
    exit_y = 190
    spine_y = 355
    leaf_y = 585
    direct_exit_y = 780

    exit_pos = layout_spine_row(exits, exit_y, width, margin)
    spine_pos = layout_spine_row(spines, spine_y, width, margin)
    leaf_pos = layout_leaf_row(leafs, leaf_y, width, margin)
    direct_exit_pos = layout_spine_row(
        public_exits,
        direct_exit_y,
        width,
        margin,
    )

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
        exit_xs = [x for x, _y in exit_pos.values()]
        if all_exit_envelope is not None:
            exit_left, exit_right, _wrap_y = all_exit_envelope
        else:
            exit_left = min(exit_xs) - NODE_R - 28
            exit_right = max(exit_xs) + NODE_R + 28

        if exit_ring_envelope is not None:
            _left, _right, exit_wrap_y = exit_ring_envelope
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

    return OverviewLayout(
        width=width,
        height=height,
        margin=margin,
        exit_y=exit_y,
        spine_y=spine_y,
        leaf_y=leaf_y,
        direct_exit_y=direct_exit_y,
        exit_pos=exit_pos,
        spine_pos=spine_pos,
        leaf_pos=leaf_pos,
        direct_exit_pos=direct_exit_pos,
        exit_ring_envelope=exit_ring_envelope,
        spine_ring_envelope=spine_ring_envelope,
    )


def endpoint_on_circle(
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    radius: int,
) -> tuple[float, float]:
    dx = x2 - x1
    dy = y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return float(x1), float(y1)
    return x1 + dx * radius / length, y1 + dy * radius / length


def directed_tooltip(
    source_id: str,
    peer_id: str,
    link_type: str,
    metric: DirectedMetric | None,
) -> str:
    return f"{source_id} -> {peer_id} [{link_type}]: {format_metric(metric)}"


def offset_segment(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    offset: float,
) -> tuple[float, float, float, float]:
    dx = x2 - x1
    dy = y2 - y1
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0.0 or offset == 0.0:
        return x1, y1, x2, y2
    nx = -dy / length
    ny = dx / length
    return x1 + nx * offset, y1 + ny * offset, x2 + nx * offset, y2 + ny * offset


def overview_directed_link_points(
    source_pos: tuple[int, int],
    peer_pos: tuple[int, int],
    *,
    offset: float = 0.0,
    arrows: bool = False,
) -> list[tuple[float, float]]:
    ax, ay = source_pos
    bx, by = peer_pos
    sx, sy = endpoint_on_circle(ax, ay, bx, by, NODE_R)
    end_radius = NODE_R + (2 if arrows else 0)
    ex, ey = endpoint_on_circle(bx, by, ax, ay, end_radius)
    sx, sy, ex, ey = offset_segment(sx, sy, ex, ey, offset)
    return [(sx, sy), (ex, ey)]


def overview_pair_link_points(
    pos: dict[str, tuple[int, int]],
    source: str,
    target: str,
    *,
    arrows: bool = False,
) -> list[tuple[float, float]]:
    return overview_directed_link_points(
        pos[source],
        pos[target],
        arrows=arrows,
    )


def overview_ring_wrap_points(
    pos: dict[str, tuple[int, int]],
    first: str,
    last: str,
    source: str,
    target: str,
    wrap_side: str,
    outer_wrap: tuple[float, float, float] | None = None,
) -> list[tuple[float, float]]:
    first_x, row_y = pos[first]
    last_x, _last_y = pos[last]
    direction = -1 if wrap_side == "top" else 1
    stub = 28
    pad = 56

    first_inner_x = first_x - NODE_R
    last_inner_x = last_x + NODE_R

    if outer_wrap is None:
        left_outer_x = first_inner_x - stub
        right_outer_x = last_inner_x + stub
        wrap_y = row_y + direction * pad
    else:
        left_outer_x, right_outer_x, wrap_y = outer_wrap

    first_to_last = [
        (first_inner_x, row_y),
        (left_outer_x, row_y),
        (left_outer_x, wrap_y),
        (right_outer_x, wrap_y),
        (right_outer_x, row_y),
        (last_inner_x, row_y),
    ]
    if source == first and target == last:
        return first_to_last
    if source == last and target == first:
        return list(reversed(first_to_last))
    raise ValueError(
        f"ring wrap direction must be {first}->{last} or {last}->{first}: "
        f"got {source}->{target}"
    )


def add_overview_directed_link(
    out: list[str],
    source_pos: tuple[int, int],
    peer_pos: tuple[int, int],
    source_id: str,
    peer_id: str,
    link_type: str,
    metric: DirectedMetric | None,
    class_name: str,
    offset: float = 0.0,
    arrows: bool = False,
    stroke_override: str | None = None,
) -> None:
    if metric is None:
        return
    points = overview_directed_link_points(
        source_pos,
        peer_pos,
        offset=offset,
        arrows=arrows,
    )
    (sx, sy), (ex, ey) = points
    color = stroke_override or metric_color(metric)
    marker = f' marker-end="url(#{marker_id_for_color(color)})"' if arrows else ""
    tooltip = directed_tooltip(source_id, peer_id, link_type, metric)

    out.append(f"<g><title>{esc(tooltip)}</title>")
    out.append(
        f'<line class="{class_name}" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"{marker}/>'
    )
    out.append("</g>")


def add_overview_pair_link(
    out: list[str],
    pos: dict[str, tuple[int, int]],
    a: str,
    b: str,
    color: str,
    tooltip: str,
    class_name: str,
    arrows: bool = False,
    source: str | None = None,
    target: str | None = None,
) -> None:
    start_name = source or a
    end_name = target or b
    points = overview_pair_link_points(
        pos,
        start_name,
        end_name,
        arrows=arrows,
    )
    (sx, sy), (ex, ey) = points
    marker = f' marker-end="url(#{marker_id_for_color(color)})"' if arrows else ""

    out.append(f"<g><title>{esc(tooltip)}</title>")
    out.append(
        f'<line class="{class_name}" x1="{sx:.1f}" y1="{sy:.1f}" '
        f'x2="{ex:.1f}" y2="{ey:.1f}" stroke="{color}"{marker}/>'
    )
    out.append("</g>")


def overview_directed_metric(
    speeds: SpeedIndex,
    link_type: str,
    source_id: str,
    peer_id: str,
    speed_direction: str | None,
) -> tuple[DirectedMetric | None, str, str]:
    if speed_direction == "to":
        return speeds.directed(link_type, peer_id, source_id), peer_id, source_id
    return speeds.directed(link_type, source_id, peer_id), source_id, peer_id


def overview_pair_style(
    speeds: SpeedIndex,
    link_type: str,
    source_id: str,
    peer_id: str,
    speed_direction: str | None,
) -> tuple[str, str]:
    pair = speeds.pair(link_type, source_id, peer_id)
    if speed_direction is None:
        return pair_color(pair), pair.tooltip()

    metric, metric_source, metric_peer = overview_directed_metric(
        speeds, link_type, source_id, peer_id, speed_direction
    )
    return metric_color(metric), directed_tooltip(
        metric_source, metric_peer, link_type, metric
    )


def add_overview_ring_links(
    out: list[str],
    names: list[str],
    node_kind: str,
    link_type: str,
    pos: dict[str, tuple[int, int]],
    width: int,
    wrap_side: str,
    speeds: SpeedIndex,
    speed_direction: str | None = None,
    outer_wrap: tuple[float, float, float] | None = None,
    stroke_override: str | None = None,
) -> None:
    ordered = [name for name in names if name in pos]
    if len(ordered) < 2:
        return

    def pair_render_data(left: str, right: str) -> tuple[str, str, bool, str, str]:
        left_id = node_id(node_kind, left)
        right_id = node_id(node_kind, right)
        if speed_direction is None:
            color, tooltip = overview_pair_style(
                speeds, link_type, left_id, right_id, None
            )
            source_name = left
            target_name = right
            arrows = False
        else:
            metric, metric_source, metric_peer = overview_directed_metric(
                speeds, link_type, left_id, right_id, speed_direction
            )
            color = metric_color(metric)
            tooltip = directed_tooltip(metric_source, metric_peer, link_type, metric)
            source_name = left if metric_source == left_id else right
            target_name = right if metric_peer == right_id else left
            arrows = True
        if stroke_override is not None:
            color = stroke_override
        return color, tooltip, arrows, source_name, target_name

    def draw_pair(left: str, right: str) -> None:
        color, tooltip, arrows, source_name, target_name = pair_render_data(left, right)
        add_overview_pair_link(
            out,
            pos,
            left,
            right,
            color,
            tooltip,
            "topology-ring-link",
            arrows=arrows,
            source=source_name,
            target=target_name,
        )

    def draw_connected_wrap_stubs(first: str, last: str) -> None:
        # Ring groups with three or more nodes are closed by an outer
        # P-shaped connector.  For the top rows it is drawn above the row; for
        # bottom rows it is drawn below.  Two-node groups are intentionally
        # shown as a single normal link, not as a two-node ring.
        color, tooltip, arrows, source_name, target_name = pair_render_data(first, last)
        points = overview_ring_wrap_points(
            pos,
            first,
            last,
            source_name,
            target_name,
            wrap_side,
            outer_wrap,
        )
        path_d = " ".join(
            ("M" if index == 0 else "L") + f" {x:.1f} {y:.1f}"
            for index, (x, y) in enumerate(points)
        )

        marker = f' marker-end="url(#{marker_id_for_color(color)})"' if arrows else ""
        out.append(f"<g><title>{esc(tooltip)}</title>")
        out.append(
            f'<path class="topology-ring-link" d="{path_d}" '
            f'stroke="{color}"{marker}/>'
        )
        out.append("</g>")

    if len(ordered) == 2:
        draw_pair(ordered[0], ordered[1])
        return

    for idx in range(len(ordered) - 1):
        draw_pair(ordered[idx], ordered[idx + 1])

    # Close only real rings with three or more nodes.  This applies both to the
    # spine mesh ring and to the public-exit ring.  Reverse exits are filtered
    # by the caller and never participate in the exit ring.
    draw_connected_wrap_stubs(ordered[0], ordered[-1])


def overview_ring_wrap_envelope(
    names: list[str],
    pos: dict[str, tuple[int, int]],
    wrap_side: str,
    x_extra: float = 0.0,
    y_extra: float = 0.0,
) -> tuple[float, float, float] | None:
    ordered = [name for name in names if name in pos]
    if len(ordered) < 3:
        return None

    fx, fy = pos[ordered[0]]
    lx, _ = pos[ordered[-1]]
    direction = -1 if wrap_side == "top" else 1
    stub = 28
    pad = 56

    left_outer_x = fx - NODE_R - stub - x_extra
    right_outer_x = lx + NODE_R + stub + x_extra
    wrap_y = fy + direction * (pad + y_extra)
    return left_outer_x, right_outer_x, wrap_y
