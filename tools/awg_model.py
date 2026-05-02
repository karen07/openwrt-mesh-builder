#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import random
import re

try:
    from .config_model import AwgOptions, PortRange
    from .default import (
        AWG_H_COUNT,
        AWG_H_GAP,
        AWG_H_MAX,
        AWG_H_MIN,
        AWG_H_SPAN_MAX,
        AWG_H_SPAN_MIN,
        AWG_INFRA_AUTO_JC_MAX,
        AWG_INFRA_AUTO_JC_MIN,
        AWG_INFRA_AUTO_JUNK_SIZE_MAX,
        AWG_INFRA_AUTO_JUNK_SIZE_MIN,
        AWG_INFRA_AUTO_S1_MAX,
        AWG_INFRA_AUTO_S1_MIN,
        AWG_INFRA_AUTO_S2_MAX,
        AWG_INFRA_AUTO_S2_MIN,
        AWG_INFRA_AUTO_S3_MAX,
        AWG_INFRA_AUTO_S3_MIN,
        AWG_INFRA_AUTO_S4_MAX,
        AWG_INFRA_AUTO_S4_MIN,
        AWG_INFRA_I1,
        AWG_INFRA_I2,
        AWG_INFRA_I3,
        AWG_INFRA_I4,
        AWG_INFRA_I5,
        AWG_JC_MAX,
        AWG_JC_MIN,
        AWG_JUNK_SIZE_MAX,
        AWG_JUNK_SIZE_MIN,
        AWG_S1_MAX,
        AWG_S1_MIN,
        AWG_S2_MAX,
        AWG_S2_MIN,
        AWG_S3_MAX,
        AWG_S3_MIN,
        AWG_S4_MAX,
        AWG_S4_MIN,
        INFRA_AWG_PORT_RANGE,
        PORT_MAX,
        PORT_MIN,
    )
    from .process import die
    from .stable_model import random_free_slots, stable_seed_u64
except ImportError:
    from config_model import AwgOptions, PortRange  # type: ignore
    from default import (  # type: ignore
        AWG_H_COUNT,
        AWG_H_GAP,
        AWG_H_MAX,
        AWG_H_MIN,
        AWG_H_SPAN_MAX,
        AWG_H_SPAN_MIN,
        AWG_INFRA_AUTO_JC_MAX,
        AWG_INFRA_AUTO_JC_MIN,
        AWG_INFRA_AUTO_JUNK_SIZE_MAX,
        AWG_INFRA_AUTO_JUNK_SIZE_MIN,
        AWG_INFRA_AUTO_S1_MAX,
        AWG_INFRA_AUTO_S1_MIN,
        AWG_INFRA_AUTO_S2_MAX,
        AWG_INFRA_AUTO_S2_MIN,
        AWG_INFRA_AUTO_S3_MAX,
        AWG_INFRA_AUTO_S3_MIN,
        AWG_INFRA_AUTO_S4_MAX,
        AWG_INFRA_AUTO_S4_MIN,
        AWG_INFRA_I1,
        AWG_INFRA_I2,
        AWG_INFRA_I3,
        AWG_INFRA_I4,
        AWG_INFRA_I5,
        AWG_JC_MAX,
        AWG_JC_MIN,
        AWG_JUNK_SIZE_MAX,
        AWG_JUNK_SIZE_MIN,
        AWG_S1_MAX,
        AWG_S1_MIN,
        AWG_S2_MAX,
        AWG_S2_MIN,
        AWG_S3_MAX,
        AWG_S3_MIN,
        AWG_S4_MAX,
        AWG_S4_MIN,
        INFRA_AWG_PORT_RANGE,
        PORT_MAX,
        PORT_MIN,
    )
    from process import die  # type: ignore
    from stable_model import random_free_slots, stable_seed_u64  # type: ignore


AWG_KEYS = {
    "jc",
    "jmin",
    "jmax",
    "s1",
    "s2",
    "s3",
    "s4",
    "h1",
    "h2",
    "h3",
    "h4",
    "i1",
    "i2",
    "i3",
    "i4",
    "i5",
}


def _require_known_keys(raw: dict[str, object], where: str, allowed: set[str]) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        die(f"{where}: unknown config key(s): {', '.join(unknown)}")


def parse_port_range_value(value: object, where: str) -> PortRange:
    if not isinstance(value, str):
        die(f"{where} must be like '20000-32767'")

    m = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if not m:
        die(f"{where} must be like '20000-32767'")

    start = int(m.group(1))
    end = int(m.group(2))
    if start < PORT_MIN or end > PORT_MAX or start > end:
        die(f"{where} must be within {PORT_MIN}..{PORT_MAX} and start <= end")

    return PortRange(start=start, end=end)


