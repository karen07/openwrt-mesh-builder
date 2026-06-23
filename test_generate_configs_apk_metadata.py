#!/usr/bin/env python3
import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
import zlib

import generate_configs


def raw_deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


def package_fixture(name: str, version: str, arch: str) -> bytes:
    payload = bytearray(b"\x00\x00\x00\x00" + b"\x00\x00\x00\x00")

    def blob(value: str) -> int:
        raw = value.encode("utf-8")
        offset = len(payload)
        if len(raw) > 255:
            raise AssertionError("test fixture blob is too large")
        payload.extend(bytes([len(raw)]))
        payload.extend(raw)
        return generate_configs.ADB_TYPE_BLOB_8 | offset

    name_value = blob(name)
    version_value = blob(version)
    arch_value = blob(arch)

    def obj(values: list[int]) -> int:
        offset = len(payload)
        payload.extend(struct.pack(f"<{len(values)}I", *values))
        return generate_configs.ADB_TYPE_OBJECT | offset

    pkginfo_value = obj([6, name_value, version_value, 0, 0, arch_value])
    root_value = obj([2, pkginfo_value])
    struct.pack_into("<I", payload, 4, root_value)

    block_raw_size = 4 + len(payload)
    block = struct.pack("<I", block_raw_size) + bytes(payload)
    padding = b"\x00" * ((8 - len(block) % 8) % 8)
    adb = (
        generate_configs.ADB_FORMAT_MAGIC
        + struct.pack("<I", generate_configs.ADB_SCHEMA_PACKAGE)
        + block
        + padding
    )
    return generate_configs.ADB_COMPRESSED_DEFLATE_MAGIC + raw_deflate(adb)


class ApkMetadataTests(unittest.TestCase):
    @staticmethod
    def write_apk(tmp: Path, name: str, version: str, arch: str) -> Path:
        path = tmp / f"{name}.apk"
        path.write_bytes(package_fixture(name, version, arch))
        return path

    def test_reads_adbd_package_metadata_without_apk_tool(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            apk = self.write_apk(
                Path(raw), "luci-proto-amneziawg", "2.2.0-r1", "noarch"
            )

            meta = generate_configs.apk_metadata(apk)

        self.assertEqual(meta.name, "luci-proto-amneziawg")
        self.assertEqual(meta.version, "2.2.0-r1")
        self.assertEqual(meta.arch, "noarch")

    def test_builds_canonical_name_from_embedded_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            apk = self.write_apk(
                Path(raw),
                "kmod-amneziawg",
                "6.12.87.1.0.20260329-r1",
                "aarch64_cortex-a53",
            )

            self.assertEqual(
                generate_configs.apk_canonical_name(apk, "aarch64_cortex-a53"),
                "kmod-amneziawg-6.12.87.1.0.20260329-r1.apk",
            )

    def test_rejects_unexpected_package_arch(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            apk = self.write_apk(
                Path(raw),
                "kmod-amneziawg",
                "6.12.87.1.0.20260329-r1",
                "aarch64_cortex-a53",
            )

            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(
                SystemExit
            ):
                generate_configs.apk_canonical_name(apk, "mipsel_24kc")


if __name__ == "__main__":
    unittest.main()
