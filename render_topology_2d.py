#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

from tools.common import ConfigData, build_config_data
from tools.config_io import load_json_config
from tools.layout import topology_2d_path, topology_2d_svg_path
from tools.process import die
from tools.topology_2d_layout import build_topology_2d_layout
from tools.topology_2d_page import html_page
from tools.topology_3d_graph import graph_from_rows
from tools.topology_cli import (
    add_output_arg,
    add_topology_input_args,
    resolved_output_path,
    write_topology_output,
)
from tools.topology_data import (
    SpeedIndex,
    SpeedRow,
    TopologyRoles,
    config_roles,
    format_ts,
    infer_roles_from_rows,
    load_config_roles,
    load_speed_rows,
    node_names_from_rows,
    topology_rows_from_config,
    topology_rows_from_generated,
)
from tools.topology_svg import render_topology_overview_svg


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(
        description="Render interactive 2D canvas HTML and topology SVG"
    )
    add_topology_input_args(ap)
    add_output_arg(ap, help_text="output HTML path")
    ap.add_argument(
        "--svg-out",
        default=None,
        help="output topology-only SVG path",
    )
    ap.add_argument(
        "--only",
        choices=("all", "topology", "from", "to"),
        default="all",
        help=(
            "initial HTML color mode; 'all' keeps all interactive modes and "
            "starts with from"
        ),
    )
    # Deprecated compatibility switches retained for old command lines.
    ap.add_argument(
        "--degraded-mbps",
        type=float,
        default=1.0,
        help=argparse.SUPPRESS,
    )
    ap.add_argument(
        "--main-label-mode",
        choices=("none", "problems", "all"),
        default="none",
        help=argparse.SUPPRESS,
    )
    args = ap.parse_args(raw_argv)

    if args.topology_only and args.only in {"from", "to"}:
        die(f"--only {args.only} requires measured --speeds-json data")
    if args.degraded_mbps < 0:
        die("--degraded-mbps must be non-negative")
    return args


def measured_roles(
    config_path: Path,
    cfg: ConfigData | None,
    rows: list[SpeedRow],
) -> TopologyRoles:
    row_roles = infer_roles_from_rows(rows)
    if cfg is None:
        return row_roles

    cfg_roles = config_roles(cfg)
    cfg_names = set(cfg_roles.routers + cfg_roles.exits)
    row_routers, row_exits = node_names_from_rows(rows)
    row_names = row_routers | row_exits

    # Do not mix an unrelated default/sample config into imported measurements.
    if row_names and not (row_names & cfg_names):
        return row_roles
    return load_config_roles(config_path, rows) or row_roles


def load_render_data(
    args: argparse.Namespace,
) -> tuple[dict[str, object], TopologyRoles, SpeedIndex, str, bool]:
    config_path = Path(args.config)
    cfg: ConfigData | None = None
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
        roles = config_roles(cfg)
        generated_text = source_text
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
        generated_text = format_ts(generated_at)
        if iperf_time:
            generated_text = f"{generated_text}, iperf_time={iperf_time}s"
        roles = measured_roles(config_path, cfg, rows)
        topology_only = False

    data = graph_from_rows(
        rows=rows,
        cfg=cfg,
        title=args.title,
        topology_only=topology_only,
        source_text=source_text,
    )
    return data, roles, SpeedIndex(rows), generated_text, topology_only


def resolved_svg_output(args: argparse.Namespace, html_out: Path) -> Path:
    if args.svg_out is not None:
        return Path(args.svg_out)
    if args.out is not None:
        return html_out.with_suffix(".svg")
    return topology_2d_svg_path()


def main() -> None:
    args = parse_args()
    data, roles, speeds, generated_text, topology_only = load_render_data(args)
    if data["topology_only"]:
        data["initial_mode"] = "topology"
    elif args.only in {"topology", "from", "to"}:
        data["initial_mode"] = args.only
    else:
        data["initial_mode"] = "from"

    data["layout_2d"] = build_topology_2d_layout(data)
    html_out = resolved_output_path(args.out, topology_2d_path())
    svg_out = resolved_svg_output(args, html_out)

    write_topology_output(html_out, html_page(data))
    write_topology_output(
        svg_out,
        render_topology_overview_svg(
            roles,
            speeds,
            args.title,
            generated_text,
            topology_only,
            "topology",
        ),
    )
    print(html_out)
    print(svg_out)


if __name__ == "__main__":
    main()
