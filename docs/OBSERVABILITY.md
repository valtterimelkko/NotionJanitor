# Observability

How to see what Notion Janitor is doing, confirm it is healthy, and diagnose it
when it goes silent. **Read this first when investigating "the janitor hasn't
asked me about notes in a while".**

The single most important fact: a totally broken scan looks identical to "nothing
to review" from the user's side (no Telegram messages either way). The features
below exist specifically to make that case visible.

---

## Where logs live

There are two parallel sinks, both written from the same root logger:

1. **journald** (primary) — captured automatically by the systemd unit
   (`StandardOutput=journal`). This is the system of record and rotates itself.
   ```bash
   journalctl -u notion-janitor -n 200          # last 200 lines
   journalctl -u notion-janitor --since "1 hour ago"
   journalctl -u notion-janitor -f              # follow live
   ```

2. **Rotated file** — `LOG_FILE` (default `/var/log/notion-janitor.log`),
   written via a `RotatingFileHandler` that rolls over at **5 MiB** and keeps
   **5** backups (`notion-janitor.log.1` … `.5`). The file is bounded on purpose
   so it stays greppable.
   ```bash
   tail -n 200 /var/log/notion-janitor.log
   grep -E "ERROR|API error" /var/log/notion-janitor.log
   ```

Vendor HTTP libraries (`httpx`, `httpcore`) are pinned to `WARNING` so tokens
and request URLs never leak into either sink.

---

## The per-scan summary

Every scan ends by logging one structured line — this is the fastest health read:

```
Weekly scan complete: {'scanned': 23, 'scanned_linked': 13, 'scanned_orphans': 10, 'sent': 23, 'errors': 0, 'cleared_stale': 0}
```

| field | meaning |
|---|---|
| `scanned` | total candidate notes found across both sub-queries |
| `scanned_linked` | stale notes with a Project relation (capped at `STALE_NOTE_LIMIT`) |
| `scanned_orphans` | stale notes with **no** Project relation (capped separately) |
| `sent` | Telegram review messages actually sent |
| `errors` | notes that failed to process (summarise/send) |
| `cleared_stale` | old pending reviews auto-removed before scanning |

**The key signal:** `sent: 0` with `errors > 0` means an upstream outage — every
note failed. `sent: 0` with `errors: 0` is benign (all candidates already pending,
or genuinely nothing stale).

---

## Scan-run history (`scan_runs` table)

Each run is persisted to the SQLite state DB (`STATE_DB_PATH`, default
`data/janitor.db`) in the `scan_runs` table, so you can read trends without
grepping logs:

```bash
# Recent runs
sqlite3 data/janitor.db \
  "SELECT id, started_at, duration_s, scanned, sent, errors, dry_run
   FROM scan_runs ORDER BY id DESC LIMIT 10;"
```

Columns: `id, started_at, finished_at, duration_s, scanned, scanned_linked,
scanned_orphans, sent, errors, cleared_stale, dry_run`.

### Last-successful-scan health signal

`StateStore.last_successful_scan()` returns the most recent **non-dry-run** that
sent at least one message (`sent > 0 AND dry_run = 0`) — i.e. the last time the
loop demonstrably worked end-to-end.

```bash
python3 -c "from state import StateStore; print(StateStore().last_successful_scan())"
```

It is also logged at every service startup:

```
Last successful scan: 2026-07-06T09:00:42Z (23 sent)
```

If that timestamp is stale (or `none recorded yet`) while scans keep running,
something upstream is rejecting every note.

---

## The scan-failure alert

When a non-dry-run scan ends with **`sent == 0` and `errors > 0`**, the scanner
sends a no-button admin message to the same Telegram chat:

> ⚠️ **Notion Janitor — scan problem**
> Today's scan found 22 stale note(s) but sent **0** review messages (22 failed
> to process).
> Last successful scan: 2026-06-15T09:00:40Z (26 messages sent).
> This usually means an upstream API (Kimi/Notion) or a config value is rejecting
> requests. The scheduler itself is fine — check the service logs:
> `journalctl -u notion-janitor`

This is the feature that makes a silent outage loud. It is best-effort: a failure
to send the alert is logged and never raised, so it cannot break the scan.

---

## Upstream API errors now self-diagnose

Both API clients log the **response body** before raising on a non-2xx (a small
`_check` helper in `notion_client.py`, and an inline check in `kimi_client.py`).
The body is where the upstream puts the actual reason:

```
Kimi API error 400 during summarise_note: {"error":{"message":"invalid temperature: only 1 is allowed for this model","type":"invalid_request_error"}}
Notion API error 404 during get_stale_notes: {"object":"error","status":404,"code":"object_not_found","message":"Could not find database..."}}
```

Historically these bodies were discarded by `raise_for_status()`, which is why the
Kimi temperature regression ran undiagnosed for weeks. Grep for `API error` to find
them fast.

---

## Diagnostic playbook: "the janitor went silent"

1. **Is the scheduler firing?** `journalctl -u notion-janitor | grep "Weekly scan complete"`
   — you should see one line per Monday. If none, the service is not running
   (`systemctl status notion-janitor`).
2. **Are scans erroring?** Look at recent `scan_runs` (`errors > 0`) or
   `grep -E "ERROR|API error"` in the logs. The `API error …` line gives the
   upstream reason directly.
3. **When did it last actually work?** `last_successful_scan()` / the startup log
   line. A long gap with runs present = chronic upstream failure.
4. **Did the alert fire?** If `sent==0 && errors>0` and you got no Telegram alert,
   Telegram itself may be unreachable (check for `Bad Gateway` polling errors in
   the log).

---

## Linting and tests

```bash
.venv/bin/ruff check .          # lint (config in pyproject.toml)
.venv/bin/python -m pytest -q   # full suite
```
