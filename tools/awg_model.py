#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import base64
import hashlib
import hmac
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
        AWG_INFRA_SIGNATURE_COUNT_MAX,
        AWG_INFRA_SIGNATURE_COUNT_MIN,
        AWG_INFRA_SIGNATURE_SIZE_MAX,
        AWG_INFRA_SIGNATURE_SIZE_MIN,
        AWG_INFRA_SIGNATURE_TAGS,
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
        AWG_INFRA_SIGNATURE_COUNT_MAX,
        AWG_INFRA_SIGNATURE_COUNT_MIN,
        AWG_INFRA_SIGNATURE_SIZE_MAX,
        AWG_INFRA_SIGNATURE_SIZE_MIN,
        AWG_INFRA_SIGNATURE_TAGS,
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

try:
    from .default import (
        AWG_CONTENT_PADDING_ADDITION,
        AWG_DISABLE_COOKIES,
        AWG_HEADER_PROTECTION_ENABLED,
        AWG_KEEPALIVE_TIMEOUT_MAX,
        AWG_KEEPALIVE_TIMEOUT_MIN,
        AWG_MAX_HANDSHAKE_ATTEMPTS_MAX,
        AWG_MAX_HANDSHAKE_ATTEMPTS_MIN,
        AWG_PERSISTENT_KEEPALIVE_MAX,
        AWG_PERSISTENT_KEEPALIVE_MIN,
        AWG_RANDOM_TRAILERS,
        AWG_REJECT_AFTER_TIME_MAX,
        AWG_REJECT_AFTER_TIME_MIN,
        AWG_REKEY_AFTER_TIME_MAX,
        AWG_REKEY_AFTER_TIME_MIN,
        AWG_REKEY_TIMEOUT_MAX,
        AWG_REKEY_TIMEOUT_MIN,
        CONFIG_KEY_MATERIALS_KEY_PATH,
        CONFIG_PATH,
    )
    from .secrets import master_key
except ImportError:
    from default import (  # type: ignore
        AWG_CONTENT_PADDING_ADDITION,
        AWG_DISABLE_COOKIES,
        AWG_HEADER_PROTECTION_ENABLED,
        AWG_KEEPALIVE_TIMEOUT_MAX,
        AWG_KEEPALIVE_TIMEOUT_MIN,
        AWG_MAX_HANDSHAKE_ATTEMPTS_MAX,
        AWG_MAX_HANDSHAKE_ATTEMPTS_MIN,
        AWG_PERSISTENT_KEEPALIVE_MAX,
        AWG_PERSISTENT_KEEPALIVE_MIN,
        AWG_RANDOM_TRAILERS,
        AWG_REJECT_AFTER_TIME_MAX,
        AWG_REJECT_AFTER_TIME_MIN,
        AWG_REKEY_AFTER_TIME_MAX,
        AWG_REKEY_AFTER_TIME_MIN,
        AWG_REKEY_TIMEOUT_MAX,
        AWG_REKEY_TIMEOUT_MIN,
        CONFIG_KEY_MATERIALS_KEY_PATH,
        CONFIG_PATH,
    )
    from secrets import master_key  # type: ignore


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
    "header_protection_key",
    "content_padding_addition",
    "rekey_after_time",
    "rekey_timeout",
    "reject_after_time",
    "keepalive_timeout",
    "max_handshake_attempts",
    "random_trailers",
    "disable_cookies",
    "persistent_keepalive",
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


def _parse_u16_range(
    value: str, where: str, *, allow_empty: bool = False
) -> tuple[int, int] | None:
    value = value.strip()
    if not value:
        if allow_empty:
            return None
        die(f"{where} must not be empty")
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", value)
    if not m:
        die(f"{where} must be N or N-M")
    start = int(m.group(1))
    end = int(m.group(2) or m.group(1))
    if start < 0 or end > 65535 or start > end:
        die(f"{where} must be within 0..65535 and start <= end")
    return start, end


