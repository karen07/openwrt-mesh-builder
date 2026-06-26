#!/usr/bin/env python3
import sys

sys.dont_write_bytecode = True
from pathlib import Path

try:
    from .process import die, need, run_captured
except ImportError:
    from process import die, need, run_captured


def _curl_base(max_time: int) -> list[str]:
    need("curl")
    return [
        "curl",
        "-fL",
        "--retry",
        "3",
        "--connect-timeout",
        "15",
        "--max-time",
        str(max_time),
    ]


def download_file(url: str, dst: Path, *, max_time: int = 300) -> None:
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = run_captured([*_curl_base(max_time), "-o", str(tmp), url])
    if result.returncode != 0:
        tmp.unlink(missing_ok=True)
        err = result.stderr.strip() or result.stdout.strip()
        die(f"failed to download {url}: {err or 'curl failed'}")
    if not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        die(f"failed to download {url}: empty response")
    tmp.replace(dst)


def try_download_file(url: str, dst: Path, *, max_time: int = 300) -> bool:
    tmp = dst.with_suffix(dst.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    dst.parent.mkdir(parents=True, exist_ok=True)
    result = run_captured([*_curl_base(max_time), "-o", str(tmp), url])
    if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(dst)
    return True


def download_text(url: str, *, max_time: int = 60) -> str:
    result = run_captured(_curl_base(max_time) + [url])
    if result.returncode != 0:
        err = result.stderr.strip() or result.stdout.strip()
        die(f"failed to download {url}: {err or 'curl failed'}")
    return result.stdout


def download_text_lines(url: str, *, max_time: int = 60) -> list[str]:
    return download_text(url, max_time=max_time).splitlines()
