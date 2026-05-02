#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse

from tools.layout import topology_3d_html_path
from tools.topology_cli import (
    add_output_arg,
    add_topology_input_args,
    resolved_output_path,
    write_topology_output,
)
from tools.topology_3d_graph import load_graph_data
from tools.topology_3d_page import html_page

DEFAULT_THREE_URL = "https://unpkg.com/three@0.160.0/build/three.module.js"
DEFAULT_ORBIT_URL = (
    "https://unpkg.com/three@0.160.0/examples/jsm/controls/OrbitControls.js"
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Render topology as interactive Three.js HTML"
    )
    add_topology_input_args(ap)
    add_output_arg(ap, help_text="output HTML path")
    ap.add_argument("--three-url", default=DEFAULT_THREE_URL)
    ap.add_argument("--orbit-url", default=DEFAULT_ORBIT_URL)
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    data = load_graph_data(args)
    out = resolved_output_path(args.out, topology_3d_html_path())
    write_topology_output(out, html_page(data, args.three_url, args.orbit_url))
    print(out)


if __name__ == "__main__":
    main()