def validate_awg_v3_options(awg: AwgOptions, where: str) -> None:
    for key in (
        "rekey_after_time",
        "rekey_timeout",
        "reject_after_time",
        "keepalive_timeout",
        "max_handshake_attempts",
        "persistent_keepalive",
    ):
        _parse_u16_range(getattr(awg, key), f"{where}.{key}")
    _parse_u16_range(
        awg.content_padding_addition,
        f"{where}.content_padding_addition",
        allow_empty=True,
    )
    if awg.header_protection_key:
        try:
            decoded = base64.b64decode(awg.header_protection_key, validate=True)
        except Exception:
            die(f"{where}.header_protection_key must be base64")
        if len(decoded) != 32:
            die(f"{where}.header_protection_key must decode to 32 bytes")
        if min(awg.s1, awg.s2, awg.s3, awg.s4) < 12:
            die(f"{where}: HeaderProtectionKey requires S1-S4 >= 12")


def validate_awg_options(awg: AwgOptions, where: str) -> None:
    validate_awg_runtime_ranges(awg, where)
    validate_awg_h_ranges(awg, where)
    validate_awg_v3_options(awg, where)


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


def stable_awg_shared_runtime_params(link_key: str) -> tuple[int, int, int, int]:
    """Parameters that must describe the same wire format on both ends."""
    validate_awg_auto_ranges()
    # Preserve the S1-S4 values produced by the original builder.
    # It used one RNG for J and S, so consume the legacy J draws before
    # deriving S. Only J moves to a directional seed.
    rng = random.Random(stable_seed_u64(f"awg-runtime:{link_key}"))
    rng.randint(AWG_INFRA_AUTO_JC_MIN, AWG_INFRA_AUTO_JC_MAX)
    rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    s1 = rng.randint(AWG_INFRA_AUTO_S1_MIN, AWG_INFRA_AUTO_S1_MAX)
    s2 = rng.randint(AWG_INFRA_AUTO_S2_MIN, AWG_INFRA_AUTO_S2_MAX)
    s3 = rng.randint(AWG_INFRA_AUTO_S3_MIN, AWG_INFRA_AUTO_S3_MAX)
    s4 = rng.randint(AWG_INFRA_AUTO_S4_MIN, AWG_INFRA_AUTO_S4_MAX)
    return s1, s2, s3, s4


def stable_awg_directional_runtime_params(
    link_key: str, src: str, dst: str
) -> tuple[int, int, int]:
    """Local/send-side junk parameters; intentionally differ by direction."""
    validate_awg_auto_ranges()
    direction = f"{link_key}:{src}->{dst}"
    rng = random.Random(stable_seed_u64(f"awg-direction-runtime:v1:{direction}"))
    jc = rng.randint(AWG_INFRA_AUTO_JC_MIN, AWG_INFRA_AUTO_JC_MAX)
    j_left = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    j_right = rng.randint(AWG_INFRA_AUTO_JUNK_SIZE_MIN, AWG_INFRA_AUTO_JUNK_SIZE_MAX)
    jmin, jmax = sorted((j_left, j_right))
    return jc, jmin, jmax


def stable_awg_signature_packets(
    link_key: str, src: str, dst: str
) -> tuple[str, str, str, str, str]:
    direction = f"{link_key}:{src}->{dst}"
    rng = random.Random(stable_seed_u64(f"awg-signatures:v1:{direction}"))
    count = rng.randint(AWG_INFRA_SIGNATURE_COUNT_MIN, AWG_INFRA_SIGNATURE_COUNT_MAX)
    values: list[str] = []
    for _ in range(count):
        tag = rng.choice(AWG_INFRA_SIGNATURE_TAGS)
        size = rng.randint(AWG_INFRA_SIGNATURE_SIZE_MIN, AWG_INFRA_SIGNATURE_SIZE_MAX)
        values.append(f"<{tag} {size}>")
    values.extend([""] * (5 - len(values)))
    return values[0], values[1], values[2], values[3], values[4]


def stable_awg_runtime_params(
    link_key: str, src: str | None = None, dst: str | None = None
) -> tuple[int, int, int, int, int, int, int]:
    # Compatibility helper: callers that do not provide a direction get a
    # deterministic pseudo-direction based on the link key itself.
    src = src or link_key
    dst = dst or link_key
    jc, jmin, jmax = stable_awg_directional_runtime_params(link_key, src, dst)
    s1, s2, s3, s4 = stable_awg_shared_runtime_params(link_key)
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


