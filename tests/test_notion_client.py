"""Unit tests for NotionClient — focus on error observability."""

import logging

import pytest
import requests

from clients.notion_client import NotionClient


class TestNotionErrorLogging:
    """On a non-2xx response the API error body must be logged before raising."""

    def test_query_error_body_is_logged(self, mocker, caplog):
        client = NotionClient()

        resp = mocker.MagicMock()
        resp.ok = False
        resp.status_code = 400
        resp.text = '{"message":"validation_error: bad filter","code":"validation_error"}'
        resp.raise_for_status = mocker.MagicMock(
            side_effect=requests.exceptions.HTTPError("400 Client Error")
        )
        mocker.patch.object(client.session, "request", return_value=resp)

        caplog.set_level(logging.ERROR)
        with pytest.raises(requests.exceptions.HTTPError):
            client.get_stale_notes("2024-01-01T00:00:00Z")

        assert "validation_error: bad filter" in caplog.text
        # The operational context should be identifiable.
        assert "get_stale_notes" in caplog.text

    def test_query_success_returns_results(self, mocker):
        client = NotionClient()

        resp = mocker.MagicMock()
        resp.ok = True
        resp.raise_for_status = mocker.MagicMock()
        resp.json.return_value = {"results": [{"id": "abc"}]}
        mocker.patch.object(client.session, "request", return_value=resp)

        notes = client.get_stale_notes("2024-01-01T00:00:00Z", limit=5)
        assert notes == [{"id": "abc"}]


class TestTransientRetries:
    """Transient upstream failures are retried inside a bounded time budget."""

    @staticmethod
    def _response(mocker, status_code, *, json_data=None, headers=None):
        resp = mocker.MagicMock()
        resp.status_code = status_code
        resp.ok = status_code < 400
        resp.text = f"HTTP {status_code} body"
        resp.headers = headers or {}
        resp.json.return_value = json_data if json_data is not None else {}
        resp.raise_for_status = mocker.MagicMock(
            side_effect=(
                requests.exceptions.HTTPError(f"{status_code} Error")
                if status_code >= 400
                else None
            )
        )
        return resp

    @staticmethod
    def _client(mocker, *, budget=100.0, max_attempts=10):
        """Client whose clock only advances when the code sleeps."""
        clock = [0.0]
        client = NotionClient(
            retry_budget_seconds=budget,
            max_attempts=max_attempts,
            sleep=lambda s: clock.__setitem__(0, clock[0] + s),
            monotonic=lambda: clock[0],
        )
        return client, clock

    def test_block_children_retries_502_then_succeeds(self, mocker):
        client, _clock = self._client(mocker)
        bad = self._response(mocker, 502)
        good = self._response(mocker, 200, json_data={"results": [], "has_more": False})
        req = mocker.patch.object(client.session, "request", side_effect=[bad, good])

        assert client.get_block_children("page-1") == []
        assert req.call_count == 2

    def test_retries_until_budget_exhausted_then_raises(self, mocker):
        client, clock = self._client(mocker, budget=100.0)
        bad = self._response(mocker, 503)
        req = mocker.patch.object(client.session, "request", return_value=bad)

        with pytest.raises(requests.exceptions.HTTPError):
            client.get_block_children("page-1")
        # Backoff sleeps 1+2+4+8+16+30+30 = 91s; the next 30s delay does not
        # fit the ~9s remaining, so the loop gives up — bounded, never endless.
        assert req.call_count == 8
        assert clock[0] == 91.0

    def test_non_transient_status_is_not_retried(self, mocker):
        client, _clock = self._client(mocker)
        bad = self._response(mocker, 400)
        req = mocker.patch.object(client.session, "request", return_value=bad)

        with pytest.raises(requests.exceptions.HTTPError):
            client.get_block_children("page-1")
        assert req.call_count == 1

    def test_transport_error_is_retried(self, mocker):
        client, _clock = self._client(mocker)
        good = self._response(mocker, 200, json_data={"results": [], "has_more": False})
        req = mocker.patch.object(
            client.session,
            "request",
            side_effect=[requests.exceptions.ConnectionError("reset"), good],
        )

        assert client.get_block_children("page-1") == []
        assert req.call_count == 2

    def test_retry_after_header_sets_delay(self, mocker):
        client, clock = self._client(mocker, budget=100.0)
        limited = self._response(mocker, 429, headers={"Retry-After": "7"})
        good = self._response(mocker, 200, json_data={"results": [], "has_more": False})
        mocker.patch.object(client.session, "request", side_effect=[limited, good])

        assert client.get_block_children("page-1") == []
        assert clock[0] == 7.0

    def test_retry_after_beyond_budget_gives_up_without_sleeping(self, mocker):
        client, clock = self._client(mocker, budget=100.0)
        limited = self._response(mocker, 429, headers={"Retry-After": "500"})
        req = mocker.patch.object(client.session, "request", return_value=limited)

        with pytest.raises(requests.exceptions.HTTPError):
            client.get_block_children("page-1")
        assert req.call_count == 1
        assert clock[0] == 0.0

    def test_max_attempts_caps_retries(self, mocker):
        client, _clock = self._client(mocker, budget=10000.0, max_attempts=3)
        bad = self._response(mocker, 502)
        req = mocker.patch.object(client.session, "request", return_value=bad)

        with pytest.raises(requests.exceptions.HTTPError):
            client.get_block_children("page-1")
        assert req.call_count == 3

    def test_stale_notes_query_retries_transient_post(self, mocker):
        client, _clock = self._client(mocker)
        bad = self._response(mocker, 502)
        good = self._response(mocker, 200, json_data={"results": [{"id": "n1"}]})
        req = mocker.patch.object(client.session, "request", side_effect=[bad, good])

        notes = client.get_stale_notes("2024-01-01T00:00:00Z")
        assert notes == [{"id": "n1"}]
        assert req.call_count == 2
