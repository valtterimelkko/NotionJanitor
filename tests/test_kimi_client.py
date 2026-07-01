"""Unit tests for KimiClient — focus on error observability."""

import logging

import pytest
import requests

from clients.kimi_client import KimiClient


class TestSummariseErrorLogging:
    """On a non-2xx response the API error body must be logged before raising.

    Regression guard: the original Kimi temperature outage was invisible because
    raise_for_status() discarded the response body that contained the diagnosis.
    """

    def test_error_body_is_logged_before_raising(self, mocker, caplog):
        client = KimiClient()

        resp = mocker.MagicMock()
        resp.ok = False
        resp.status_code = 400
        resp.text = '{"error":{"message":"invalid temperature: only 1 is allowed"}}'
        resp.raise_for_status = mocker.MagicMock(
            side_effect=requests.exceptions.HTTPError("400 Client Error")
        )
        mocker.patch.object(client.session, "post", return_value=resp)

        caplog.set_level(logging.ERROR)
        with pytest.raises(requests.exceptions.HTTPError):
            client.summarise_note("Some title", "Some content")

        # The actual diagnostic from the API must appear in the logs.
        assert "invalid temperature: only 1 is allowed" in caplog.text
        assert "400" in caplog.text

    def test_success_path_returns_summary(self, mocker):
        client = KimiClient()

        resp = mocker.MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.raise_for_status = mocker.MagicMock()
        resp.json.return_value = {
            "choices": [{"message": {"content": "A one-sentence summary."}}]
        }
        mocker.patch.object(client.session, "post", return_value=resp)

        assert client.summarise_note("Title", "Content") == "A one-sentence summary."