def infra_awg_port_range() -> PortRange:
    return parse_port_range_value(INFRA_AWG_PORT_RANGE, "INFRA_AWG_PORT_RANGE")


def parse_awg_h_range(value: str, where: str) -> tuple[int, int]:
    value = value.strip()
    parts = value.split("-", 1)
    if len(parts) != 2:
        die(f"{where} must be START-END")

    try:
        start = int(parts[0])
        end = int(parts[1])
    except ValueError:
        die(f"{where} must contain integer bounds")

    if start < AWG_H_MIN or end > AWG_H_MAX or start > end:
        die(f"{where} must be in range {AWG_H_MIN}..{AWG_H_MAX} " "and start <= end")

    return start, end


def ranges_overlap(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] <= right[1] and right[0] <= left[1]


def validate_awg_h_range_strings(values: list[str], where: str) -> None:
    if len(values) != AWG_H_COUNT:
        die(f"{where}: expected {AWG_H_COUNT} AWG H ranges, got {len(values)}")

    parsed: list[tuple[str, tuple[int, int]]] = []
    for idx, value in enumerate(values, start=1):
        name = f"h{idx}"
        parsed.append((name, parse_awg_h_range(value, f"{where}.{name}")))

    for left_idx, (left_name, left) in enumerate(parsed):
        for right_name, right in parsed[left_idx + 1 :]:
            if ranges_overlap(left, right):
                die(
                    f"{where}: AWG H ranges overlap: "
                    f"{left_name}={left[0]}-{left[1]} "
                    f"{right_name}={right[0]}-{right[1]}"
                )


def validate_awg_h_ranges(awg: AwgOptions, where: str) -> None:
    validate_awg_h_range_strings([awg.h1, awg.h2, awg.h3, awg.h4], where)


def validate_awg_runtime_ranges(awg: AwgOptions, where: str) -> None:
    if awg.jc < AWG_JC_MIN or awg.jc > AWG_JC_MAX:
        die(f"{where}.jc must be in range {AWG_JC_MIN}..{AWG_JC_MAX}")
    if (
        awg.jmin < AWG_JUNK_SIZE_MIN
        or awg.jmin > AWG_JUNK_SIZE_MAX
        or awg.jmax < AWG_JUNK_SIZE_MIN
        or awg.jmax > AWG_JUNK_SIZE_MAX
        or awg.jmin > awg.jmax
    ):
        die(
            f"{where}.jmin/jmax must be in range "
            f"{AWG_JUNK_SIZE_MIN}..{AWG_JUNK_SIZE_MAX} and jmin <= jmax"
        )
    if not (
        AWG_S1_MIN <= awg.s1 <= AWG_S1_MAX
        and AWG_S2_MIN <= awg.s2 <= AWG_S2_MAX
        and AWG_S3_MIN <= awg.s3 <= AWG_S3_MAX
        and AWG_S4_MIN <= awg.s4 <= AWG_S4_MAX
    ):
        die(
            f"{where}.s1 must be {AWG_S1_MIN}..{AWG_S1_MAX}, "
            f"s2 must be {AWG_S2_MIN}..{AWG_S2_MAX}, "
            f"s3 must be {AWG_S3_MIN}..{AWG_S3_MAX}, "
            f"s4 must be {AWG_S4_MIN}..{AWG_S4_MAX}"
        )


def validate_awg_options(awg: AwgOptions, where: str) -> None:
    validate_awg_runtime_ranges(awg, where)
    validate_awg_h_ranges(awg, where)


