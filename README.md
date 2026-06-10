# AI CLOCK

**Objective work-time + token clock for AI coding agents.**

> Command name, env vars and data files use the prefix `aiclock` (no space —
> command-line friendly). The project / brand name is **AI CLOCK**; the repo is
> `ai-clock`.

When you bill clients by the hour for AI-assisted work, "how long did the AI
actually take?" can't be a guess. `aiclock` measures each work segment by the
**OS clock** (not the model's estimate) and backfills the **token usage** for
that segment by reading the agent's own transcript. Out comes a per-project CSV
you can turn into a billing spreadsheet.

Works with **Claude Code** and **OpenAI Codex** — each agent's tokens are read
from its own transcript and kept in separate files, so concurrent agents never
pollute each other's numbers.

> ⚠️ **The agent does not auto-run this.** There is no daemon, no hook, no
> background process. The agent (or you) explicitly calls `start` / `stop`.
> Typically you tell your agent: *"use aiclock for project X"* and it stamps
> each segment as it works.

---

## Why two time columns?

| column | what it is | use |
|--------|-----------|-----|
| **billable time** (`wall_min`) | user-asked → delivered, including the user's reading/thinking/comms | what you bill the client |
| **AI time** (`duration_min`) | pure OS-clock run time of the segment | transparency / cost analysis |

Billable hours = billable time rounded **up** to a billing increment (default
15 min). Set your own with `AICLOCK_BILLING_INCREMENT`.

## Why is `cache_read` excluded from `total_tok`?

LLM agents reload a large cached context every turn — often millions of tokens
that have nothing to do with how much work a segment did. `aiclock` records
`cache_read` in its own column for transparency but **excludes it from
`total_tok`** (`total = in + out + cache_creation`), so the token total reflects
real work, not background reloads.

---

## Install

```bash
git clone https://github.com/<you>/ai-clock
cd ai-clock
pip install openpyxl    # only needed for build_log.py
```

No other dependencies; `aiclock.py` is pure standard library.

## Use

```bash
# begin a segment (agent calls this when it starts working)
python3 aiclock.py start myproject "research the API and draft the change"

# ... work happens ...

# end it — writes a CSV row, backfills tokens from the transcript
python3 aiclock.py stop  myproject "drafted PR, 3 files changed"

# is something open? / show the log
python3 aiclock.py status myproject
python3 aiclock.py show   myproject

# build the billing spreadsheet
python3 build_log.py --project myproject
```

### Codex

```bash
python3 aiclock.py start myproject "task" --agent codex
python3 aiclock.py stop  myproject "done" --agent codex
python3 build_log.py --project myproject --agent codex   # separate .xlsx
```

### Billable wall-clock start

If the user asked at 09:30 but the agent only stamped `start` at 09:42, record
the real billable start:

```bash
python3 aiclock.py start myproject "task" --wall 09:30
```

---

## Telling your agent to use it

Put something like this in your agent's instructions (e.g. `CLAUDE.md`,
`AGENTS.md`, a system prompt, or a memory):

> When working on a billable project, run
> `python3 /path/to/aiclock.py start <project> "<task>"` at the start of each
> work segment and `... stop <project> "<deliverable>"` when you deliver. Use
> `--agent codex` if you are Codex. Re-run `build_log.py --project <project>`
> after stops to refresh the spreadsheet.

The agent still has to remember to do it — there is no magic auto-tracking.

---

## Automatic mode: `aiclock_watch.py` (background daemon)

If you'd rather **not** stamp anything by hand, run the watcher. It sits in the
background, reads the Claude Code / Codex transcripts, groups consecutive
token-usage events into "activity sessions" (a gap longer than the idle
threshold starts a new session), and logs each session's time + tokens — fully
automatic, no start/stop.

```bash
python3 aiclock_watch.py backfill          # build sessions from existing transcripts
python3 aiclock_watch.py daemon            # run continuously (auto-detects activity)
python3 aiclock_watch.py report            # per-agent per-day rollup (sessions/min/tokens)
python3 aiclock_watch.py show --agent codex
```

Options: `--idle N` (idle-gap minutes that ends a session, default 5),
`--interval N` (daemon poll seconds, default 30), `--agents claude,codex`.

### Run it on login (macOS launchd)

Create `~/Library/LaunchAgents/com.aiclock.watch.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.aiclock.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABSOLUTE/PATH/TO/ai-clock/aiclock_watch.py</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.aiclock.watch.plist   # start + auto-start on login
launchctl unload ~/Library/LaunchAgents/com.aiclock.watch.plist # stop
```

(Linux: a `systemd --user` service or a cron `@reboot` line works the same way.)

### ⚠️ Watcher is for internal reference, NOT billing

The watcher trades accuracy for zero effort. Use it as a rough productivity /
cost dashboard, **not** as a client invoice:

- **Session boundaries are guessed** from the idle threshold, not work semantics.
- **No task/deliverable description** — the watcher can't see what you were doing.
- The time logged is "the transcript had activity", not "asked → delivered".
- Token totals are much larger than a manual segment's, because the watcher
  captures *all* activity in a window.

It writes to **separate** files (`aiclock_watch_<agent>.csv`) so it never
touches your manual `aiclock.py` data. For billable, described segments, keep
using `aiclock.py start/stop`.

---

## Configuration (all env vars, all defaulted)

| var | default | meaning |
|-----|---------|---------|
| `AICLOCK_HOME` | `~/.aiclock` | where CSVs + pending files live |
| `AICLOCK_TZ_OFFSET` | local tz | timezone offset (hours) for timestamps |
| `AICLOCK_CLAUDE_DIR` | auto `~/.claude/projects/*` | Claude transcript root(s) |
| `AICLOCK_CODEX_DIR` | `~/.codex/sessions` | Codex sessions root |
| `AICLOCK_BILLING_INCREMENT` | `0.25` | billing round-up unit (hours) |
| `AICLOCK_WATCH_IDLE_MIN` | `5` | watcher: idle-gap minutes that ends a session |
| `AICLOCK_WATCH_INTERVAL_SEC` | `30` | watcher daemon: poll interval seconds |

## CSV columns

```
seq, date, wall_start_iso, wall_end_iso, wall_min,
start_iso, stop_iso, duration_sec, duration_min,
in_tok, out_tok, cache_tok, cache_read_tok, total_tok, task, deliverable
```

See `examples/aiclock_demo.csv` for a sample (fake data).

---

## Limitations (read this)

- **Token backfill is best-effort.** It reads the agents' on-disk transcript
  formats (`usage` for Claude Code, `token_count` events for Codex), which are
  **not public APIs** and may change between versions. If a format changes,
  **timing still works**; tokens may read 0.
- **Very short segments can read 0 tokens** — the last turn may not be flushed
  to the transcript when `stop` runs. Normal-length segments are unaffected.
- **Two modes, two purposes.** `aiclock.py` (manual start/stop) gives precise,
  described, billable segments. `aiclock_watch.py` (background daemon) gives
  effortless but approximate internal reference. Don't bill from the watcher.

## License

MIT — see [LICENSE](LICENSE).
