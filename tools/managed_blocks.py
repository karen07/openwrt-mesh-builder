from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

try:
    from .common import decrypt_owmb_text, has_any_owmb_marker
    from .uci import normalize_uci, parse_uci_block, split_uci_blocks
except ImportError:
    from common import decrypt_owmb_text, has_any_owmb_marker  # type: ignore
    from uci import normalize_uci, parse_uci_block, split_uci_blocks  # type: ignore


def owmb_compare_text(text: str, *, where: str = "managed_blocks") -> str:
    # OWMB encrypted markers use fresh nonces.  Managed block comparisons must
    # compare the decrypted representation, while callers still print or write
    # the original on-disk text when reporting unmanaged content.
    if has_any_owmb_marker(text):
        return decrypt_owmb_text(text, where=where)
    return text


def strip_outer_blank_lines(lines: list[str]) -> list[str]:
    out = list(lines)
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def strip_exact_text_block_once(
    lines: list[str],
    block: str,
    *,
    where: str = "managed_blocks",
) -> tuple[list[str], bool]:
    block_lines = block.rstrip("\n").splitlines()
    if not block_lines:
        return list(lines), False

    out: list[str] = []
    i = 0
    removed = False
    expected_cmp = owmb_compare_text("\n".join(block_lines), where=where).strip("\n")

    while i < len(lines):
        candidate = lines[i : i + len(block_lines)]
        candidate_cmp = owmb_compare_text("\n".join(candidate), where=where).strip("\n")
        if not removed and candidate_cmp == expected_cmp:
            i += len(block_lines)
            removed = True
            continue
        out.append(lines[i])
        i += 1

    return out, removed


def strip_exact_text_blocks(
    lines: list[str],
    blocks: Iterable[str],
    *,
    where: str = "managed_blocks",
) -> list[str]:
    out = strip_outer_blank_lines(list(lines))
    for block in blocks:
        out, _removed = strip_exact_text_block_once(out, block, where=where)
        out = strip_outer_blank_lines(out)
    return strip_outer_blank_lines(out)


def uci_block_key(block: str) -> str:
    # Ignore only inter-block separator newlines.  The bytes inside the UCI
    # block itself, including indentation, option order and values, must match
    # after OWMB ciphertext is normalized by uci_compare_key().
    return block.strip("\n")


def uci_compare_key(block: str, *, where: str = "managed_blocks") -> str:
    return uci_block_key(owmb_compare_text(block, where=where))


def uci_counter_from_text(
    text: str,
    *,
    where: str = "managed_blocks",
) -> Counter[str]:
    out: Counter[str] = Counter()
    normalized = normalize_uci(text)

    for block in split_uci_blocks(normalized):
        if parse_uci_block(block):
            out[uci_compare_key(block, where=where)] += 1

    return out


def consume_expected_uci_block(
    expected: Counter[str],
    block: str,
    *,
    where: str = "managed_blocks",
) -> bool:
    key = uci_compare_key(block, where=where)
    if expected.get(key, 0) <= 0:
        return False
    expected[key] -= 1
    return True


def collect_unmanaged_uci_blocks(
    text_before_marker: str,
    expected: Counter[str],
    *,
    where: str = "managed_blocks",
) -> list[str]:
    out: list[str] = []

    for block in split_uci_blocks(text_before_marker):
        key = uci_block_key(block)
        if not key.strip():
            continue

        if consume_expected_uci_block(expected, block, where=where):
            continue

        out.append(key.rstrip())

    return out


def normalize_uci_part(text: str) -> str:
    return normalize_uci(text).strip("\n")


def render_marked_uci_text(
    generated_parts: Iterable[str],
    preserved_before: str,
    marker_and_tail: str,
    *,
    leading_newline: bool = False,
    normalize_generated: bool = True,
    normalize_result: bool = True,
) -> str:
    parts: list[str] = []

    for part in generated_parts:
        rendered = normalize_uci_part(part) if normalize_generated else part.strip("\n")
        if rendered:
            parts.append(rendered)

    preserved = preserved_before.strip("\n")
    if preserved:
        parts.append(preserved)

    marker_tail = marker_and_tail.strip("\n")
    if marker_tail:
        parts.append(marker_tail)

    text = "\n\n".join(parts).rstrip()
    if not text:
        return ""

    text = ("\n" if leading_newline else "") + text + "\n"
    return normalize_uci(text) if normalize_result else text
