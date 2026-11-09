"""Notion API client for Ultimate Brain (Second Brain) operations."""

import logging
import time

import requests

from config import (
    NOTION_API_BASE,
    NOTION_DATABASE_ID,
    NOTION_RETRY_BUDGET_SECONDS,
    NOTION_TOKEN,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

# Statuses worth retrying: rate limiting and transient gateway/server errors.
# Notion intermittently answers with 502/503 HTML error pages; without a retry
# a single blip drops a note from the weekly batch.
TRANSIENT_STATUS_CODES = frozenset({429, 500, 502, 503, 504})

# Transport-level failures that are safe to retry.
TRANSIENT_REQUEST_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

# Backoff doubles from 1s up to this cap; the retry window itself is bounded
# by NOTION_RETRY_BUDGET_SECONDS so a dead upstream delays a call by about
# two minutes at most — robustness without an endless loop.
RETRY_BACKOFF_CAP_SECONDS = 30.0
DEFAULT_RETRY_MAX_ATTEMPTS = 10


def _retry_after_seconds(resp) -> float | None:
    """Parse a Retry-After header (delta-seconds form) into seconds."""
    raw = resp.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


class NotionClient:
    """Wraps the Notion API to match the behaviour of the n8n Notion nodes."""

    def __init__(
        self,
        *,
        retry_budget_seconds: float = NOTION_RETRY_BUDGET_SECONDS,
        max_attempts: int = DEFAULT_RETRY_MAX_ATTEMPTS,
        sleep=time.sleep,
        monotonic=time.monotonic,
    ):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self.retry_budget_seconds = max(0.0, retry_budget_seconds)
        self.max_attempts = max(1, max_attempts)
        self._sleep = sleep
        self._monotonic = monotonic

    def _retry_delay(self, attempt: int, resp: requests.Response | None) -> float:
        """Seconds before the next attempt: Retry-After when offered, else backoff."""
        if resp is not None:
            retry_after = _retry_after_seconds(resp)
            if retry_after is not None:
                return max(1.0, retry_after)
        return min(2 ** (attempt - 1), RETRY_BACKOFF_CAP_SECONDS)

    def _request(self, method: str, url: str, *, context: str, **kwargs) -> requests.Response:
        """Issue an API call, retrying transient failures inside a bounded window.

        Every Notion call goes through here so a transient upstream error can
        never silently drop a note (or abort the whole scan). Retries 429/5xx
        statuses and transient transport errors with exponential backoff until
        retry_budget_seconds elapses — about two minutes by default, capped by
        max_attempts, never an endless loop.
        """
        deadline = self._monotonic() + self.retry_budget_seconds
        attempt = 0
        while True:
            attempt += 1
            try:
                resp = self.session.request(method, url, **kwargs)
                transient_exc = None
            except TRANSIENT_REQUEST_ERRORS as exc:
                resp = None
                transient_exc = exc

            if transient_exc is None and resp.status_code not in TRANSIENT_STATUS_CODES:
                self._check(resp, context)
                return resp

            if attempt >= self.max_attempts:
                break

            delay = self._retry_delay(attempt, resp)
            remaining = deadline - self._monotonic()
            if delay > remaining:
                break

            if transient_exc is not None:
                what = f"{type(transient_exc).__name__}: {transient_exc}"
            else:
                what = f"HTTP {resp.status_code}"
            logger.warning(
                "Retrying Notion %s (%s) after %s on attempt %d in %.1fs (%.0fs budget left)",
                context, method, what, attempt, delay, remaining,
            )
            self._sleep(delay)

        # Out of budget or attempts: surface the last failure exactly as an
        # un-retried call would have.
        if transient_exc is not None:
            raise transient_exc
        self._check(resp, context)
        return resp

    @staticmethod
    def _check(resp, context: str) -> None:
        """Raise for HTTP errors, but log the upstream body first.

        raise_for_status() alone discards the response body, which is where
        Notion puts the diagnostic (e.g. validation_error details). Logging it
        here makes outages self-diagnosing in the logs.
        """
        if not resp.ok:
            logger.error(
                "Notion API error %s during %s: %s",
                resp.status_code,
                context,
                resp.text[:1000],
            )
        resp.raise_for_status()

    # ------------------------------------------------------------------
    # Database queries
    # ------------------------------------------------------------------
    def get_stale_notes(
        self,
        cutoff_iso: str,
        limit: int = 13,
        orphans_only: bool | None = None,
    ) -> list[dict]:
        """Query the Notes database for notes not edited since *cutoff_iso*.

        orphans_only controls project filtering:
            None  — no project filter (all stale notes)
            True  — only notes WITHOUT a Project relation (orphans)
            False — only notes WITH a Project relation
        """
        url = f"{NOTION_API_BASE}/databases/{NOTION_DATABASE_ID}/query"
        filters: list[dict] = [
            {
                "property": "Archived",
                "checkbox": {"does_not_equal": True},
            },
            {
                "timestamp": "last_edited_time",
                "last_edited_time": {"before": cutoff_iso},
            },
        ]
        if orphans_only is True:
            filters.append({"property": "Project", "relation": {"is_empty": True}})
        elif orphans_only is False:
            filters.append({"property": "Project", "relation": {"is_not_empty": True}})

        payload = {
            "filter": {"and": filters},
            "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
            "page_size": limit,
        }
        resp = self._request("POST", url, context="get_stale_notes", json=payload)
        results = resp.json().get("results", [])
        logger.info(
            "Found %d stale notes (limit %d, orphans_only=%s)",
            len(results), limit, orphans_only,
        )
        return results

    # ------------------------------------------------------------------
    # Page / relation helpers
    # ------------------------------------------------------------------
    def get_page(self, page_id: str) -> dict:
        """Fetch a single page (used to resolve project relation)."""
        url = f"{NOTION_API_BASE}/pages/{page_id}"
        resp = self._request("GET", url, context="get_page")
        return resp.json()

    def get_project_name(self, note: dict) -> str:
        """Extract the first project name from the 'Project' relation.

        Returns 'No Project' if the note has no project relation.
        """
        try:
            relations = note["properties"]["Project"]["relation"]
            if not relations:
                return "No Project"
            project_page = self.get_page(relations[0]["id"])
            return (
                project_page.get("properties", {})
                .get("Name", {})
                .get("title", [{}])[0]
                .get("plain_text", "Unknown Project")
            )
        except Exception as exc:
            logger.warning("Could not resolve project name: %s", exc)
            return "No Project"

    # ------------------------------------------------------------------
    # Content blocks
    # ------------------------------------------------------------------
    def get_block_children(self, block_id: str) -> list[dict]:
        """Fetch all content blocks for a page/block (with nested children)."""
        blocks: list[dict] = []
        url = f"{NOTION_API_BASE}/blocks/{block_id}/children"
        has_more = True
        while has_more:
            resp = self._request("GET", url, context="get_block_children")
            data = resp.json()
            for block in data.get("results", []):
                blocks.append(block)
                # recurse into nested blocks
                if block.get("has_children"):
                    blocks.extend(self.get_block_children(block["id"]))
            has_more = data.get("has_more", False)
            if has_more:
                url = data.get("next_cursor")
                if url:
                    url = f"{NOTION_API_BASE}/blocks/{block_id}/children?start_cursor={url}"
                else:
                    has_more = False
        return blocks

    def flatten_blocks_text(self, blocks: list[dict]) -> str:
        """Convert block objects into a simple text string for the summariser prompt."""
        texts = []
        for b in blocks:
            btype = b.get("type", "")
            content = b.get(btype, {})
            rich_text = content.get("rich_text", [])
            text = "".join(r.get("plain_text", "") for r in rich_text)
            if text.strip():
                texts.append(text)
        return "\n".join(texts)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------
    def archive_note(self, page_id: str) -> None:
        """Set the 'Archived' checkbox to true."""
        url = f"{NOTION_API_BASE}/pages/{page_id}"
        payload = {
            "properties": {
                "Archived": {"checkbox": True},
            }
        }
        self._request("PATCH", url, context="archive_note", json=payload)
        logger.info("Archived note %s", page_id)

    def append_kept_block(self, page_id: str) -> None:
        """Append a text block marking the note as kept today.

        This updates last_edited_time so the note won't surface again
        for another 60 days.
        """
        from datetime import datetime, timezone

        url = f"{NOTION_API_BASE}/blocks/{page_id}/children"
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        payload = {
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {
                                    "content": f"✅ Kept via Telegram review on {today}"
                                },
                            }
                        ]
                    },
                }
            ]
        }
        self._request("PATCH", url, context="append_kept_block", json=payload)
        logger.info("Appended 'kept' block to note %s", page_id)
