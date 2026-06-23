#!/usr/bin/env python3
import unittest
from unittest.mock import patch

from tools.cli_common import urlopen_insecure


class DownloadSslTests(unittest.TestCase):
    def test_urlopen_insecure_passes_ssl_context(self) -> None:
        with patch("tools.cli_common.urllib.request.urlopen") as urlopen:
            urlopen_insecure("https://example.test/file", timeout=12)

        _args, kwargs = urlopen.call_args
        self.assertEqual(kwargs["timeout"], 12)
        self.assertIsNotNone(kwargs["context"])


if __name__ == "__main__":
    unittest.main()