def _stable_subrange(
    link_key: str,
    purpose: str,
    minimum: int,
    maximum: int,
    width_min: int,
    width_max: int,
) -> str:
    if minimum < 0 or maximum > 65535 or minimum > maximum:
        die(f"bad AWG {purpose} envelope")
    span = maximum - minimum
    if span == 0:
        return str(minimum)
    width_min = max(1, min(width_min, span))
    width_max = max(width_min, min(width_max, span))
    rng = random.Random(stable_seed_u64(f"awg-{purpose}:{link_key}"))
    width = rng.randint(width_min, width_max)
    start = rng.randint(minimum, maximum - width)
    return f"{start}-{start + width}"


def stable_awg_header_protection_key(link_key: str) -> str:
    root = master_key(CONFIG_KEY_MATERIALS_KEY_PATH, config_path=CONFIG_PATH)
    msg = b"openwrt-mesh-builder:awg-header-protection:v1\0" + link_key.encode("utf-8")
    return base64.b64encode(hmac.new(root, msg, hashlib.sha256).digest()).decode(
        "ascii"
    )


def stable_awg_v3_params(
    link_key: str, direction_key: str | None = None
) -> dict[str, object]:
    local_key = direction_key or link_key
    return {
        "header_protection_key": (
            stable_awg_header_protection_key(link_key)
            if AWG_HEADER_PROTECTION_ENABLED
            else ""
        ),
        "content_padding_addition": AWG_CONTENT_PADDING_ADDITION,
        "rekey_after_time": _stable_subrange(
            local_key,
            "rekey-after-time",
            AWG_REKEY_AFTER_TIME_MIN,
            AWG_REKEY_AFTER_TIME_MAX,
            20,
            30,
        ),
        "rekey_timeout": _stable_subrange(
            local_key,
            "rekey-timeout",
            AWG_REKEY_TIMEOUT_MIN,
            AWG_REKEY_TIMEOUT_MAX,
            2,
            3,
        ),
        "reject_after_time": _stable_subrange(
            local_key,
            "reject-after-time",
            AWG_REJECT_AFTER_TIME_MIN,
            AWG_REJECT_AFTER_TIME_MAX,
            20,
            30,
        ),
        "keepalive_timeout": _stable_subrange(
            local_key,
            "keepalive-timeout",
            AWG_KEEPALIVE_TIMEOUT_MIN,
            AWG_KEEPALIVE_TIMEOUT_MAX,
            4,
            6,
        ),
        "max_handshake_attempts": _stable_subrange(
            local_key,
            "max-handshake-attempts",
            AWG_MAX_HANDSHAKE_ATTEMPTS_MIN,
            AWG_MAX_HANDSHAKE_ATTEMPTS_MAX,
            4,
            7,
        ),
        "random_trailers": AWG_RANDOM_TRAILERS,
        "disable_cookies": AWG_DISABLE_COOKIES,
        "persistent_keepalive": _stable_subrange(
            local_key,
            "persistent-keepalive",
            AWG_PERSISTENT_KEEPALIVE_MIN,
            AWG_PERSISTENT_KEEPALIVE_MAX,
            5,
            8,
        ),
    }


def awg_for_infra_direction(link_key: str, src: str, dst: str) -> AwgOptions:
    h1, h2, h3, h4 = stable_awg_h_ranges(link_key)
    s1, s2, s3, s4 = stable_awg_shared_runtime_params(link_key)
    jc, jmin, jmax = stable_awg_directional_runtime_params(link_key, src, dst)
    i1, i2, i3, i4, i5 = stable_awg_signature_packets(link_key, src, dst)
    direction_key = f"{link_key}:{src}->{dst}"
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
        i1=i1,
        i2=i2,
        i3=i3,
        i4=i4,
        i5=i5,
        **stable_awg_v3_params(link_key, direction_key),
    )
    validate_awg_options(awg, f"infra AWG {direction_key}")
    return awg


