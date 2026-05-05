"""Unit tests for WeeklyScanner helpers."""

from datetime import datetime, timezone, timedelta

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
    def test_dry_run_does_not_mutate(self, mocker, caplog):
        caplog.set_level("INFO")
        scanner = WeeklyScanner(dry_run=True)

        # Mock Notion to return one fake stale note
        fake_note = {
            "id": "fake-id",
            "properties": {
                "Name": {"title": [{"plain_text": "Test Note"}]}
            },
        }
        mocker.patch.object(
            scanner.notion, "get_stale_notes", return_value=[fake_note]
        )
        mocker.patch.object(scanner.notion, "get_project_name", return_value="TestProj")
        mocker.patch.object(scanner.notion, "get_block_children", return_value=[])
        mocker.patch.object(scanner.kimi, "summarise_note", return_value="A test summary")
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=42)

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["scanned"] == 1
        assert result["sent"] == 0  # dry_run skips the send
        assert "[DRY RUN]" in caplog.text
