#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True

try:
    from .common import *
    from .materials import public_key_from_private as wg_public_key_from_private
    from .validate_context import validate_optional_mtu
except ImportError:
    from common import *  # type: ignore
    from materials import public_key_from_private as wg_public_key_from_private  # type: ignore
    from validate_context import validate_optional_mtu  # type: ignore


def public_key_or_die(priv: str, where: str) -> str:
    try:
        return wg_public_key_from_private(priv)
    except RuntimeError as exc:
        die(f"{where}: failed to derive public key: {exc}")


def require_option(opts: dict[str, str], key: str, expected: str, where: str) -> None:
    actual = opts.get(key)
    if actual != expected:
        die(f"{where}: bad {key}: expected {expected!r}, got {actual!r}")


def require_list(
    lists: dict[str, list[str]], key: str, expected: list[str], where: str
) -> None:
    actual = lists.get(key, [])
    if actual != expected:
        die(f"{where}: bad list {key}: expected {expected!r}, got {actual!r}")


def awg_conf_key_map() -> dict[str, str]:
    return {
        "awg_jc": "Jc",
        "awg_jmin": "Jmin",
        "awg_jmax": "Jmax",
        "awg_s1": "S1",
        "awg_s2": "S2",
        "awg_s3": "S3",
        "awg_s4": "S4",
        "awg_h1": "H1",
        "awg_h2": "H2",
        "awg_h3": "H3",
        "awg_h4": "H4",
        "awg_i1": "I1",
        "awg_i2": "I2",
        "awg_i3": "I3",
        "awg_i4": "I4",
        "awg_i5": "I5",
    }


def validate_awg_uci_options(opts: dict[str, str], awg: AwgOptions, where: str) -> None:
    expected = awg_uci_options(awg)
    for key, value in expected.items():
        require_option(opts, key, value, where)

    # If an I* option is empty in config.json, it must not be left stale in UCI.
    for key in ("awg_i1", "awg_i2", "awg_i3", "awg_i4", "awg_i5"):
        if key not in expected and key in opts:
            die(f"{where}: unexpected stale {key}")


def validate_awg_conf_options(
    iface: dict[str, str], awg: AwgOptions, where: str
) -> None:
    expected_uci = awg_uci_options(awg)
    key_map = awg_conf_key_map()
    for uci_key, conf_key in key_map.items():
        expected = expected_uci.get(uci_key)
        actual = iface.get(conf_key)
        if expected is None:
            if actual is not None:
                die(f"{where}: unexpected stale {conf_key}")
        elif actual != expected:
            die(f"{where}: bad {conf_key}: expected {expected!r}, got {actual!r}")


def require_interface_block(
    parsed: dict[str, dict[str, object]], iface_name: str, where: str
) -> dict[str, object]:
    block = find_block_by_type_and_name(parsed, "interface", iface_name)
    if block is None:
        die(f"{where}: missing interface {iface_name}")
    return block


def require_peer_block(
    parsed: dict[str, dict[str, object]], peer_type: str, where: str
) -> dict[str, object]:
    block = find_block_by_type_and_name(parsed, peer_type)
    if block is None:
        die(f"{where}: missing peer block {peer_type}")
    return block


def public_from_iface(block: dict[str, object], where: str) -> str:
    opts = block.get("options", {})
    priv = opts.get("private_key")
    if not priv:
        die(f"{where}: missing private_key")
    return public_key_or_die(str(priv), where)


def validate_router_awg_interface_common(
    block: dict[str, object], awg: AwgOptions, addresses: list[str], where: str
) -> str:
    opts = block.get("options", {})
    lists = block.get("lists", {})
    require_option(opts, "proto", PROTOCOL_AMNEZIAWG, where)
    require_option(opts, "defaultroute", "0", where)
    validate_optional_mtu(opts.get("mtu"), where)
    validate_awg_uci_options(opts, awg, where)
    require_list(lists, "addresses", addresses, where)
    return public_from_iface(block, where)


def validate_awg_peer_common(
    block: dict[str, object], expected_public_key: str, where: str
) -> None:
    opts = block.get("options", {})
    lists = block.get("lists", {})
    require_option(opts, "public_key", expected_public_key, where)
    require_option(opts, "route_allowed_ips", "1", where)
    require_option(opts, "persistent_keepalive", str(KEEPALIVE), where)
    require_list(lists, "allowed_ips", DEFAULT_ALLOWED_IPS, where)


def find_block_by_type_and_name(
    parsed: dict[str, dict[str, object]],
    typ: str,
    name: str | None = None,
) -> dict[str, object] | None:
    for block in parsed.values():
        if block.get("type") != typ:
            continue
        if name is not None and block.get("name") != name:
            continue
        return block
    return None
