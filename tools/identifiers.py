#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
import re

try:
    from .process import die
except ImportError:
    from process import die


CONFIG_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_]+$")
EXIT_HUB_IDENTIFIER_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FILE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
PACKAGE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.+-]*$")
CANONICAL_IPV4_RE = re.compile(r"^(?:0|[1-9][0-9]{0,2})(?:\.(?:0|[1-9][0-9]{0,2})){3}$")
LINUX_IFACE_NAME_MAX_BYTES = 15
EXIT_HUB_NAME_MAX_BYTES = 8
FILE_IDENTIFIER_MAX_BYTES = 64
PACKAGE_IDENTIFIER_MAX_BYTES = 128
ARCH_IDENTIFIER_MAX_BYTES = 64


def require_ascii_identifier(
    value: str,
    where: str,
    *,
    pattern: re.Pattern[str],
    allowed: str,
    max_bytes: int,
) -> None:
    if not pattern.fullmatch(value):
        die(f"{where} must contain only {allowed}: {value}")
    byte_len = len(value.encode("ascii"))
    if byte_len > max_bytes:
        die(f"{where} is too long: {value} is {byte_len} bytes, max {max_bytes}")


def require_linux_iface_name(value: str, where: str) -> None:
    # Linux IFNAMSIZ is 16 bytes including the trailing NUL, so the
    # visible interface name is limited to 15 ASCII bytes.
    require_ascii_identifier(
        value,
        where,
        pattern=CONFIG_IDENTIFIER_RE,
        allowed="ASCII letters, digits and underscore",
        max_bytes=LINUX_IFACE_NAME_MAX_BYTES,
    )


def require_generated_linux_iface_name(value: str, where: str) -> None:
    # Generated names may contain fixed OpenWrt/Linux prefixes such as
    # "ipip-".  User-controlled fragments are validated separately; here we
    # only enforce the Linux visible interface-name byte limit and reject
    # the characters Linux definitely cannot accept in interface names.
    byte_len = len(value.encode("ascii"))
    if byte_len > LINUX_IFACE_NAME_MAX_BYTES:
        die(
            f"{where} is too long: {value} is {byte_len} bytes, "
            f"max {LINUX_IFACE_NAME_MAX_BYTES}"
        )
    if any(ch in value for ch in ("/", ":")) or any(ch.isspace() for ch in value):
        die(
            f"{where} contains characters that are not valid in Linux interface names: {value}"
        )


def require_exit_hub_name(value: str, where: str) -> None:
    # The generated OpenWrt IPIP section is f"ip{value}". OpenWrt then
    # creates a Linux device named f"ipip-ip{value}", so the visible
    # exit name itself may consume at most 8 ASCII bytes.  Keep this
    # uppercase-only because exit_route_env_key() uppercases names for env
    # variables, where lowercase names would otherwise collide/change.
    require_ascii_identifier(
        value,
        where,
        pattern=EXIT_HUB_IDENTIFIER_RE,
        allowed="uppercase ASCII letters, digits and underscore, starting with a letter",
        max_bytes=EXIT_HUB_NAME_MAX_BYTES,
    )


def require_file_identifier(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=FILE_IDENTIFIER_RE,
        allowed="ASCII letters, digits, underscore, dot and dash",
        max_bytes=FILE_IDENTIFIER_MAX_BYTES,
    )


def require_file_path_segment(value: str, where: str) -> None:
    require_file_identifier(value, where)
    if value in (".", ".."):
        die(f"{where} must not be '.' or '..'")


def require_package_identifier(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=PACKAGE_IDENTIFIER_RE,
        allowed=(
            "ASCII letters, digits, underscore, dot, plus and dash, "
            "starting with a letter, digit or underscore"
        ),
        max_bytes=PACKAGE_IDENTIFIER_MAX_BYTES,
    )


def require_device_profile_board(value: object, where: str) -> None:
    if not isinstance(value, str) or not value:
        die(f"{where} must be like 'target/subtarget'")

    parts = value.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        die(f"{where} must be like 'target/subtarget'")

    target, subtarget = parts
    require_file_path_segment(target, f"{where} target")
    require_file_path_segment(subtarget, f"{where} subtarget")


def require_arch_path_segment(value: str, where: str) -> None:
    require_ascii_identifier(
        value,
        where,
        pattern=PACKAGE_IDENTIFIER_RE,
        allowed=(
            "ASCII letters, digits, underscore, dot, plus and dash, "
            "starting with a letter, digit or underscore"
        ),
        max_bytes=ARCH_IDENTIFIER_MAX_BYTES,
    )
    if value in (".", ".."):
        die(f"{where} must not be '.' or '..'")


def require_device_profile_arch(value: object, where: str) -> None:
    if not isinstance(value, str) or not value:
        die(f"{where} must be a non-empty string")
    require_arch_path_segment(value, where)
