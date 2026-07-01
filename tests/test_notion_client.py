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
        mocker.patch.object(client.session, "post", return_value=resp)

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
        mocker.patch.object(client.session, "post", return_value=resp)

        notes = client.get_stale_notes("2024-01-01T00:00:00Z", limit=5)
        assert notes == [{"id": "abc"}]
