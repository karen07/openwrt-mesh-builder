#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from tools.cli_common import git_short_hash


class NativeCliCommonTests(unittest.TestCase):
    def test_git_short_hash_reads_loose_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git_dir = root / ".git"
            ref = git_dir / "refs" / "heads" / "main"
            ref.parent.mkdir(parents=True)
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            ref.write_text("0123456789abcdef\n", encoding="utf-8")

            self.assertEqual(git_short_hash(root), "0123456")

    def test_git_short_hash_reads_packed_ref(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            git_dir = root / ".git"
            git_dir.mkdir()
            (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
            (git_dir / "packed-refs").write_text(
                "# pack-refs\nabcdef0123456789 refs/heads/main\n",
                encoding="utf-8",
            )

            self.assertEqual(git_short_hash(root), "abcdef0")


if __name__ == "__main__":
    unittest.main()