def validate_awg_auto_ranges() -> None:
    if AWG_INFRA_AUTO_JC_MIN < AWG_JC_MIN or AWG_INFRA_AUTO_JC_MAX > AWG_JC_MAX:
        die("bad AWG_INFRA_AUTO_JC_MIN/AWG_INFRA_AUTO_JC_MAX")
    if AWG_INFRA_AUTO_JC_MIN > AWG_INFRA_AUTO_JC_MAX:
        die("bad AWG_INFRA_AUTO_JC_MIN/AWG_INFRA_AUTO_JC_MAX")
    if (
        AWG_INFRA_AUTO_JUNK_SIZE_MIN < AWG_JUNK_SIZE_MIN
        or AWG_INFRA_AUTO_JUNK_SIZE_MAX > AWG_JUNK_SIZE_MAX
        or AWG_INFRA_AUTO_JUNK_SIZE_MIN > AWG_INFRA_AUTO_JUNK_SIZE_MAX
    ):
        die("bad AWG_INFRA_AUTO_JUNK_SIZE_MIN/AWG_INFRA_AUTO_JUNK_SIZE_MAX")
    if (
        AWG_INFRA_AUTO_S1_MIN < AWG_S1_MIN
        or AWG_INFRA_AUTO_S1_MAX > AWG_S1_MAX
        or AWG_INFRA_AUTO_S1_MIN > AWG_INFRA_AUTO_S1_MAX
    ):
        die("bad AWG_INFRA_AUTO_S1_MIN/AWG_INFRA_AUTO_S1_MAX")
    if (
        AWG_INFRA_AUTO_S2_MIN < AWG_S2_MIN
        or AWG_INFRA_AUTO_S2_MAX > AWG_S2_MAX
        or AWG_INFRA_AUTO_S2_MIN > AWG_INFRA_AUTO_S2_MAX
    ):
        die("bad AWG_INFRA_AUTO_S2_MIN/AWG_INFRA_AUTO_S2_MAX")
    if (
        AWG_INFRA_AUTO_S3_MIN < AWG_S3_MIN
        or AWG_INFRA_AUTO_S3_MAX > AWG_S3_MAX
        or AWG_INFRA_AUTO_S3_MIN > AWG_INFRA_AUTO_S3_MAX
    ):
        die("bad AWG_INFRA_AUTO_S3_MIN/AWG_INFRA_AUTO_S3_MAX")
    if (
        AWG_INFRA_AUTO_S4_MIN < AWG_S4_MIN
        or AWG_INFRA_AUTO_S4_MAX > AWG_S4_MAX
        or AWG_INFRA_AUTO_S4_MIN > AWG_INFRA_AUTO_S4_MAX
    ):
        die("bad AWG_INFRA_AUTO_S4_MIN/AWG_INFRA_AUTO_S4_MAX")


def stable_awg_runtime_params(
    link_key: str,
) -> tuple[int, int, int, int, int, int, int]:
    # Derive per-link AWG runtime parameters from the same stable link key
    # family as ports/link addresses/H-ranges.  This keeps generation
    # deterministic without forcing identical AWG fingerprints on all links.
    validate_awg_auto_ranges()
    rng = random.Random(stable_seed_u64(f"awg-runtime:{link_key}"))

    jc = rng.randint(AWG_INFRA_AUTO_JC_MIN, AWG_INFRA_AUTO_JC_MAX)
    j_left = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    j_right = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    jmin, jmax = sorted((j_left, j_right))

    s1 = rng.randint(AWG_INFRA_AUTO_S1_MIN, AWG_INFRA_AUTO_S1_MAX)
    s2 = rng.randint(AWG_INFRA_AUTO_S2_MIN, AWG_INFRA_AUTO_S2_MAX)
    s3 = rng.randint(AWG_INFRA_AUTO_S3_MIN, AWG_INFRA_AUTO_S3_MAX)
    s4 = rng.randint(AWG_INFRA_AUTO_S4_MIN, AWG_INFRA_AUTO_S4_MAX)

    return jc, jmin, jmax, s1, s2, s3, s4


def stable_awg_h_ranges(link_key: str) -> tuple[str, str, str, str]:
    if AWG_H_COUNT != 4:
        die("infra AWG H generation expects AWG_H_COUNT = 4")
    if AWG_H_GAP < 0:
        die("AWG_H_GAP must be non-negative")
    if AWG_H_SPAN_MIN <= 0 or AWG_H_SPAN_MAX < AWG_H_SPAN_MIN:
        die("bad AWG_H_SPAN_MIN/AWG_H_SPAN_MAX")
    if AWG_H_MAX < AWG_H_MIN:
        die("bad AWG_H_MIN/AWG_H_MAX")

    rng = random.Random(stable_seed_u64(f"awg-h:{link_key}"))
    lengths = [rng.randint(AWG_H_SPAN_MIN, AWG_H_SPAN_MAX) for _ in range(AWG_H_COUNT)]

    available = AWG_H_MAX - AWG_H_MIN + 1
    required = sum(lengths) + (len(lengths) - 1) * AWG_H_GAP
    if required > available:
        die(
            "AWG H range is too small for generated spans: "
            f"need {required}, have {available}"
        )

    free_slots = random_free_slots(rng, available - required, len(lengths) + 1)

    ranges: list[str] = []
    pos = AWG_H_MIN + free_slots[0]
    for idx, length in enumerate(lengths):
        start = pos
        end = start + length - 1
        ranges.append(f"{start}-{end}")
        if idx + 1 < len(lengths):
            pos = end + 1 + AWG_H_GAP + free_slots[idx + 1]

    validate_awg_h_range_strings(ranges, f"infra AWG {link_key}")
    return ranges[0], ranges[1], ranges[2], ranges[3]


