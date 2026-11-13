#!/usr/bin/env python3
"""Remove derived node artifacts while retaining source key material."""

import os
import re
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .change_report import log_change
from .config_model import ConfigData
from .default import (
    FIREWALL_MARKER,
    PROTOCOL_AMNEZIAWG,
    PROTOCOL_OPENVPN,
    PROTOCOL_WIREGUARD,
)
from .generate_router_misc import (
    remove_managed_pppoe_blocks,
    remove_managed_wifi_blocks,
    remove_openvpn_babeld_hotplug_block,
)
from .layout import router_dir, server_exit_dir
from .materials import extract_tunnel_private_key_value, require_encrypted_material
from .openvpn_model import openvpn_inline_material
from .process import die
from .uci import parse_uci_block, split_uci_blocks

NETWORK_PART = Path("files/etc/config/network_part")
BOOTSTRAP = Path("files/etc/uci-defaults/99-firstboot-custom")
OPENVPN_ROOT = Path("files/etc/openvpn")
WIREGUARD_ROOT = Path("files/etc/wireguard")
SERVER_AWG_ROOT = Path("etc/amnezia/amneziawg")


@dataclass(frozen=True)
class PreservedFile:
    data: bytes
    mode: int


def checked_source(root: Path, relative: Path) -> Path:
    """Never follow a symlink while reading material from a generated tree."""
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            die(f"--clean refuses to preserve symlink: {path}")
    return path


def save_bytes(
    root: Path, rel: Path, result: dict[Path, PreservedFile], *, required: bool = False
) -> None:
    source = checked_source(root, rel)
    if not source.exists():
        if required:
            die(f"--clean: required material is missing: {source}")
        return
    if not source.is_file():
        die(f"--clean: expected a regular file: {source}")
    result[rel] = PreservedFile(
        source.read_bytes(), stat.S_IMODE(source.stat().st_mode)
    )


def save_text(
    root: Path,
    rel: Path,
    text: str,
    result: dict[Path, PreservedFile],
    *,
    mode: int = 0o600,
) -> None:
    result[rel] = PreservedFile(text.encode("utf-8"), mode)


def network_private_keys(root: Path, result: dict[Path, PreservedFile]) -> None:
    path = checked_source(root, NETWORK_PART)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    preserved: list[str] = []
    names: set[str] = set()
    for block in split_uci_blocks(text):
        if not block.strip():
            continue
        parsed = parse_uci_block(block)
        if not parsed:
            if "private_key" in block:
                die(f"--clean: cannot parse private key in {path}")
            continue
        opts = parsed["options"]
        if "private_key" not in opts:
            continue
        if parsed["type"] != "interface" or parsed["name"] == "interface":
            die(f"--clean: invalid private-key section in {path}")
        name = str(parsed["name"])
        if name in names:
            die(f"--clean: duplicate private-key interface {name} in {path}")
        names.add(name)
        key = opts["private_key"]
        if not key or "'" in key or "\n" in key:
            die(f"--clean: malformed private key for {name} in {path}")
        require_encrypted_material(key, f"{path}: {name}.private_key")
        preserved.append(f"config interface '{name}'\n    option private_key '{key}'")
    if preserved:
        save_text(root, NETWORK_PART, "\n\n".join(preserved) + "\n", result)


def custom_bootstrap(root: Path, result: dict[Path, PreservedFile]) -> None:
    path = checked_source(root, BOOTSTRAP)
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    marker = re.search(rf"(?m)^{re.escape(FIREWALL_MARKER)}\s*$", text)
    if marker is None:
        die(f"--clean: missing customization marker in {path}")
    before = text[: marker.start()]
    # Preserve the entire user-owned prefix, not just customization().
    # The only code replaced here is the generator-owned content inside it.
    match = re.search(
        r"^customization\(\)\s*\{\n(?P<body>.*?)^\}[ \t]*$",
        before,
        flags=re.M | re.S,
    )
    if match is None:
        die(f"--clean: customization() block not found in {path}")
    body = match.group("body")
    body = remove_openvpn_babeld_hotplug_block(body)
    body = remove_managed_pppoe_blocks(body)
    body = remove_managed_wifi_blocks(body)
    body = re.sub(
        r"(?m)^[ \t]*# Set subnet and name[ \t]*\n"
        r"(?:[ \t]*uci -q set network\.lan\.ipaddr='[^'\n]*'\n)?"
        r"(?:[ \t]*uci -q set system\.@system\[0\]\.hostname='[^'\n]*'\n)?",
        "",
        body,
    )
    body = re.sub(
        r"(?m)^[ \t]*# Set DoH source address[ \t]*\n"
        r"(?:[ \t]*uci -q set https-dns-proxy\.config\.source_addr='[^'\n]*'\n)?",
        "",
        body,
    )
    body = body.strip("\n")
    if body:
        body += "\n"
    kept_prefix = before[: match.start("body")] + body + before[match.end("body") :]
    slim = kept_prefix.rstrip("\n") + f"\n\n{FIREWALL_MARKER}\n"
    save_text(root, BOOTSTRAP, slim, result, mode=stat.S_IMODE(path.stat().st_mode))


