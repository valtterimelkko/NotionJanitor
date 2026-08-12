"""Tests for the Pi Web UI Internal API summariser."""

import asyncio
import json

import httpx
import pytest

from clients.pi_summariser import (
    PI_SUMMARISER_MODEL,
    PI_SUMMARISER_THINKING_LEVEL,
    PiInternalApiError,
    PiInternalApiSummariser,
)


CAPABILITIES = {
    "status": "ok",
    "contract": {
        "name": "pi-web-ui-internal-api",
        "routePrefix": "/api/v1",
        "majorVersion": "v1",
        "contractVersion": "1.19.0",
    },
    "features": {"piProviderPolicy": {"blockedProviders": ["openai", "openrouter"]}},
    "runtimes": {
        "pi": {
            "available": True,
            "supportsThinkingLevel": True,
        }
    },
}

MODELS = {
    "models": {
        "pi": [
            {
                "id": "gpt-5.6-luna",
                "provider": "openai-codex",
                "thinkingLevels": ["off", "minimal", "low", "medium", "high", "xhigh", "max"],
            }
        ]
    }
}

CAPACITY = {"available": True, "activeTurns": 0, "apiTurnLimit": 5}


def json_response(payload: dict, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


def make_client(handler):
    return httpx.AsyncClient(
        base_url="http://localhost",
        transport=httpx.MockTransport(handler),
    )


def test_summarise_uses_codex_luna_medium_and_cleans_up_session():
    calls = []
    transcript_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path, request.url.query, request.content))
        body = json.loads(request.content or b"{}")

        if request.method == "GET" and request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.method == "GET" and request.url.path == "/api/v1/models":
            assert request.url.query == b"runtime=pi"
            return json_response(MODELS)
        if request.method == "GET" and request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        if request.method == "POST" and request.url.path == "/api/v1/sessions":
            assert body == {
                "runtime": "pi",
                "cwd": "/tmp/notion-janitor-summariser",
                "model": PI_SUMMARISER_MODEL,
                "thinkingLevel": PI_SUMMARISER_THINKING_LEVEL,
            }
            return json_response({"sessionId": "session-1"}, 201)
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-1/info":
            return json_response({
                "sessionId": "session-1",
                "runtime": "pi",
                "model": PI_SUMMARISER_MODEL,
                "thinkingLevel": PI_SUMMARISER_THINKING_LEVEL,
            })
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-1/control":
            assert body == {"action": "set_thinking_level", "level": "medium"}
            return json_response({"success": True, "action": "set_thinking_level", "level": "medium"})
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-1/prompt":
            assert body["verbosity"] == "answers"
            assert body["detach"] is True
            assert body["idempotencyKey"].startswith("notionjanitor-summary-")
            assert "A note title" in body["message"]
            assert "A note body" in body["message"]
            return json_response(
                {"sessionId": "session-1", "runId": "run-1", "detached": True, "status": "accepted"},
                202,
            )
        if request.method == "GET" and request.url.path == "/api/v1/runs/run-1":
            return json_response(
                {
                    "runId": "run-1",
                    "sessionId": "session-1",
                    "status": "completed",
                    "model": PI_SUMMARISER_MODEL,
                    "outputEvidence": {"disposition": "text"},
                }
            )
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-1/transcript":
            nonlocal transcript_calls
            transcript_calls += 1
            assert request.url.query == b"scope=visible_full"
            items = [{"kind": "user", "text": "prompt"}]
            if transcript_calls == 1:
                return json_response({"error": "Transcript not available yet", "code": "EMPTY_TRANSCRIPT"}, 404)
            items.append({"kind": "assistant", "text": "A concise summary of the note."})
            return json_response({"sessionId": "session-1", "items": items})
        if request.method == "DELETE" and request.url.path == "/api/v1/sessions/session-1":
            return json_response({"success": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(
            http_client=make_client(handler),
            cwd="/tmp/notion-janitor-summariser",
            poll_interval_seconds=0,
        )
        try:
            return await summariser.summarise_note("A note title", "A note body")
        finally:
            await summariser.aclose()

    result = asyncio.run(scenario())

    assert result == "A concise summary of the note."
    assert [call[:2] for call in calls] == [
        ("GET", "/api/v1/capabilities"),
        ("GET", "/api/v1/models"),
        ("GET", "/api/v1/capacity"),
        ("POST", "/api/v1/sessions"),
        ("GET", "/api/v1/sessions/session-1/info"),
        ("POST", "/api/v1/sessions/session-1/control"),
        ("POST", "/api/v1/sessions/session-1/prompt"),
        ("GET", "/api/v1/runs/run-1"),
        ("GET", "/api/v1/sessions/session-1/transcript"),
        ("GET", "/api/v1/sessions/session-1/transcript"),
        ("DELETE", "/api/v1/sessions/session-1"),
    ]


def test_startup_validation_rejects_a_model_with_a_mismatched_provider():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.url.path == "/api/v1/models":
            return json_response({
                "models": {
                    "pi": [{"id": PI_SUMMARISER_MODEL, "provider": "openai"}],
                }
            })
        if request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(http_client=make_client(handler), poll_interval_seconds=0)
        try:
            with pytest.raises(PiInternalApiError, match="openai-codex/gpt-5.6-luna"):
                await summariser.ensure_ready()
        finally:
            await summariser.aclose()

    asyncio.run(scenario())


def test_startup_validation_rejects_a_non_codex_model():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.url.path == "/api/v1/models":
            return json_response({"models": {"pi": [{"id": "gpt-5.6-luna", "provider": "openai"}]}})
        if request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(http_client=make_client(handler), poll_interval_seconds=0)
        try:
            with pytest.raises(PiInternalApiError, match="openai-codex/gpt-5.6-luna"):
                await summariser.ensure_ready()
        finally:
            await summariser.aclose()

    asyncio.run(scenario())


def test_completed_run_requires_exact_model_identity():
    summariser = PiInternalApiSummariser(http_client=make_client(lambda request: json_response({})))
    try:
        with pytest.raises(PiInternalApiError, match="unexpected model/provider"):
            summariser._validate_completed_receipt({"status": "completed"})
    finally:
        asyncio.run(summariser.aclose())


def test_effective_session_model_is_verified_before_prompt_dispatch():
    prompt_called = False
    deleted = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal prompt_called, deleted
        if request.method == "GET" and request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.method == "GET" and request.url.path == "/api/v1/models":
            return json_response(MODELS)
        if request.method == "GET" and request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        if request.method == "POST" and request.url.path == "/api/v1/sessions":
            return json_response({"sessionId": "session-wrong-model"}, 201)
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-wrong-model/info":
            return json_response({
                "sessionId": "session-wrong-model",
                "runtime": "pi",
                "model": "openai/gpt-5.5",
            })
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-wrong-model/prompt":
            prompt_called = True
            raise AssertionError("prompt must not be dispatched for a wrong effective model")
        if request.method == "DELETE" and request.url.path == "/api/v1/sessions/session-wrong-model":
            deleted = True
            return json_response({"success": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(http_client=make_client(handler))
        try:
            with pytest.raises(PiInternalApiError, match="unexpected effective model"):
                await summariser.summarise_note("Title", "Content")
        finally:
            await summariser.aclose()

    asyncio.run(scenario())
    assert prompt_called is False
    assert deleted is True


def test_failed_run_still_deletes_the_ephemeral_session():
    deleted = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal deleted
        if request.method == "GET" and request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.method == "GET" and request.url.path == "/api/v1/models":
            return json_response(MODELS)
        if request.method == "GET" and request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        if request.method == "POST" and request.url.path == "/api/v1/sessions":
            return json_response({"sessionId": "session-failed"}, 201)
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-failed/info":
            return json_response({"sessionId": "session-failed", "runtime": "pi", "model": PI_SUMMARISER_MODEL})
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-failed/control":
            return json_response({"success": True, "action": "set_thinking_level", "level": "medium"})
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-failed/prompt":
            return json_response(
                {"sessionId": "session-failed", "runId": "run-failed", "detached": True, "status": "accepted"},
                202,
            )
        if request.method == "GET" and request.url.path == "/api/v1/runs/run-failed":
            return json_response({"runId": "run-failed", "status": "failed", "errorCode": "RUNTIME_ERROR"})
        if request.method == "DELETE" and request.url.path == "/api/v1/sessions/session-failed":
            deleted = True
            return json_response({"success": True})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(http_client=make_client(handler), poll_interval_seconds=0)
        try:
            with pytest.raises(PiInternalApiError, match="RUNTIME_ERROR"):
                await summariser.summarise_note("Title", "Content")
        finally:
            await summariser.aclose()

    asyncio.run(scenario())

    assert deleted is True


def test_cleanup_failure_is_reported_after_a_successful_summary():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/v1/capabilities":
            return json_response(CAPABILITIES)
        if request.method == "GET" and request.url.path == "/api/v1/models":
            return json_response(MODELS)
        if request.method == "GET" and request.url.path == "/api/v1/capacity":
            return json_response(CAPACITY)
        if request.method == "POST" and request.url.path == "/api/v1/sessions":
            return json_response({"sessionId": "session-cleanup"}, 201)
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-cleanup/info":
            return json_response({"sessionId": "session-cleanup", "runtime": "pi", "model": PI_SUMMARISER_MODEL})
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-cleanup/control":
            return json_response({"success": True, "level": "medium"})
        if request.method == "POST" and request.url.path == "/api/v1/sessions/session-cleanup/prompt":
            return json_response({"sessionId": "session-cleanup", "runId": "run-cleanup", "detached": True, "status": "accepted"}, 202)
        if request.method == "GET" and request.url.path == "/api/v1/runs/run-cleanup":
            return json_response({
                "runId": "run-cleanup",
                "sessionId": "session-cleanup",
                "status": "completed",
                "model": PI_SUMMARISER_MODEL,
                "outputEvidence": {"disposition": "text"},
            })
        if request.method == "GET" and request.url.path == "/api/v1/sessions/session-cleanup/transcript":
            return json_response({"sessionId": "session-cleanup", "items": [{"kind": "assistant", "text": "Summary."}]})
        if request.method == "DELETE" and request.url.path == "/api/v1/sessions/session-cleanup":
            return json_response({"error": "temporary failure", "code": "INTERNAL_ERROR"}, 500)
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    async def scenario():
        summariser = PiInternalApiSummariser(
            http_client=make_client(handler),
            poll_interval_seconds=0,
            max_retries=0,
        )
        try:
            with pytest.raises(PiInternalApiError, match="cleanup"):
                await summariser.summarise_note("Title", "Content")
        finally:
            await summariser.aclose()

    asyncio.run(scenario())


def test_working_directory_symlinks_are_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "summariser"
    link.symlink_to(target, target_is_directory=True)

    summariser = PiInternalApiSummariser(cwd=link)
    with pytest.raises(PiInternalApiError, match="symlink"):
        summariser._ensure_secure_cwd()
