#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import argparse
import asyncio
import json
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from tools.config_io import load_json_config
from tools.process import die, eprint
from tools.remote_exec import CapturedRemoteResult, ssh_config_args
from tools.common import ConfigData, build_config_data
from tools.default import (
    CONFIG_PATH,
    IPERF_BITRATE,
    IPERF_TIME_SEC,
    LINK_SPEEDS_JSON_PATH,
    LINK_SPEEDS_TEXT_PATH,
    SSH_COMMAND_TIMEOUT_GRACE_SEC,
    SSH_TIMEOUT,
)
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

NodeKey = tuple[str, str]


@dataclass(frozen=True)
class MeasurementTask:
    source: NodeRef
    target: IperfTarget

    @property
    def endpoints(self) -> frozenset[NodeKey]:
        return frozenset(
            (
                (self.source.kind, self.source.name),
                (self.target.peer_kind, self.target.peer_name),
            )
        )

    @property
    def label(self) -> str:
        return (
            f"{self.source.kind}:{self.source.name} -> "
            f"{self.target.peer_kind}:{self.target.peer_name} "
            f"({self.target.link_type})"
        )


def positive_jobs(raw_value: str) -> int:
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def default_jobs(tasks: list[MeasurementTask]) -> int:
    nodes: set[NodeKey] = set()
    for task in tasks:
        nodes.update(task.endpoints)
    return max(1, len(nodes) // 2)


def build_measurement_tasks(
    cfg: ConfigData,
    sources: list[NodeRef],
    *,
    topology_source: str,
    generated: GeneratedTopologyIndex | None,
) -> list[MeasurementTask]:
    tasks: list[MeasurementTask] = []
    for source in sources:
        targets = targets_for_source(
            cfg,
            source,
            topology_source=topology_source,
            generated=generated,
        )
        tasks.extend(MeasurementTask(source, target) for target in targets)
    return tasks


def pop_schedulable_task(
    pending: list[MeasurementTask],
    busy_nodes: set[NodeKey],
) -> MeasurementTask | None:
    for idx, task in enumerate(pending):
        if task.endpoints.isdisjoint(busy_nodes):
            return pending.pop(idx)
    return None


def progress_result_text(rows: list[LinkSpeedRow]) -> str:
    if not rows:
        return "no-result"
    row = rows[0]
    if row.status == "up":
        return f"{row.mbps:.1f} Mbps"
    return row.status


async def run_ssh_async(
    host: str,
    command: str,
    *,
    ssh_timeout: int,
    config_path: str | Path,
) -> tuple[int, str, str]:
    argv = [
        "ssh",
        *ssh_config_args(config_path),
        "-o",
        f"ConnectTimeout={ssh_timeout}",
        "-o",
        "BatchMode=yes",
        host,
        command,
    ]
    process_timeout = ssh_timeout + SSH_COMMAND_TIMEOUT_GRACE_SEC

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=process_timeout,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return (
                1,
                "",
                f"ssh to {host} timed out after {process_timeout} seconds",
            )
    except Exception as exc:
        return 1, "", str(exc)

    return (
        process.returncode or 0,
        stdout.decode(errors="replace"),
        stderr.decode(errors="replace"),
    )


async def run_captured_remote_async(
    label: str,
    hosts: tuple[str, ...] | list[str],
    command: str,
    *,
    ssh_timeout: int = SSH_TIMEOUT,
    command_timeout: int | None = None,
    config_path: str | Path = CONFIG_PATH,
) -> CapturedRemoteResult:
    host_tuple = tuple(hosts)
    if not host_tuple:
        raise ValueError(f"{label}: empty SSH host list")

    timeout = command_timeout if command_timeout is not None else ssh_timeout
    last_host = host_tuple[-1]
    last_rc = 1
    last_out = ""
    last_err = "no SSH hosts tried"

    for host in host_tuple:
        rc, out, err = await run_ssh_async(
            host,
            command,
            ssh_timeout=timeout,
            config_path=config_path,
        )
        if rc == 0:
            return CapturedRemoteResult(label, host_tuple, host, rc, out, err)
        last_host, last_rc, last_out, last_err = host, rc, out, err

    return CapturedRemoteResult(
        label,
        host_tuple,
        last_host,
        last_rc,
        last_out,
        last_err,
    )


async def collect_speeds_async(
    tasks: list[MeasurementTask],
    *,
    jobs: int,
    ssh_timeout: int,
    iperf_time: int,
    iperf_bitrate: str,
    verbose: bool,
    progress: bool,
    config_path: str | Path = CONFIG_PATH,
) -> list[LinkSpeedRow]:
    if not tasks:
        return []

    task_limit = min(jobs, len(tasks))
    pending = list(tasks)
    running: dict[
        asyncio.Task[list[LinkSpeedRow]],
        tuple[MeasurementTask, frozenset[NodeKey]],
    ] = {}
    busy_nodes: set[NodeKey] = set()
    all_rows: list[LinkSpeedRow] = []
    completed = 0

    if progress:
        print(
            f"measurements={len(tasks)} jobs={task_limit} "
            "conflict-policy=no-shared-node scheduler=asyncio",
            flush=True,
        )

    while pending or running:
        while len(running) < task_limit:
            task = pop_schedulable_task(pending, busy_nodes)
            if task is None:
                break

            endpoints = task.endpoints
            busy_nodes.update(endpoints)
            async_task = asyncio.create_task(
                collect_source_speeds(
                    task.source,
                    [task.target],
                    ssh_timeout=ssh_timeout,
                    iperf_time=iperf_time,
                    iperf_bitrate=iperf_bitrate,
                    verbose=verbose,
                    config_path=config_path,
                )
            )
            running[async_task] = (task, endpoints)

        if not running:
            raise RuntimeError(
                "measurement scheduler stalled with pending work and no active task"
            )

        done, _ = await asyncio.wait(
            running,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for async_task in done:
            task, endpoints = running.pop(async_task)
            busy_nodes.difference_update(endpoints)
            rows = await async_task
            all_rows.extend(rows)
            completed += 1

            if progress:
                print(
                    f"[{completed}/{len(tasks)}] {task.label}: "
                    f"{progress_result_text(rows)}",
                    flush=True,
                )

    return all_rows


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


async def collect_source_speeds(
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

    remote = await run_captured_remote_async(
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
    ap.add_argument(
        "--out",
        help=(
            "write the report in the selected format to this file "
            f"(default for measurements: {LINK_SPEEDS_TEXT_PATH})"
        ),
    )
    ap.add_argument(
        "--json-out",
        help=(
            "write JSON output for topology rendering "
            f"(default for measurements: {LINK_SPEEDS_JSON_PATH})"
        ),
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
    ap.add_argument(
        "-j",
        "--jobs",
        type=positive_jobs,
        default=None,
        help=(
            "maximum simultaneous measurements; active measurements never share "
            "a router/server endpoint (default: half the number of topology nodes)"
        ),
    )
    ap.add_argument(
        "--progress",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show measurement progress (default: enabled; use --no-progress to disable)",
    )
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
    tasks = build_measurement_tasks(
        cfg,
        sources,
        topology_source=args.topology_source,
        generated=generated,
    )

    if args.list_targets:
        all_rows = [
            row_from_target(
                task.source,
                task.target,
                source_ssh="/".join(task.source.ssh_hosts),
            )
            for task in tasks
        ]
    else:
        jobs = args.jobs if args.jobs is not None else default_jobs(tasks)
        all_rows = asyncio.run(
            collect_speeds_async(
                tasks,
                jobs=jobs,
                ssh_timeout=args.ssh_timeout,
                iperf_time=args.iperf_time,
                iperf_bitrate=args.iperf_bitrate,
                verbose=args.verbose,
                progress=args.progress,
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

    out_path = args.out
    json_out_path = args.json_out
    if not args.list_targets:
        if out_path is None:
            out_path = str(LINK_SPEEDS_TEXT_PATH)
        if json_out_path is None:
            json_out_path = str(LINK_SPEEDS_JSON_PATH)

    if out_path:
        write_optional(out_path, text)
    else:
        print(text)
    write_optional(json_out_path, json_text)


if __name__ == "__main__":
    main()
