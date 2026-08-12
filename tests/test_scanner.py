"""Unit tests for WeeklyScanner helpers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from logic.scanner import WeeklyScanner


class TestCalculateCutoff:
    def test_cutoff_is_60_days_ago(self):
        scanner = WeeklyScanner(dry_run=True)
        cutoff_iso = scanner._calculate_cutoff()
        cutoff = datetime.fromisoformat(cutoff_iso)
        now = datetime.now(timezone.utc)
        delta = now - cutoff
        assert delta.days == 60


class TestDryRun:
    def _fake_note(self, note_id: str, title: str) -> dict:
        return {
            "id": note_id,
            "properties": {
                "Name": {"title": [{"plain_text": title}]},
                "Project": {"relation": []},
            },
        }

    def test_dry_run_does_not_mutate(self, mocker, caplog):
        caplog.set_level("INFO")
        scanner = WeeklyScanner(dry_run=True)

        linked_note = self._fake_note("linked-id", "Linked Note")
        orphan_note = self._fake_note("orphan-id", "Orphan Note")

        # Two calls: first for project-linked, second for orphans
        mocker.patch.object(
            scanner.notion,
            "get_stale_notes",
            side_effect=[[linked_note], [orphan_note]],
        )
        mocker.patch.object(scanner.notion, "get_project_name", return_value="TestProj")
        mocker.patch.object(scanner.notion, "get_block_children", return_value=[])
        mocker.patch.object(
            scanner.summariser,
            "summarise_note",
            new_callable=AsyncMock,
            return_value="A test summary",
        )
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=42)
        mocker.patch.object(scanner.state, "record_scan_run")

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["scanned"] == 2
        assert result["scanned_linked"] == 1
        assert result["scanned_orphans"] == 1
        assert result["sent"] == 0  # dry_run skips the send
        assert "[DRY RUN]" in caplog.text

    def test_orphans_only_scan(self, mocker, caplog):
        """Verify orphan notes are picked up even when no linked notes are stale."""
        caplog.set_level("INFO")
        scanner = WeeklyScanner(dry_run=True)

        orphan_note = self._fake_note("orphan-id", "Orphan Note")

        mocker.patch.object(
            scanner.notion,
            "get_stale_notes",
            side_effect=[[], [orphan_note]],  # no linked, one orphan
        )
        mocker.patch.object(scanner.notion, "get_project_name", return_value="No Project")
        mocker.patch.object(scanner.notion, "get_block_children", return_value=[])
        mocker.patch.object(
            scanner.summariser,
            "summarise_note",
            new_callable=AsyncMock,
            return_value="summary",
        )
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=99)
        mocker.patch.object(scanner.state, "record_scan_run")

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["scanned"] == 1
        assert result["scanned_linked"] == 0
        assert result["scanned_orphans"] == 1
        assert result["sent"] == 0  # dry_run
        assert "[DRY RUN]" in caplog.text


class TestScanFailureAlert:
    """A scan that sends nothing despite candidates must alert the user."""

    def _fake_note(self, note_id: str, title: str) -> dict:
        return {
            "id": note_id,
            "properties": {
                "Name": {"title": [{"plain_text": title}]},
                "Project": {"relation": []},
            },
        }

    def _wire(self, scanner, mocker, *, summariser_raises=False):
        """Mock all external dependencies and isolate the state DB.

        Returns (send_alert_mock, record_run_mock) so tests can assert on both.
        """
        mocker.patch.object(
            scanner.notion,
            "get_stale_notes",
            side_effect=[[self._fake_note("n1", "Note 1")], []],
        )
        mocker.patch.object(scanner.notion, "get_project_name", return_value="No Project")
        mocker.patch.object(scanner.notion, "get_block_children", return_value=[])
        if summariser_raises:
            mocker.patch.object(
                scanner.summariser,
                "summarise_note",
                new_callable=AsyncMock,
                side_effect=RuntimeError("Pi API error"),
            )
        else:
            mocker.patch.object(
                scanner.summariser,
                "summarise_note",
                new_callable=AsyncMock,
                return_value="ok summary",
            )
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=1)
        # Isolate from the real SQLite DB.
        mocker.patch.object(scanner.state, "clear_stale_pending", return_value=0)
        mocker.patch.object(scanner.state, "is_pending", return_value=False)
        mocker.patch.object(scanner.state, "add_pending")
        record_run = mocker.patch.object(scanner.state, "record_scan_run")
        mocker.patch.object(scanner.state, "last_successful_scan", return_value=None)
        send_alert = mocker.patch.object(scanner.telegram, "send_alert")
        return send_alert, record_run

    def test_alert_fires_on_total_failure(self, mocker):
        scanner = WeeklyScanner(dry_run=False)
        send_alert, record_run = self._wire(scanner, mocker, summariser_raises=True)

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["sent"] == 0
        assert result["errors"] == 1
        send_alert.assert_called_once()
        # The failed run is still recorded for history.
        record_run.assert_called_once()

    def test_no_alert_when_messages_sent(self, mocker):
        scanner = WeeklyScanner(dry_run=False)
        send_alert, record_run = self._wire(scanner, mocker, summariser_raises=False)

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["sent"] == 1
        assert result["errors"] == 0
        send_alert.assert_not_called()
        record_run.assert_called_once()
        assert record_run.call_args.args[0]["sent"] == 1

    def test_no_alert_in_dry_run(self, mocker):
        scanner = WeeklyScanner(dry_run=True)
        send_alert, _ = self._wire(scanner, mocker, summariser_raises=True)

        import asyncio
        asyncio.run(scanner.run())

        # dry_run returns before the summariser is called, so errors stay 0 -> no alert.
        send_alert.assert_not_called()
