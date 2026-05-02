#!/usr/bin/env python3
import html
import math
import textwrap
from dataclasses import dataclass

from .default import SPEED_MAX_MBPS, SPEED_MIN_MBPS, TOPOLOGY_NODE_R as NODE_R
from .topology_data import DirectedMetric, PairMetric

from .topology_svg_colors import (
    LINK_GROUP_COLORS,
    MAGMA_COLORMAP,
    NO_SPEED_COLOR,
    TOPOLOGY_COLOR,
)


@dataclass(frozen=True)
class SvgFile:
    name: str
    text: str


def esc(value: str) -> str:
    return html.escape(value, quote=True)


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def speed_to_color(mbps: float) -> str:
    if SPEED_MAX_MBPS <= SPEED_MIN_MBPS:
        t = 1.0
    else:
        lo = math.log10(max(SPEED_MIN_MBPS, 0.001))
        hi = math.log10(max(SPEED_MAX_MBPS, SPEED_MIN_MBPS))
        value = math.log10(max(SPEED_MIN_MBPS, mbps))
        t = clamp01((value - lo) / (hi - lo))
    idx = round(t * (len(MAGMA_COLORMAP) - 1))
    return MAGMA_COLORMAP[idx]


def metric_color(metric: DirectedMetric | None) -> str:
    if metric is not None and metric.is_target:
        return TOPOLOGY_COLOR
    if metric is None or not metric.is_up:
        return NO_SPEED_COLOR
    return speed_to_color(metric.mbps)


def pair_color(pair: PairMetric) -> str:
    if any(m and m.is_target for m in (pair.a_to_b, pair.b_to_a)):
        return TOPOLOGY_COLOR
    if pair.up_count == 0:
        return NO_SPEED_COLOR
    return speed_to_color(pair.min_up_mbps or pair.best_mbps)


def topology_link_color(group: str, topology_only: bool) -> str | None:
    if not topology_only:
        return None
    return LINK_GROUP_COLORS[group]


def marker_id_for_color(color: str) -> str:
    return f"arrow-{color[1:]}"


def add_defs(out: list[str]) -> None:
    colors = [
        NO_SPEED_COLOR,
        TOPOLOGY_COLOR,
        *LINK_GROUP_COLORS.values(),
    ] + MAGMA_COLORMAP
    out.append("<defs>")
    seen: set[str] = set()
    for color in colors:
        if color in seen:
            continue
        seen.add(color)
        marker_id = marker_id_for_color(color)
        out.append(
            f'<marker id="{marker_id}" markerWidth="8" markerHeight="8" '
            f'refX="7" refY="4" orient="auto" markerUnits="strokeWidth">'
            f'<path d="M 0 0 L 8 4 L 0 8 z" fill="{color}"/>'
            f"</marker>"
        )
    out.append('<linearGradient id="speed-scale" x1="0%" y1="0%" x2="100%" y2="0%">')
    last = len(MAGMA_COLORMAP) - 1
    for i, color in enumerate(MAGMA_COLORMAP):
        offset = 0 if last <= 0 else round(100.0 * i / last, 2)
        out.append(f'<stop offset="{offset}%" stop-color="{color}"/>')
    out.append("</linearGradient>")
    out.append("</defs>")


def add_style(out: list[str]) -> None:
    out.append("""
<style>
  text {
    font-family: Arial, sans-serif;
    fill: #111827;
  }
  .title {
    font-size: 22px;
    font-weight: 700;
    text-anchor: middle;
  }
  .subtitle {
    font-size: 12px;
    fill: #4b5563;
    text-anchor: middle;
  }
  .node {
    fill: #f8fafc;
    stroke: #111827;
    stroke-width: 1.6;
  }
  .spine-node {
    fill: #dbeafe;
    stroke: #2563eb;
  }
  .leaf-node {
    fill: #dcfce7;
    stroke: #16a34a;
  }
  .exit-node {
    fill: #ffedd5;
    stroke: #ea580c;
  }
  .node-label {
    font-size: 11px;
    font-weight: 700;
    fill: #0f172a;
    text-anchor: middle;
    dominant-baseline: middle;
  }
  .row-label {
    font-size: 12px;
    fill: #374151;
    font-weight: 700;
    text-anchor: start;
  }
  .link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 2.1;
    opacity: 0.95;
  }
  .topology-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-primary-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-ring-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 1.9;
    opacity: 0.78;
  }
  .topology-reverse-link {
  }
  .spine-link {
    fill: none;
    stroke-linecap: round;
    stroke-width: 2.2;
    opacity: 0.9;
  }
  .exit-link {
    stroke-width: 1.8;
    opacity: 0.95;
  }
  .edge-label {
    font-size: 10px;
    font-weight: 700;
    text-anchor: middle;
    paint-order: stroke;
    stroke: white;
    stroke-width: 3px;
  }
  .legend {
    font-size: 11px;
    fill: #4b5563;
  }
  .scale-label {
    font-size: 10px;
    font-weight: 700;
    fill: #374151;
  }
</style>
""")


