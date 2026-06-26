#!/usr/bin/env python3

try:
    from .process import die
    from .default import TUNNEL_MTU
    from .tunnel_model import ipip_mtu_value
except ImportError:
    from process import die  # type: ignore
    from default import TUNNEL_MTU  # type: ignore
    from tunnel_model import ipip_mtu_value  # type: ignore

VERBOSE = False


def set_verbose(value: bool) -> None:
    global VERBOSE
    VERBOSE = value


def vprint(*args, **kwargs) -> None:
    if VERBOSE:
        print(*args, **kwargs)


def validate_optional_mtu(actual: str | None, where: str) -> None:
    if TUNNEL_MTU is None:
        if actual is not None:
            die(f"{where}: unexpected MTU")
        return
    if actual != str(TUNNEL_MTU):
        die(f"{where}: bad MTU")


def validate_optional_ipip_mtu(actual: str | None, where: str) -> None:
    value = ipip_mtu_value()
    if value is None:
        if actual not in (None, ""):
            die(f"{where}: unexpected IPIP MTU")
        return
    if actual != str(value):
        die(f"{where}: bad IPIP MTU: expected {value}, got {actual!r}")
