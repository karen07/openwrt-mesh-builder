#!/usr/bin/env python3
import base64
import unittest

from tools.common import gen_private_key, public_key_from_private


class WireGuardKeyTests(unittest.TestCase):
    def test_public_key_matches_rfc7748_x25519_vector(self) -> None:
        private_key = "dwdtCnMYpX08FsFyUbJmRd9ML4frwJkqsXf7pR25LCo="

        self.assertEqual(
            public_key_from_private(private_key),
            "hSDwCYkwp1R0i33ctD73Wg2/Og0mOBr066SpjqqbTmo=",
        )

    def test_generated_private_key_is_base64_32_bytes(self) -> None:
        raw = base64.b64decode(gen_private_key(), validate=True)

        self.assertEqual(len(raw), 32)


if __name__ == "__main__":
    unittest.main()
