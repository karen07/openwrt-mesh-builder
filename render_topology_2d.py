#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
from pathlib import Path

from tools.config_io import load_json_config
from tools.process import die
from tools.common import ConfigData, build_config_data
from tools.layout import topology_2d_path
from tools.topology_cli import (
    add_output_arg,
    add_topology_input_args,
    resolved_output_path,
    write_topology_output,
)
from tools.topology_svg import SvgFile, render_topology_overview_svg
from tools.topology_data import (
    SpeedIndex,
    config_roles,
    format_ts,
    infer_roles_from_rows,
    load_config_roles,
    load_speed_rows,
    topology_rows_from_config,
    topology_rows_from_generated,
)


def output_paths(out_path: Path) -> dict[str, Path]:
    return {
        "topology": out_path.with_name(f"{out_path.stem}_topology{out_path.suffix}"),
        "from": out_path.with_name(f"{out_path.stem}_from{out_path.suffix}"),
        "to": out_path.with_name(f"{out_path.stem}_to{out_path.suffix}"),
    }


def build_svgs(args: argparse.Namespace) -> list[SvgFile]:
    if args.topology_only:
        raw_cfg = load_json_config(Path(args.config))
        cfg: ConfigData = build_config_data(raw_cfg)
        roles = config_roles(cfg)
        if args.topology_source == "config":
            rows = topology_rows_from_config(cfg)
            generated_text = "config topology only"
        else:
            rows, warnings = topology_rows_from_generated(cfg)
            for warning in warnings:
                print(f"topology warning: {warning}", file=sys.stderr)
            if not rows:
                die("no generated topology links found")
            generated_text = "generated AWG/UCI topology"
        topology_only_data = True
    else:
        rows, generated_at, iperf_time = load_speed_rows(Path(args.speeds_json))
        if not rows:
            die(f"{args.speeds_json}: no rows found")

        roles = load_config_roles(Path(args.config), rows) or infer_roles_from_rows(
            rows
        )
        generated_text = format_ts(generated_at)
        if iperf_time:
            generated_text = f"{generated_text}, iperf_time={iperf_time}s"
        topology_only_data = False

    speeds = SpeedIndex(rows)
    svgs: list[SvgFile] = []

    if args.topology_only or args.only == "topology":
        svgs.append(
            SvgFile(
                name="topology",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only_data,
                    "topology",
                ),
            )
        )

    if args.topology_only:
        return svgs

    svgs.extend(
        [
            SvgFile(
                name="from",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only_data,
                    "from",
                ),
            ),
            SvgFile(
                name="to",
                text=render_topology_overview_svg(
                    roles,
                    speeds,
                    args.title,
                    generated_text,
                    topology_only_data,
                    "to",
                ),
            ),
        ]
    )
    return svgs


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Render measured or configured topology SVGs"
    )
    add_topology_input_args(ap)
    add_output_arg(ap, help_text="output SVG path")
    ap.add_argument(
        "--only",
        choices=("all", "topology", "from", "to"),
        default="all",
        help="which SVG to write",
    )
    ap.add_argument(
        "--degraded-mbps",
        type=float,
        default=1.0,
        help="positive speed below this value is treated as degraded",
    )
    ap.add_argument(
        "--main-label-mode",
        choices=("none", "problems", "all"),
        default="none",
        help="speed labels on topology_2d_from/to SVGs",
    )

    args = ap.parse_args()

    if args.degraded_mbps < 0:
        die("--degraded-mbps must be non-negative")

    svgs = build_svgs(args)
    out_path = resolved_output_path(args.out, topology_2d_path())
    paths = output_paths(out_path)

    for svg in svgs:
        if args.only != "all" and args.only != svg.name:
            continue
        if args.topology_only:
            path = out_path
        else:
            path = paths[svg.name]
        write_topology_output(path, svg.text)
        print(path)


if __name__ == "__main__":
    main()
