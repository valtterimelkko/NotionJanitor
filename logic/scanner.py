"""Weekly Scanner logic — replaces n8n Workflow 1."""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from clients.kimi_client import KimiClient
from clients.notion_client import NotionClient
from clients.telegram_client import TelegramClient
from config import CUTOFF_DAYS, STALE_NOTE_LIMIT
from state import StateStore

logger = logging.getLogger(__name__)


class WeeklyScanner:
    """Finds stale notes, summarises them, and sends Telegram review messages."""

    def __init__(self, dry_run: bool = False):
        self.notion = NotionClient()
        self.kimi = KimiClient()
        self.telegram = TelegramClient()
        self.state = StateStore()
        self.dry_run = dry_run

    def _calculate_cutoff(self) -> str:
        """Return ISO8601 timestamp for *cutoff* days ago (UTC)."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=CUTOFF_DAYS)
        return cutoff.isoformat().replace("+00:00", "Z")

    async def run(self) -> dict:
        """Execute one full scan cycle.

        Returns a summary dict for logging / testing.
        """
        # Clean up very old pending reviews (user never clicked) before scanning.
        # Use a 13-day cutoff to avoid scheduling/seconds race conditions.
        cleared = self.state.clear_stale_pending(days=13)

        cutoff_iso = self._calculate_cutoff()
        logger.info("Starting weekly scan — cutoff: %s", cutoff_iso)

        # 1. Fetch stale notes from Notion
        stale_notes = self.notion.get_stale_notes(cutoff_iso, limit=STALE_NOTE_LIMIT)
        if not stale_notes:
            logger.info("No stale notes found. Nothing to do.")
            return {"scanned": 0, "sent": 0, "errors": 0, "cleared_stale": cleared}

        sent_count = 0
        error_count = 0

        for note in stale_notes:
            note_id = note["id"]

            # Skip if already pending review (prevents duplicates within the same week)
            if self.state.is_pending(note_id):
                logger.info("Skipping note %s — already pending review", note_id)
                continue

            try:
                did_send = await self._process_one_note(note)
                if did_send:
                    sent_count += 1
            except Exception as exc:
                logger.exception("Failed to process note %s: %s", note_id, exc)
                error_count += 1

        summary = {
            "scanned": len(stale_notes),
            "sent": sent_count,
            "errors": error_count,
            "cleared_stale": cleared,
        }
        logger.info("Weekly scan complete: %s", summary)
        return summary

    async def _process_one_note(self, note: dict) -> bool:
        """Summarise a single note and send the Telegram review message.

        Returns True if a message was actually sent, False in dry-run mode.
        """
        note_id = note["id"]
        title = (
            note.get("properties", {})
            .get("Name", {})
            .get("title", [{}])[0]
            .get("plain_text", "Untitled")
        )

        # Get project name (mirrors n8n "Get Project" node)
        project = self.notion.get_project_name(note)

        # Get content blocks (mirrors n8n "Get Content" node)
        blocks = self.notion.get_block_children(note_id)
        content_text = self.notion.flatten_blocks_text(blocks)

        if self.dry_run:
            logger.info(
                "[DRY RUN] Would review: %s | Project: %s | Blocks: %d",
                title, project, len(blocks),
            )
            return False

        # Generate summary via Kimi (mirrors n8n "Message a model")
        summary = self.kimi.summarise_note(title, content_text)

        # Send Telegram review message (mirrors n8n "Send a text message")
        message_id = await self.telegram.send_review_message(
            note_id=note_id,
            title=title,
            project=project,
            summary=summary,
        )

        # Record in local state so we don't resend it this week
        self.state.add_pending(note_id, title, project, summary, message_id)
        return True
