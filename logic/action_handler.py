"""Action handler logic — replaces n8n Workflow 2."""

import logging
import re

from clients.notion_client import NotionClient
from clients.telegram_client import TelegramClient
from state import StateStore

logger = logging.getLogger(__name__)


class ActionHandler:
    """Processes Telegram Keep/Archive callbacks."""

    def __init__(self, dry_run: bool = False):
        self.notion = NotionClient()
        self.telegram = TelegramClient()
        self.state = StateStore()
        self.dry_run = dry_run

    def parse_callback(self, callback_data: str, message_text: str) -> dict:
        """Extract action, note_id, and title from the callback.

        Mirrors the n8n "Code in JavaScript" node logic exactly.
        """
        parts = callback_data.split(":")
        action = parts[0] if len(parts) > 0 else ""
        note_id = parts[1] if len(parts) > 1 else ""

        # Extract title from message text: look for "Title: " followed by text
        match = re.search(r"Title:\s*(.+?)\n", message_text)
        title = match.group(1).strip() if match else "this note"

        return {"action": action, "note_id": note_id, "title": title}

    async def handle(self, action: str, note_id: str, title: str, message_id: int) -> None:
        """Route to the correct handler."""
        if action == "archive":
            await self._archive(note_id, title, message_id)
        elif action == "keep":
            await self._keep(note_id, title, message_id)
        else:
            logger.warning("Unknown action '%s' for note %s", action, note_id)

    async def _archive(self, note_id: str, title: str, message_id: int) -> None:
        """Archive the note and edit the Telegram message."""
        if self.dry_run:
            logger.info("[DRY RUN] Would archive note %s (%s)", note_id, title)
            return

        self.notion.archive_note(note_id)
        await self.telegram.edit_to_archived(message_id, title)
        self.state.remove_pending(note_id)
        self.state.record_processed(note_id, "archived")
        logger.info("Archived note %s (%s)", note_id, title)

    async def _keep(self, note_id: str, title: str, message_id: int) -> None:
        """Append 'kept' block to the note and edit the Telegram message."""
        if self.dry_run:
            logger.info("[DRY RUN] Would keep note %s (%s)", note_id, title)
            return

        self.notion.append_kept_block(note_id)
        await self.telegram.edit_to_kept(message_id, title)
        self.state.remove_pending(note_id)
        self.state.record_processed(note_id, "kept")
        logger.info("Kept note %s (%s)", note_id, title)
