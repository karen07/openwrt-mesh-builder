from __future__ import annotations

import json
from json import JSONDecodeError
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from .process import die
except ImportError:
    from process import die  # type: ignore

STATUS_UP = "up"
STATUS_TARGET = "target"


@dataclass(frozen=True)
class SpeedRow:
    source_kind: str
    source: str
    link_type: str
    peer_kind: str
    peer: str
    iface: str
    peer_ip: str
    mbps: float
    status: str

    @property
    def source_id(self) -> str:
        return node_id(self.source_kind, self.source)

    @property
    def peer_id(self) -> str:
        return node_id(self.peer_kind, self.peer)


@dataclass(frozen=True)
class DirectedMetric:
    mbps: float
    status: str
    iface: str
    peer_ip: str

    @property
    def is_up(self) -> bool:
        return self.status == STATUS_UP and self.mbps > 0.0

    @property
    def is_target(self) -> bool:
        return self.status == STATUS_TARGET


@dataclass(frozen=True)
class PairMetric:
    a: str
    b: str
    link_type: str
    a_to_b: DirectedMetric | None
    b_to_a: DirectedMetric | None

    @property
    def best_mbps(self) -> float:
        values = [m.mbps for m in (self.a_to_b, self.b_to_a) if m]
        return max(values) if values else 0.0

    @property
    def min_up_mbps(self) -> float:
        values = [m.mbps for m in (self.a_to_b, self.b_to_a) if m and m.is_up]
        return min(values) if values else 0.0

    @property
    def up_count(self) -> int:
        return sum(1 for m in (self.a_to_b, self.b_to_a) if m and m.is_up)

    def tooltip(self) -> str:
        return "\n".join(
            [
                f"{self.a} -> {self.b}: {format_metric(self.a_to_b)}",
                f"{self.b} -> {self.a}: {format_metric(self.b_to_a)}",
            ]
        )


@dataclass(frozen=True)
class TopologyRoles:
    routers: list[str]
    spines: list[str]
    leafs: list[str]
    exits: list[str]
    public_exits: list[str]
    reverse_exits: list[str]


class SpeedIndex:
    def __init__(self, rows: list[SpeedRow]) -> None:
        self.rows = rows
        self._directed: dict[tuple[str, str, str], DirectedMetric] = {}
        self._load_best_directed(rows)

    def _load_best_directed(self, rows: list[SpeedRow]) -> None:
        for row in rows:
            key = (row.link_type, row.source_id, row.peer_id)
            metric = DirectedMetric(
                mbps=row.mbps,
                status=row.status,
                iface=row.iface,
                peer_ip=row.peer_ip,
            )
            old = self._directed.get(key)
            if old is None or metric_rank(metric) > metric_rank(old):
                self._directed[key] = metric

    def directed(
        self,
        link_type: str,
        source_id: str,
        peer_id: str,
    ) -> DirectedMetric | None:
        return self._directed.get((link_type, source_id, peer_id))

    def pair(self, link_type: str, a: str, b: str) -> PairMetric:
        return PairMetric(
            a=a,
            b=b,
            link_type=link_type,
            a_to_b=self.directed(link_type, a, b),
            b_to_a=self.directed(link_type, b, a),
        )


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{name}"


def parse_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def metric_rank(metric: DirectedMetric) -> tuple[int, float]:
    if metric.is_up:
        return (3, metric.mbps)
    if metric.status == "down":
        return (2, metric.mbps)
    if metric.status in {"iperf-fail", "ssh-fail", "missing", "jq-missing"}:
        return (1, metric.mbps)
    return (0, metric.mbps)


def display_link_text(value: str) -> str:
    return value.replace("\u2194", "<->").replace("\u2192", "->")


def format_metric(metric: DirectedMetric | None) -> str:
    if metric is None:
        return "missing"
    iface_text = display_link_text(metric.iface)
    return f"{metric.mbps:.1f} Mbit/s {metric.status} via {iface_text} {metric.peer_ip}"


def format_ts(ts: int | float | None) -> str:
    if not ts:
        return "unknown time"
    return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")


def load_speed_rows(path: Path) -> tuple[list[SpeedRow], int | None, int | None]:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        die(
            f"{path}: file not found; run ./collect_link_speeds.py --json-out {path} "
            "or use --topology-only"
        )
    except OSError as exc:
        die(f"{path}: cannot read file: {exc}")

    try:
        raw = json.loads(text)
    except JSONDecodeError as exc:
        die(f"{path}: invalid JSON: {exc}")

    if not isinstance(raw, dict):
        die(f"{path}: expected JSON object with rows list")

    rows_raw = raw.get("rows")
    if not isinstance(rows_raw, list):
        die(f"{path}: expected JSON object with rows list")

    rows: list[SpeedRow] = []
    for item in rows_raw:
        if not isinstance(item, dict):
            continue
        rows.append(
            SpeedRow(
                source_kind=str(item.get("source_kind", "")),
                source=str(item.get("source", "")),
                link_type=str(item.get("link_type", "")),
                peer_kind=str(item.get("peer_kind", "")),
                peer=str(item.get("peer", "")),
                iface=str(item.get("iface", "")),
                peer_ip=str(item.get("peer_ip", "")),
                mbps=parse_float(item.get("mbps", 0.0)),
                status=str(item.get("status", "")),
            )
        )

    generated_at = raw.get("generated_at")
    iperf_time = raw.get("iperf_time")
    return (
        rows,
        int(generated_at) if generated_at else None,
        int(iperf_time or 0) or None,
    )
