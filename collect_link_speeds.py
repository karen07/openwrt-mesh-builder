#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import json
import shlex
import time
from pathlib import Path

from tools.config_io import load_json_config
from tools.process import die, eprint
from tools.remote_exec import run_captured_remote
from tools.common import build_config_data
from tools.default import CONFIG_PATH, IPERF_BITRATE, IPERF_TIME_SEC, SSH_TIMEOUT
from tools.file_ops import write_text_output
from tools.link_speed_model import (
    IperfTarget,
    LinkSpeedRow,
    NodeRef,
    format_table,
    format_tsv,
    row_from_target,
    sort_rows,
    source_nodes,
    speed_rows_payload,
    targets_for_source,
)
from tools.topology_index import GeneratedTopologyIndex, load_generated_topology_index


def shell_printf_targets(targets: list[IperfTarget]) -> str:
    if not targets:
        return ":"

    args: list[str] = []
    for target in targets:
        args.append(shlex.quote(target.label))
        args.append(shlex.quote(target.peer_ip))

    return f"printf '%s %s\n' {' '.join(args)}"


def build_iperf_command(
    targets: list[IperfTarget],
    iperf_time: int,
    iperf_bitrate: str,
) -> str:
    explicit_targets_cmd = shell_printf_targets(targets)
    bitrate_line = f'        -b "{iperf_bitrate}" \\\n' if iperf_bitrate else ""

    return rf"""
targets="$({explicit_targets_cmd})"
[ -n "$targets" ] || exit 0

printf '%s\n' "$targets" \
  | sort -u \
  | while read -r label ip; do
      [ -n "$label" ] || continue
      [ -n "$ip" ] || continue

      if ! command -v iperf3 >/dev/null 2>&1; then
          printf '%s %s 0 iperf-missing\n' "$label" "$ip"
          continue
      fi

      if ! command -v jq >/dev/null 2>&1; then
          printf '%s %s 0 jq-missing\n' "$label" "$ip"
          continue
      fi

      json=$(iperf3 -c "$ip" \
        --connect-timeout 1000 \
{bitrate_line}        -t {iperf_time} -J 2>/dev/null)
      iperf_rc=$?

      bps=$(printf '%s' "$json" | jq -r '
        try (
          .end.sum_received.bits_per_second
          // .end.sum_sent.bits_per_second
          // .end.sum.bits_per_second
          // 0
        ) catch 0
      ' 2>/dev/null)

      [ -n "$bps" ] || bps=0
      [ "$bps" != "null" ] || bps=0

      if [ "$iperf_rc" -ne 0 ]; then
          status="iperf-fail"
      elif [ "$bps" = "0" ] || [ "$bps" = "0.0" ]; then
          status="down"
      else
          status="up"
      fi

      printf '%s %s %s %s\n' "$label" "$ip" "$bps" "$status"
    done
"""


def collect_source_speeds(
    source: NodeRef,
    targets: list[IperfTarget],
    *,
    ssh_timeout: int,
    iperf_time: int,
    iperf_bitrate: str,
    verbose: bool,
    config_path: str | Path = CONFIG_PATH,
) -> list[LinkSpeedRow]:
    by_key = {(target.label, target.peer_ip): target for target in targets}

    if not targets:
        return []

    cmd = build_iperf_command(targets, iperf_time, iperf_bitrate)
    per_target_budget_sec = max(iperf_time + 2, 3)
    command_timeout = max(
        ssh_timeout,
        len(targets) * per_target_budget_sec + ssh_timeout + 5,
    )

    remote = run_captured_remote(
        f"{source.kind}:{source.name}",
        source.ssh_hosts,
        cmd,
        command_timeout=command_timeout,
        config_path=config_path,
    )
    used_host = remote.host

    if not remote.ok:
        if verbose:
            eprint(
                f"{source.kind} {source.name} "
                f"({'/'.join(source.ssh_hosts)}) IPERF_FAIL "
                f"{remote.error_text()}"
            )
        return [
            row_from_target(
                source,
                target,
                source_ssh=used_host,
                status="ssh-fail",
            )
            for target in targets
        ]

    out = remote.out

    seen: set[tuple[str, str]] = set()
    rows: list[LinkSpeedRow] = []

    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) not in (3, 4):
            continue
        label, peer_ip, bps_s = parts[:3]
        remote_status = parts[3] if len(parts) == 4 else ""
        target = by_key.get((label, peer_ip))
        if target is None:
            continue
        seen.add((label, peer_ip))
        try:
            bps = float(bps_s)
        except ValueError:
            bps = 0.0
        mbps = bps / 1_000_000.0
        rows.append(
            row_from_target(
                source,
                target,
                source_ssh=used_host,
                mbps=mbps,
                status=remote_status or ("up" if mbps > 0 else "down"),
            )
        )

    for key, target in sorted(by_key.items()):
        if key in seen:
            continue
        rows.append(
            row_from_target(
                source,
                target,
                source_ssh=used_host,
                status="missing",
            )
        )

    return sorted(rows, key=lambda r: (r.link_type, r.peer_kind, r.peer, r.iface))