def access_material(
    root: Path, cfg: ConfigData, name: str, result: dict[Path, PreservedFile]
) -> None:
    for group in cfg.access.get(name, []):
        if group.protocol == PROTOCOL_OPENVPN:
            base = OPENVPN_ROOT / group.name
            for filename in ("ca.key", "ca.pem", "ca.srl"):
                relative = base / "ca" / filename
                if filename == "ca.key":
                    source = checked_source(root, relative)
                    if source.is_file():
                        require_encrypted_material(
                            source.read_text(encoding="utf-8"), str(source)
                        )
                save_bytes(root, relative, result)
            server_path = base / "server.ovpn"
            source = checked_source(root, server_path)
            if source.is_file():
                _ca, cert, key = openvpn_inline_material(
                    source.read_text(encoding="utf-8")
                )
                if not cert or not key:
                    die(f"--clean: server OpenVPN credentials missing: {source}")
                require_encrypted_material(key, str(source))
                save_text(
                    root,
                    server_path,
                    f"<cert>\n{cert.rstrip()}\n</cert>\n"
                    f"<key>\n{key.rstrip()}\n</key>\n",
                    result,
                )
            clients = base / "clients"
            suffix = ".ovpn"
        elif group.protocol in (PROTOCOL_WIREGUARD, PROTOCOL_AMNEZIAWG):
            clients = WIREGUARD_ROOT / group.name / "clients"
            suffix = ".conf"
        else:
            die(f"--clean: unsupported access protocol: {group.protocol}")
        # Preserve only profiles for users still present in config.json.
        for user in group.users:
            relative = clients / f"{user}{suffix}"
            source = checked_source(root, relative)
            if source.is_file():
                raw = source.read_text(encoding="utf-8")
                if group.protocol == PROTOCOL_OPENVPN:
                    _ca, _cert, private = openvpn_inline_material(raw)
                else:
                    private = extract_tunnel_private_key_value(raw)
                if not private:
                    die(f"--clean: missing client private key: {source}")
                require_encrypted_material(private, str(source))
            save_bytes(root, relative, result)


def server_private_keys(root: Path, result: dict[Path, PreservedFile]) -> None:
    directory = checked_source(root, SERVER_AWG_ROOT)
    if not directory.exists():
        return
    if not directory.is_dir():
        die(f"--clean: expected directory: {directory}")
    for file in sorted(directory.iterdir()):
        if file.suffix != ".conf":
            continue
        relative = file.relative_to(root)
        source = checked_source(root, relative)
        if not source.is_file():
            die(f"--clean: expected AWG config file: {source}")
        private = extract_tunnel_private_key_value(source.read_text(encoding="utf-8"))
        if not private:
            die(f"--clean: missing AWG private key: {source}")
        require_encrypted_material(private, str(source))
        save_text(root, relative, f"[Interface]\nPrivateKey = {private}\n", result)


def staging_directory(root: Path, files: dict[Path, PreservedFile]) -> Path:
    path = Path(tempfile.mkdtemp(prefix=".owmb-clean-stage-", dir=root.parent))
    path.chmod(stat.S_IMODE(root.stat().st_mode) if root.exists() else 0o755)
    try:
        for rel, content in files.items():
            dst = path / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(content.data)
            dst.chmod(content.mode)
    except Exception:
        shutil.rmtree(path)
        raise
    return path


def replace_with_stage(root: Path, stage: Path) -> None:
    if not root.exists():
        os.replace(stage, root)
        return
    backup = Path(tempfile.mkdtemp(prefix=".owmb-clean-backup-", dir=root.parent))
    backup.rmdir()
    os.replace(root, backup)
    try:
        os.replace(stage, root)
    except Exception:
        os.replace(backup, root)
        raise
    shutil.rmtree(backup)


def clean_generated(cfg: ConfigData) -> None:
    """Rebuild only the persistent subset; do not run configuration generators."""
    planned: list[tuple[Path, dict[Path, PreservedFile]]] = []
    for name in cfg.router_names:
        root = router_dir(cfg, name)
        if root.name == "example" or root.parent.is_symlink():
            die(f"--clean refuses template or symlinked router root: {root}")
        if root.is_symlink():
            die(f"--clean refuses router symlink: {root}")
        data: dict[Path, PreservedFile] = {}
        if root.is_dir():
            network_private_keys(root, data)
            custom_bootstrap(root, data)
            access_material(root, cfg, name, data)
        elif root.exists():
            die(f"--clean: expected router directory: {root}")
        planned.append((root, data))
    for hub in cfg.exit_hubs:
        root = server_exit_dir(hub.name)
        if root.name == "example" or root.parent.is_symlink():
            die(f"--clean refuses template or symlinked EXIT root: {root}")
        if root.is_symlink():
            die(f"--clean refuses EXIT symlink: {root}")
        data = {}
        if root.is_dir():
            server_private_keys(root, data)
        elif root.exists():
            die(f"--clean: expected EXIT directory: {root}")
        planned.append((root, data))

    # Refuse to silently leave old generated targets behind or destroy their
    # private keys. They must be archived/removed explicitly by the operator.
    for parent, expected in (
        (
            Path("routers"),
            {root.name for root, _ in planned if root.parent == Path("routers")},
        ),
        (
            Path("servers"),
            {root.name for root, _ in planned if root.parent == Path("servers")},
        ),
    ):
        if not parent.exists():
            continue
        unexpected = sorted(
            item.name
            for item in parent.iterdir()
            if item.name != "example" and item.name not in expected
        )
        if unexpected:
            die(
                f"--clean: unknown node directories in {parent}: "
                f'{", ".join(unexpected)}; archive/remove them explicitly'
            )

    # Collect and validate all protected data BEFORE touching any generated tree.
    stages: list[tuple[Path, Path, int]] = []
    try:
        for root, files in planned:
            root.parent.mkdir(parents=True, exist_ok=True)
            stage = staging_directory(root, files)
            stages.append((root, stage, len(files)))
        for root, stage, count in stages:
            replace_with_stage(root, stage)
            log_change(
                f"Cleaned {root}: preserved {count} key/customization/profile files"
            )
    finally:
        for _root, stage, _count in stages:
            if stage.exists():
                shutil.rmtree(stage)
