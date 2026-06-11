from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "cairn" / "src"))

os.environ.setdefault("CAIRN_JWT_SECRET", "test-jwt-secret-do-not-use-in-prod-32bytes")
os.environ.setdefault("CAIRN_SECRETS_KEY", "test-jwt-secret-do-not-use-in-prod-32bytes")


class CairnClientRetryTests(unittest.TestCase):
    def _make_client(self):
        from cairn.dispatcher.protocol.client import CairnClient

        return CairnClient("http://example.invalid")

    def test_get_retries_on_5xx(self) -> None:
        """GET should retry on 5xx; the third attempt returns 200."""
        client = self._make_client()
        success = MagicMock(status_code=200)
        fail = MagicMock(status_code=503)
        # Avoid the exception path: 503 will raise HTTPError, which
        # is what tenacity catches and retries.
        with patch.object(client, "_session") as session:
            session.return_value.get.side_effect = [fail, fail, success]
            with patch("time.sleep", lambda *_a, **_k: None):  # speed up backoff
                response = client._get("/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.return_value.get.call_count, 3)

    def test_get_does_not_retry_on_4xx(self) -> None:
        """A 4xx is not retryable; one GET attempt only."""
        client = self._make_client()
        not_found = MagicMock(status_code=404)
        with patch.object(client, "_session") as session:
            session.return_value.get.return_value = not_found
            response = client._get("/projects")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(session.return_value.get.call_count, 1)

    def test_get_retries_on_network_error(self) -> None:
        """``ConnectionError`` / ``Timeout`` should also retry."""
        import requests as real_requests

        client = self._make_client()
        success = MagicMock(status_code=200)
        with patch.object(client, "_session") as session:
            session.return_value.get.side_effect = [
                real_requests.ConnectionError("boom"),
                success,
            ]
            with patch("time.sleep", lambda *_a, **_k: None):
                response = client._get("/projects")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(session.return_value.get.call_count, 2)

    def test_post_does_not_retry(self) -> None:
        """POSTs are not retried: a 503 must surface on the first call."""
        client = self._make_client()
        fail = MagicMock(status_code=503)
        fail.headers = {"content-type": "application/json"}
        fail.json.return_value = {"detail": "boom"}
        with patch.object(client, "_session") as session:
            session.return_value.request.return_value = fail
            result = client._request_json("POST", "/projects", json={"x": 1})
        self.assertEqual(result.status_code, 503)
        self.assertEqual(session.return_value.request.call_count, 1)

    def test_observability_requests_use_short_timeout(self) -> None:
        client = self._make_client()
        success = MagicMock(status_code=201)
        success.headers = {"content-type": "application/json"}
        success.content = b'{"events":[],"dropped":0}'
        success.text = '{"events":[],"dropped":0}'
        success.json.return_value = {"events": [], "dropped": 0}
        with patch.object(client, "_session") as session:
            session.return_value.request.return_value = success
            result = client.create_llm_events("proj_001", "exec_1", [])
        self.assertEqual(result.status_code, 201)
        self.assertEqual(session.return_value.request.call_args.kwargs["timeout"], 2.0)


if __name__ == "__main__":
    unittest.main()