def write_optional(path: str | None, text: str) -> None:
    if path:
        write_text_output(Path(path), text + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(
        description=(
            "Collect directed iperf3 speeds for router-router, "
            "router-exit, and exit-exit links"
        )
    )
    ap.add_argument("--config", default=str(CONFIG_PATH))
    ap.add_argument("--ssh-timeout", type=int, default=SSH_TIMEOUT)
    ap.add_argument("--iperf-time", type=int, default=IPERF_TIME_SEC)
    ap.add_argument("--iperf-bitrate", default=IPERF_BITRATE)
    ap.add_argument("--format", choices=("table", "tsv", "json"), default="table")
    ap.add_argument("--out", help="optional output file in the selected format")
    ap.add_argument(
        "--json-out",
        help="optional JSON output file, useful for later SVG rendering",
    )
    ap.add_argument(
        "--list-targets",
        action="store_true",
        help="print target matrix without running iperf3",
    )
    ap.add_argument(
        "--topology-source",
        choices=("generated", "config"),
        default="generated",
        help=(
            "generated: measure only links that exist in generated AWG/UCI files; "
            "config: measure planned topology from config.json"
        ),
    )
    ap.add_argument(
        "--server-ssh-mode",
        choices=("auto", "node", "public"),
        default="auto",
        help=(
            "server SSH alias mode for server-side measurements: auto tries "
            "server_<name>_node first then server_<name>; node/public force one alias"
        ),
    )
    ap.add_argument("--progress", action="store_true")
    ap.add_argument("--verbose", action="store_true")

    args = ap.parse_args()

    if args.iperf_time <= 0:
        die("--iperf-time must be positive")

    cfg = build_config_data(load_json_config(Path(args.config)))

    generated: GeneratedTopologyIndex | None = None
    if args.topology_source == "generated":
        generated = load_generated_topology_index(cfg)
        for warning in generated.warnings:
            eprint(f"topology warning: {warning}")

    sources = source_nodes(cfg, args.server_ssh_mode)
    all_rows: list[LinkSpeedRow] = []

    for idx, source in enumerate(sources, start=1):
        targets = targets_for_source(
            cfg,
            source,
            topology_source=args.topology_source,
            generated=generated,
        )
        if args.progress:
            eprint(
                f"[{idx}/{len(sources)}] "
                f"{source.kind}:{source.name} "
                f"ssh={'/'.join(source.ssh_hosts)} targets={len(targets)}"
            )

        if args.list_targets:
            all_rows.extend(
                row_from_target(
                    source,
                    target,
                    source_ssh="/".join(source.ssh_hosts),
                )
                for target in targets
            )
            continue

        all_rows.extend(
            collect_source_speeds(
                source,
                targets,
                ssh_timeout=args.ssh_timeout,
                iperf_time=args.iperf_time,
                iperf_bitrate=args.iperf_bitrate,
                verbose=args.verbose,
                config_path=args.config,
            )
        )

    if args.topology_source == "generated" and not all_rows:
        die(
            "no generated AWG links found; run generate_configs.py first "
            "or use --topology-source config"
        )

    all_rows = sort_rows(all_rows)
    payload = speed_rows_payload(
        all_rows,
        generated_at=int(time.time()),
        iperf_time=args.iperf_time,
        iperf_bitrate=args.iperf_bitrate,
        topology_source=args.topology_source,
        server_ssh_mode=args.server_ssh_mode,
    )
    json_text = json.dumps(payload, ensure_ascii=False, indent=2)

    if args.format == "json":
        text = json_text
    elif args.format == "tsv":
        text = format_tsv(all_rows)
    else:
        text = format_table(all_rows)

    print(text)
    write_optional(args.out, text)
    write_optional(args.json_out, json_text)


if __name__ == "__main__":
    main()
