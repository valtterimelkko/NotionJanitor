"""Entry point for Notion Janitor.

Starts two things concurrently:
1. APScheduler — triggers the Weekly Scanner every Monday at 09:00
2. python-telegram-bot polling loop — handles Keep/Archive button clicks
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
)

from config import SCHEDULE_DAY, SCHEDULE_HOUR, SCHEDULE_MINUTE, TELEGRAM_BOT_TOKEN
from logic.action_handler import ActionHandler
from logic.scanner import WeeklyScanner

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging(log_to_file: bool = True) -> None:
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        from config import LOG_FILE

        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(LOG_FILE))

    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        handlers=handlers,
    )

    # Avoid vendor HTTP request logs leaking sensitive URLs/tokens into journals.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# ------------------------------------------------------------------
# Telegram callback handler
# ------------------------------------------------------------------
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle Keep/Archive button clicks."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()  # Stop the button from spinning

    handler = ActionHandler(dry_run=context.bot_data.get("dry_run", False))
    parsed = handler.parse_callback(query.data, query.message.text if query.message else "")

    logger = logging.getLogger(__name__)
    logger.info(
        "Callback received: action=%s note_id=%s title=%s",
        parsed["action"],
        parsed["note_id"],
        parsed["title"],
    )

    await handler.handle(
        action=parsed["action"],
        note_id=parsed["note_id"],
        title=parsed["title"],
        message_id=query.message.message_id if query.message else 0,
    )


# ------------------------------------------------------------------
# Scheduler job
# ------------------------------------------------------------------
async def run_scanner(dry_run: bool = False) -> None:
    """APScheduler job wrapper."""
    scanner = WeeklyScanner(dry_run=dry_run)
    await scanner.run()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------
async def main() -> None:
    parser = argparse.ArgumentParser(description="Notion Janitor")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run scanner without mutating Notion or sending real Telegram messages",
    )
    parser.add_argument(
        "--run-once",
        action="store_true",
        help="Run the scanner once immediately and exit (for testing)",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Notion Janitor — dry_run=%s", args.dry_run)

    if args.run_once:
        await run_scanner(dry_run=args.dry_run)
        return

    # Build the Telegram application (polling mode — no webhook)
    telegram_app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .build()
    )
    telegram_app.bot_data["dry_run"] = args.dry_run
    telegram_app.add_handler(CallbackQueryHandler(on_callback))

    # Scheduler
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        run_scanner,
        "cron",
        day_of_week=SCHEDULE_DAY,
        hour=SCHEDULE_HOUR,
        minute=SCHEDULE_MINUTE,
        kwargs={"dry_run": args.dry_run},
        id="weekly_scan",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler active — next scan: %s %02d:%02d",
        SCHEDULE_DAY, SCHEDULE_HOUR, SCHEDULE_MINUTE,
    )

    # Start polling (blocks until interrupted)
    await telegram_app.initialize()
    await telegram_app.start()
    await telegram_app.updater.start_polling(drop_pending_updates=True)
    logger.info("Telegram polling started")

    # Keep the event loop alive
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
    finally:
        await telegram_app.updater.stop()
        await telegram_app.stop()
        await telegram_app.shutdown()
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