def awg_for_infra_link(link_key: str) -> AwgOptions:
    h1, h2, h3, h4 = stable_awg_h_ranges(link_key)
    jc, jmin, jmax, s1, s2, s3, s4 = stable_awg_runtime_params(link_key)
    awg = AwgOptions(
        jc=jc,
        jmin=jmin,
        jmax=jmax,
        s1=s1,
        s2=s2,
        s3=s3,
        s4=s4,
        h1=h1,
        h2=h2,
        h3=h3,
        h4=h4,
        i1=AWG_INFRA_I1,
        i2=AWG_INFRA_I2,
        i3=AWG_INFRA_I3,
        i4=AWG_INFRA_I4,
        i5=AWG_INFRA_I5,
    )
    validate_awg_options(awg, f"infra AWG {link_key}")
    return awg


def peer_endpoint(
    *,
    listen_ip: str,
    port: int,
) -> tuple[str, int]:
    return listen_ip, port


def load_awg_options(raw: object, where: str) -> AwgOptions:
    if raw is None:
        die(f"{where}.awg is required for AmneziaWG links")
    if not isinstance(raw, dict):
        die(f"{where}.awg must be an object")
    _require_known_keys(raw, f"{where}.awg", AWG_KEYS)

    def get_int(key: str) -> int:
        if key not in raw:
            die(f"{where}.awg.{key} is required")
        try:
            return int(raw[key])
        except Exception:
            die(f"{where}.awg.{key} must be an integer")

    def get_str(key: str, default: str = "") -> str:
        value = raw.get(key, default)
        if value is None:
            return default
        return str(value).strip()

    jc = get_int("jc")
    jmin = get_int("jmin")
    jmax = get_int("jmax")
    s1 = get_int("s1")
    s2 = get_int("s2")
    s3 = get_int("s3")
    s4 = get_int("s4")

    awg = AwgOptions(
        jc=jc,
        jmin=jmin,
        jmax=jmax,
        s1=s1,
        s2=s2,
        s3=s3,
        s4=s4,
        h1=get_str("h1"),
        h2=get_str("h2"),
        h3=get_str("h3"),
        h4=get_str("h4"),
        i1=get_str("i1"),
        i2=get_str("i2"),
        i3=get_str("i3"),
        i4=get_str("i4"),
        i5=get_str("i5"),
    )
    validate_awg_options(awg, f"{where}.awg")
    return awg


def awg_uci_options(awg: AwgOptions) -> dict[str, str]:
    return {
        "awg_jc": str(awg.jc),
        "awg_jmin": str(awg.jmin),
        "awg_jmax": str(awg.jmax),
        "awg_s1": str(awg.s1),
        "awg_s2": str(awg.s2),
        "awg_s3": str(awg.s3),
        "awg_s4": str(awg.s4),
        "awg_h1": str(awg.h1),
        "awg_h2": str(awg.h2),
        "awg_h3": str(awg.h3),
        "awg_h4": str(awg.h4),
        **({"awg_i1": awg.i1} if awg.i1 else {}),
        **({"awg_i2": awg.i2} if awg.i2 else {}),
        **({"awg_i3": awg.i3} if awg.i3 else {}),
        **({"awg_i4": awg.i4} if awg.i4 else {}),
        **({"awg_i5": awg.i5} if awg.i5 else {}),
    }


def awg_conf_lines(awg: AwgOptions) -> list[str]:
    return [
        f"Jc = {awg.jc}",
        f"Jmin = {awg.jmin}",
        f"Jmax = {awg.jmax}",
        f"S1 = {awg.s1}",
        f"S2 = {awg.s2}",
        f"S3 = {awg.s3}",
        f"S4 = {awg.s4}",
        f"H1 = {awg.h1}",
        f"H2 = {awg.h2}",
        f"H3 = {awg.h3}",
        f"H4 = {awg.h4}",
        *([f"I1 = {awg.i1}"] if awg.i1 else []),
        *([f"I2 = {awg.i2}"] if awg.i2 else []),
        *([f"I3 = {awg.i3}"] if awg.i3 else []),
        *([f"I4 = {awg.i4}"] if awg.i4 else []),
        *([f"I5 = {awg.i5}"] if awg.i5 else []),
    ]