def wrap_svg_subtitle(text: str, width: int) -> list[str]:
    # Keep long subtitles inside the SVG viewport.  SVG text does not wrap by
    # itself, so use a conservative character-width estimate for 12px Arial.
    max_chars = max(70, (width - 120) // 7)
    return textwrap.wrap(
        text,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )


def start_svg(width: int, height: int, title: str, subtitle: str) -> list[str]:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    add_defs(out)
    add_style(out)
    out.append(f'<text x="{width // 2}" y="30" class="title">{esc(title)}</text>')

    subtitle_lines = wrap_svg_subtitle(subtitle, width)
    if subtitle_lines:
        out.append(f'<text x="{width // 2}" y="52" class="subtitle">')
        for idx, line in enumerate(subtitle_lines):
            dy = 0 if idx == 0 else 14
            out.append(f'<tspan x="{width // 2}" dy="{dy}">{esc(line)}</tspan>')
        out.append("</text>")

    return out


def add_node(
    out: list[str], x: int, y: int, label: str, class_name: str, title: str = ""
) -> None:
    out.append(f'<g>{f"<title>{esc(title)}</title>" if title else ""}')
    out.append(f'<circle class="node {class_name}" cx="{x}" cy="{y}" r="{NODE_R}"/>')
    out.append(f'<text class="node-label" x="{x}" y="{y}">{esc(label)}</text>')
    out.append("</g>")


def log_speed_pos(mbps: float, x: int, width: int) -> float:
    if SPEED_MAX_MBPS <= SPEED_MIN_MBPS:
        return float(x + width)
    lo = math.log10(max(SPEED_MIN_MBPS, 0.001))
    hi = math.log10(max(SPEED_MAX_MBPS, SPEED_MIN_MBPS))
    value = math.log10(max(SPEED_MIN_MBPS, mbps))
    return x + width * clamp01((value - lo) / (hi - lo))


def add_speed_legend(out: list[str], width: int, y: int = 106) -> None:
    bar_w = 220
    bar_h = 12
    x = width - bar_w - 35
    ticks = [
        (SPEED_MIN_MBPS, f"{SPEED_MIN_MBPS:.0f} M", "start"),
        (20.0, "20 M", "middle"),
        (100.0, "100 M", "middle"),
        (SPEED_MAX_MBPS, f"{SPEED_MAX_MBPS:.0f} M", "end"),
    ]
    out.append(
        f'<text x="{x + bar_w}" y="{y - 8}" class="scale-label" text-anchor="end">'
        f"Magma log scale: dark=slow, bright=fast</text>"
    )
    out.append(
        f'<rect x="{x}" y="{y}" width="{bar_w}" height="{bar_h}" '
        f'fill="url(#speed-scale)" stroke="#111827" stroke-width="0.6" rx="3"/>'
    )
    for mbps, label, anchor in ticks:
        tx = log_speed_pos(mbps, x, bar_w)
        out.append(
            f'<line x1="{tx:.1f}" y1="{y + bar_h}" x2="{tx:.1f}" '
            f'y2="{y + bar_h + 4}" stroke="#111827" stroke-width="0.6"/>'
        )
        out.append(
            f'<text x="{tx:.1f}" y="{y + 30}" class="scale-label" '
            f'text-anchor="{anchor}">{label}</text>'
        )


def add_topology_link_legend(out: list[str], x: int, y: int) -> None:
    items = [
        ("spine-spine", "spine-spine"),
        ("leaf-spine", "leaf-spine"),
        ("exit-exit", "exit-exit"),
        ("spine-exit", "spine-exit"),
        ("exit-spine", "exit-spine"),
        ("leaf-exit", "leaf-exit"),
    ]
    col_w = 145
    row_h = 18
    for idx, (group, text) in enumerate(items):
        col = idx % 3
        row = idx // 3
        xx = x + col * col_w
        yy = y + row * row_h
        color = LINK_GROUP_COLORS[group]
        out.append(
            f'<line x1="{xx}" y1="{yy}" x2="{xx + 26}" y2="{yy}" '
            f'stroke="{color}" stroke-width="3"/>'
        )
        out.append(
            f'<text x="{xx + 34}" y="{yy + 4}" class="legend">' f"{esc(text)}</text>"
        )


def finish_svg(out: list[str]) -> str:
    out.append("</svg>")
    out.append("")
    return "\n".join(out)
