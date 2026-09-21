import json
import unittest
from unittest.mock import patch

from mdlp_client import MDLPClient, MDLPConfig, MDLPError


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit):
        return json.dumps(self.payload).encode("utf-8")


class MDLPClientTests(unittest.TestCase):
    def test_public_sgtin_request_uses_sandbox_and_token(self):
        config = MDLPConfig(
            enabled=True,
            base_url="https://api.sb.mdlp.crpt.ru",
            token="test-token",
            timeout=3,
            max_response_bytes=1024,
        )
        client = MDLPClient(config)

        with patch("mdlp_client.urllib.request.urlopen") as urlopen:
            urlopen.return_value = _Response({
                "total": 1,
                "failed": 0,
                "entries": [{"sgtin": "04601234567893ABC1234567890", "status": "in_circulation"}],
            })
            result = client.find_public_sgtin("04601234567893ABC1234567890")

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.sb.mdlp.crpt.ru/api/v1/reestr/sgtin/public/sgtins-by-list")
        self.assertEqual(request.get_header("Authorization"), "token test-token")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"filter": {"sgtins": ["04601234567893ABC1234567890"]}},
        )
        self.assertEqual(result["status"], "in_circulation")

    def test_missing_token_is_auth_error(self):
        client = MDLPClient(MDLPConfig(True, "https://api.sb.mdlp.crpt.ru", None, 3, 1024))
        with self.assertRaises(MDLPError) as ctx:
            client.find_public_sgtin("04601234567893ABC1234567890")
        self.assertEqual(ctx.exception.kind, "auth")


if __name__ == "__main__":
    unittest.main()