def awg_for_infra_link(link_key: str) -> AwgOptions:
    # Backward-compatible deterministic profile for tooling that has no local
    # endpoint context. New infra generation should use awg_for_infra_direction.
    return awg_for_infra_direction(link_key, link_key, link_key)


def peer_endpoint(
    *,
    listen_ip: str,
    port: int,
) -> tuple[str, int]:
    return listen_ip, port


def load_awg_options(
    raw: object, where: str, *, auto_key: str | None = None
) -> AwgOptions:
    if raw is None:
        die(f"{where}.awg is required for AmneziaWG links")
    if not isinstance(raw, dict):
        die(f"{where}.awg must be an object")
    _require_known_keys(raw, f"{where}.awg", AWG_KEYS)

    auto = stable_awg_v3_params(auto_key) if auto_key else {}

    def get_int(key: str) -> int:
        if key not in raw:
            die(f"{where}.awg.{key} is required")
        try:
            return int(raw[key])
        except Exception:
            die(f"{where}.awg.{key} must be an integer")

    def get_str(key: str, default: str = "") -> str:
        value = raw.get(key, auto.get(key, default))
        if value is None:
            return default
        return str(value).strip()

    def get_bool(key: str, default: bool) -> bool:
        value = raw.get(key, auto.get(key, default))
        if not isinstance(value, bool):
            die(f"{where}.awg.{key} must be a boolean")
        return value

    awg = AwgOptions(
        jc=get_int("jc"),
        jmin=get_int("jmin"),
        jmax=get_int("jmax"),
        s1=get_int("s1"),
        s2=get_int("s2"),
        s3=get_int("s3"),
        s4=get_int("s4"),
        h1=get_str("h1"),
        h2=get_str("h2"),
        h3=get_str("h3"),
        h4=get_str("h4"),
        i1=get_str("i1"),
        i2=get_str("i2"),
        i3=get_str("i3"),
        i4=get_str("i4"),
        i5=get_str("i5"),
        header_protection_key=get_str("header_protection_key"),
        content_padding_addition=get_str("content_padding_addition"),
        rekey_after_time=get_str("rekey_after_time"),
        rekey_timeout=get_str("rekey_timeout"),
        reject_after_time=get_str("reject_after_time"),
        keepalive_timeout=get_str("keepalive_timeout"),
        max_handshake_attempts=get_str("max_handshake_attempts"),
        random_trailers=get_bool("random_trailers", AWG_RANDOM_TRAILERS),
        disable_cookies=get_bool("disable_cookies", AWG_DISABLE_COOKIES),
        persistent_keepalive=get_str("persistent_keepalive"),
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
        **(
            {"awg_header_protection_key": awg.header_protection_key}
            if awg.header_protection_key
            else {}
        ),
        **(
            {"awg_content_padding_addition": awg.content_padding_addition}
            if awg.content_padding_addition
            else {}
        ),
        "awg_rekey_after_time": awg.rekey_after_time,
        "awg_rekey_timeout": awg.rekey_timeout,
        "awg_reject_after_time": awg.reject_after_time,
        "awg_keepalive_timeout": awg.keepalive_timeout,
        "awg_max_handshake_attempts": awg.max_handshake_attempts,
        "awg_random_trailers": "1" if awg.random_trailers else "0",
        "awg_disable_cookies": "1" if awg.disable_cookies else "0",
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
        *(
            [f"HeaderProtectionKey = {awg.header_protection_key}"]
            if awg.header_protection_key
            else []
        ),
        *(
            [f"ContentPaddingAddition = {awg.content_padding_addition}"]
            if awg.content_padding_addition
            else []
        ),
        f"RekeyAfterTime = {awg.rekey_after_time}",
        f"RekeyTimeout = {awg.rekey_timeout}",
        f"RejectAfterTime = {awg.reject_after_time}",
        f"KeepaliveTimeout = {awg.keepalive_timeout}",
        f"MaxHandshakeAttempts = {awg.max_handshake_attempts}",
        f"RandomTrailers = {1 if awg.random_trailers else 0}",
        f"DisableCookies = {1 if awg.disable_cookies else 0}",
    ]
