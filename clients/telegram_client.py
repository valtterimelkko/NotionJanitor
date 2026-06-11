"""Telegram client for sending review messages and editing confirmations."""

import logging
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


class TelegramClient:
    """Wraps python-telegram-bot to replicate the n8n Telegram nodes."""

    def __init__(self):
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = TELEGRAM_CHAT_ID
        self._app: Application | None = None

    @property
    def app(self) -> Application:
        if self._app is None:
            self._app = Application.builder().token(self.token).build()
        return self._app

    # ------------------------------------------------------------------
    # Review message (was Workflow 1 "Send a text message")
    # ------------------------------------------------------------------
    async def send_review_message(
        self, note_id: str, title: str, project: str, summary: str
    ) -> int:
        """Send the stale-note review message with Keep/Archive buttons.

        Returns the sent message_id so we can edit it later.
        """
        text = (
            "🗑 <b>Stale Note Review</b>\n\n"
            f"<b>Title:</b> {title}\n"
            f"<b>Project:</b> {project}\n\n"
            f"<b>Summary:</b> {summary}"
        )

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Keep",
                        callback_data=f"keep:{note_id}",
                    ),
                    InlineKeyboardButton(
                        "🗄️ Archive",
                        callback_data=f"archive:{note_id}",
                    ),
                ]
            ]
        )

        message = await self.app.bot.send_message(
            chat_id=self.chat_id,
            text=text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        logger.info("Sent review message for note %s (msg_id=%s)", note_id, message.message_id)
        return message.message_id

    # ------------------------------------------------------------------
    # Confirmation edits (was Workflow 2 "Edit a text message")
    # ------------------------------------------------------------------
    async def edit_to_archived(self, message_id: int, title: str) -> None:
        """Edit the review message to show it was archived."""
        await self.app.bot.edit_message_text(
            chat_id=self.chat_id,
            message_id=message_id,
            text=f"🗄️ Archived: {title}",
            parse_mode="HTML",
        )
        logger.info("Edited msg %s to archived", message_id)

    async def edit_to_kept(self, message_id: int, title: str) -> None:
        """Edit the review message to show it was kept."""
        await self.app.bot.edit_message_text(
            chat_id=self.chat_id,
            message_id=message_id,
            text=f"👌 Kept: {title}\n(Timer reset)",
            parse_mode="HTML",
        )
        logger.info("Edited msg %s to kept", message_id)
