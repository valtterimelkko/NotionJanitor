"""Notion API client for Ultimate Brain (Second Brain) operations."""

import logging
from typing import Any, Optional

import requests

from config import NOTION_API_BASE, NOTION_DATABASE_ID, NOTION_TOKEN

logger = logging.getLogger(__name__)

HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}


class NotionClient:
    """Wraps the Notion API to match the behaviour of the n8n Notion nodes."""

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(HEADERS)

    # ------------------------------------------------------------------
    # Database queries
    # ------------------------------------------------------------------
    def get_stale_notes(self, cutoff_iso: str, limit: int = 20) -> list[dict]:
        """Query the Notes database for notes not edited since *cutoff_iso*.

        Mirrors the n8n "Get Stale Notes" node filter:
            - Archived checkbox != true
            - last_edited_time < cutoffDate
            - sorted oldest first
        """
        url = f"{NOTION_API_BASE}/databases/{NOTION_DATABASE_ID}/query"
        payload = {
            "filter": {
                "and": [
                    {
                        "property": "Archived",
                        "checkbox": {"does_not_equal": True},
                    },
                    {
                        "timestamp": "last_edited_time",
                        "last_edited_time": {"before": cutoff_iso},
                    },
                ]
            },
            "sorts": [
                {
                    "timestamp": "last_edited_time",
                    "direction": "ascending",
                }
            ],
            "page_size": limit,
        }
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        logger.info("Found %d stale notes (limit %d)", len(results), limit)
        return results

    # ------------------------------------------------------------------
    # Page / relation helpers
    # ------------------------------------------------------------------
    def get_page(self, page_id: str) -> dict:
        """Fetch a single page (used to resolve project relation)."""
        url = f"{NOTION_API_BASE}/pages/{page_id}"
        resp = self.session.get(url)
        resp.raise_for_status()
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
            resp = self.session.get(url)
            resp.raise_for_status()
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
        """Convert block objects into a simple text string for the Kimi prompt."""
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
        resp = self.session.patch(url, json=payload)
        resp.raise_for_status()
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
        resp = self.session.patch(url, json=payload)
        resp.raise_for_status()
        logger.info("Appended 'kept' block to note %s", page_id)
