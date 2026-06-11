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
        mocker.patch.object(scanner.kimi, "summarise_note", return_value="A test summary")
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=42)

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
        mocker.patch.object(scanner.kimi, "summarise_note", return_value="summary")
        mocker.patch.object(scanner.telegram, "send_review_message", return_value=99)

        import asyncio
        result = asyncio.run(scanner.run())

        assert result["scanned"] == 1
        assert result["scanned_linked"] == 0
        assert result["scanned_orphans"] == 1
        assert result["sent"] == 0  # dry_run
        assert "[DRY RUN]" in caplog.text
