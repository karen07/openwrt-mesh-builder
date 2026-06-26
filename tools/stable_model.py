#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import hashlib
import random

try:
    from .config_model import PortRange
    from .default import STABLE_HASH_U32_DIGEST_SIZE, STABLE_SEED_U64_DIGEST_SIZE
    from .process import die
except ImportError:
    from config_model import PortRange  # type: ignore
    from default import STABLE_HASH_U32_DIGEST_SIZE, STABLE_SEED_U64_DIGEST_SIZE  # type: ignore
    from process import die  # type: ignore


def stable_hash_u32(seed: str) -> int:
    digest = hashlib.blake2s(
        seed.encode("utf-8"), digest_size=STABLE_HASH_U32_DIGEST_SIZE
    ).digest()
    return int.from_bytes(digest, "big")


def stable_unique_values(
    keys: list[str],
    *,
    start: int,
    end: int,
    purpose: str,
    where: str,
) -> dict[str, int]:
    if start > end:
        die(f"{where}: invalid allocation range {start}..{end}")

    span = end - start + 1
    if len(keys) > span:
        die(f"{where}: cannot allocate {len(keys)} unique values in {start}..{end}")

    used: set[int] = set()
    result: dict[str, int] = {}

    for key in sorted(keys):
        for attempt in range(span):
            value = start + (stable_hash_u32(f"{key}:{purpose}:{attempt}") % span)
            if value in used:
                continue
            used.add(value)
            result[key] = value
            break
        else:
            die(f"{where}: cannot allocate unique {purpose} for {key}")

    return result


def stable_unique_values_avoiding(
    keys: list[str],
    *,
    start: int,
    end: int,
    purpose: str,
    where: str,
    reserved: set[int] | None = None,
) -> dict[str, int]:
    reserved = set(reserved or set())
    if start > end:
        die(f"{where}: invalid allocation range {start}..{end}")

    span = end - start + 1
    if len(keys) + len(reserved) > span:
        die(
            f"{where}: cannot allocate {len(keys)} unique values in {start}..{end} "
            f"with {len(reserved)} reserved values"
        )

    used: set[int] = set(reserved)
    result: dict[str, int] = {}

    for key in sorted(keys):
        for attempt in range(span):
            value = start + (stable_hash_u32(f"{key}:{purpose}:{attempt}") % span)
            if value in used:
                continue
            used.add(value)
            result[key] = value
            break
        else:
            die(f"{where}: cannot allocate unique {purpose} for {key}")

    return result


def stable_port_for(
    port_range: PortRange,
    keys: list[str],
    key: str,
    where: str,
) -> int:
    return stable_unique_values(
        keys,
        start=port_range.start,
        end=port_range.end,
        purpose="port",
        where=where,
    )[key]


def stable_port_avoiding_for(
    port_range: PortRange,
    keys: list[str],
    key: str,
    where: str,
    reserved: set[int],
) -> int:
    return stable_unique_values_avoiding(
        keys,
        start=port_range.start,
        end=port_range.end,
        purpose="port",
        where=where,
        reserved=reserved,
    )[key]


def stable_seed_u64(seed: str) -> int:
    digest = hashlib.blake2b(
        seed.encode("utf-8"), digest_size=STABLE_SEED_U64_DIGEST_SIZE
    ).digest()
    return int.from_bytes(digest, "big")


def random_free_slots(rng: random.Random, total_free: int, slots: int) -> list[int]:
    if slots <= 1:
        return [total_free]
    points = sorted(rng.randrange(total_free + 1) for _ in range(slots - 1))
    values: list[int] = []
    prev = 0
    for point in points:
        values.append(point - prev)
        prev = point
    values.append(total_free - prev)
    return values


def ring_link_pairs(names: list[str]) -> list[tuple[str, str]]:
    # Keep the order provided by the caller.  The current config loader passes
    # mesh hubs in lexical order, so mesh rings are lexical unless a different
    # caller deliberately supplies another order.
    ordered = list(names)
    if len(ordered) < 2:
        return []
    if len(ordered) == 2:
        return [(ordered[0], ordered[1])]
    return [(ordered[i], ordered[(i + 1) % len(ordered)]) for i in range(len(ordered))]
