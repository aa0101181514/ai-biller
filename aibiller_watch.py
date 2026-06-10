#!/usr/bin/env python3
"""
aibiller_watch — passive background watcher for AI agent activity (Claude Code / Codex)

UNLIKE aibiller.py (which an agent explicitly stamps start/stop on, giving you
semantically-clean, billable segments with task descriptions), this watcher runs
in the background and AUTO-DETECTS activity by reading the agents' transcripts.
It groups consecutive token-usage events into "activity sessions" (a gap longer
than the idle threshold starts a new session) and logs each session's time span
and tokens.

⚠️ This is for INTERNAL productivity/cost reference only — a rough "how much AI
time/tokens did we burn" dashboard. It is NOT a billing record:
  - session boundaries are GUESSED from an idle threshold, not work semantics
  - there is no task/deliverable description (the watcher can't see intent)
  - the time is "transcript had activity" time, not "asked → delivered" time
For billable, described segments keep using aibiller.py start/stop.

The watcher writes to SEPARATE files (aibiller_watch_<agent>.csv) so it never
pollutes your manual aibiller data.

USAGE
    aibiller_watch.py backfill                 # scan existing transcripts, rebuild sessions
    aibiller_watch.py daemon                   # run continuously (poll every interval)
    aibiller_watch.py show [--agent claude|codex]
    aibiller_watch.py report                   # rollup: sessions / minutes / tokens per agent per day

OPTIONS / CONFIG (env)
    --idle N / AIBILLER_WATCH_IDLE_MIN   idle gap (minutes) that ends a session (default 5)
    --interval N / AIBILLER_WATCH_INTERVAL_SEC   daemon poll interval seconds (default 30)
    AIBILLER_HOME / AIBILLER_CLAUDE_DIR / AIBILLER_CODEX_DIR   (same as aibiller.py)
    --agents claude,codex               which agents to watch (default both)

CSV COLUMNS (aibiller_watch_<agent>.csv)
    seq, date, session_start_iso, session_end_iso, active_min, event_count,
    in_tok, out_tok, cache_tok, cache_read_tok, total_tok, agent
    (total_tok = in + out + cache_creation; cache_read excluded — same rule as aibiller.py)

MIT License.
"""
import csv
import json
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# reuse aibiller.py's path detection + tz so the two tools never drift apart
sys.path.insert(0, str(Path(__file__).resolve().parent))
import aibiller as _ac  # noqa: E402


def _idle_min():
    try:
        return float(os.environ.get("AIBILLER_WATCH_IDLE_MIN", "5"))
    except ValueError:
        return 5.0


def _interval_sec():
    try:
        return float(os.environ.get("AIBILLER_WATCH_INTERVAL_SEC", "30"))
    except ValueError:
        return 30.0


def watch_csv(agent):
    return _ac._data_home() / f"aibiller_watch_{agent}.csv"


HEADER = ["seq", "date", "session_start_iso", "session_end_iso", "active_min",
          "event_count", "in_tok", "out_tok", "cache_tok", "cache_read_tok",
          "total_tok", "agent"]


# ── per-event extraction (the watcher needs every event, not an interval sum) ──
def _events_claude():
    """Yield (epoch, in, out, cache_creation, cache_read) for each usage event."""
    seen = set()
    for d in _ac._claude_dirs():
        if not d.exists():
            continue
        for jf in d.glob("*.jsonl"):
            for line in _ac._iter_jsonl(jf):
                if '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                ep = _ac._ep(ts) if ts else None
                if ep is None:
                    continue
                u = (o.get("message") or {}).get("usage") or o.get("usage")
                if not isinstance(u, dict):
                    continue
                inp = u.get("input_tokens", 0) or 0
                out = u.get("output_tokens", 0) or 0
                cc = u.get("cache_creation_input_tokens", 0) or 0
                cr = u.get("cache_read_input_tokens", 0) or 0
                key = (ts, inp, out, cc, cr)
                if key in seen:
                    continue
                seen.add(key)
                # skip pure-zero heartbeat usage rows (no real work)
                if inp == 0 and out == 0 and cc == 0 and cr == 0:
                    continue
                yield (ep, inp, out, cc, cr)


def _events_codex():
    root = _ac._codex_dir()
    if not root.exists():
        return
    for jf in root.rglob("rollout-*.jsonl"):
        for line in _ac._iter_jsonl(jf):
            if "token_count" not in line:
                continue
            try:
                o = json.loads(line)
            except ValueError:
                continue
            payload = o.get("payload") or {}
            if payload.get("type") != "token_count":
                continue
            ts = o.get("timestamp")
            ep = _ac._ep(ts) if ts else None
            if ep is None:
                continue
            last = ((payload.get("info") or {}).get("last_token_usage")) or {}
            if not last:
                continue
            inp = last.get("input_tokens", 0) or 0
            cached = last.get("cached_input_tokens", 0) or 0
            out = last.get("output_tokens", 0) or 0
            reason = last.get("reasoning_output_tokens", 0) or 0
            non_cached_in = max(inp - cached, 0)
            if non_cached_in == 0 and out == 0 and reason == 0 and cached == 0:
                continue
            # map to (in, out, cache_creation=0, cache_read=cached)
            yield (ep, non_cached_in, out + reason, 0, cached)


def _collect_events(agent):
    if agent == "codex":
        return sorted(_events_codex(), key=lambda e: e[0])
    return sorted(_events_claude(), key=lambda e: e[0])


# ── sessionization: group events; a gap > idle threshold starts a new session ──
def _sessionize(events, idle_min):
    gap = idle_min * 60.0
    sessions = []
    cur = None
    for ep, inp, out, cc, cr in events:
        if cur is None or ep - cur["end"] > gap:
            if cur:
                sessions.append(cur)
            cur = {"start": ep, "end": ep, "n": 0,
                   "in": 0, "out": 0, "cc": 0, "cr": 0}
        cur["end"] = ep
        cur["n"] += 1
        cur["in"] += inp
        cur["out"] += out
        cur["cc"] += cc
        cur["cr"] += cr
    if cur:
        sessions.append(cur)
    return sessions


def _write_sessions(agent, sessions):
    """Overwrite the watch CSV with the full recomputed session list (idempotent:
    re-running backfill always reflects current transcripts, no double-count)."""
    cp = watch_csv(agent)
    cp.parent.mkdir(parents=True, exist_ok=True)
    tz = _ac._tz()
    with cp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        for i, s in enumerate(sessions, 1):
            sd = datetime.fromtimestamp(s["start"], tz)
            ed = datetime.fromtimestamp(s["end"], tz)
            active_min = (s["end"] - s["start"]) / 60.0
            total = s["in"] + s["out"] + s["cc"]
            w.writerow([
                i, sd.strftime("%Y-%m-%d"),
                sd.isoformat(timespec="seconds"),
                ed.isoformat(timespec="seconds"),
                round(active_min, 2), s["n"],
                s["in"], s["out"], s["cc"], s["cr"], total, agent,
            ])
    return cp


# ── commands ──────────────────────────────────────────────────────────────────
def cmd_backfill(agents, idle_min, quiet=False):
    for agent in agents:
        events = _collect_events(agent)
        sessions = _sessionize(events, idle_min)
        cp = _write_sessions(agent, sessions)
        if not quiet:
            tot = sum(s["in"] + s["out"] + s["cc"] for s in sessions)
            mins = sum((s["end"] - s["start"]) / 60.0 for s in sessions)
            print(f"[{agent}] {len(sessions)} sessions, "
                  f"{mins:.0f} active min, {tot:,} tokens → {cp}")


def cmd_daemon(agents, idle_min, interval):
    print(f"⏳ aibiller_watch daemon: agents={agents} idle={idle_min}m "
          f"interval={interval}s home={_ac._data_home()}")
    print("   (passive; reads transcripts only. Ctrl-C to stop.)")
    try:
        while True:
            cmd_backfill(agents, idle_min, quiet=True)
            stamp = _ac.now().strftime("%H:%M:%S")
            summary = []
            for agent in agents:
                cp = watch_csv(agent)
                n = sum(1 for _ in cp.open(encoding="utf-8")) - 1 if cp.exists() else 0
                summary.append(f"{agent}:{max(n,0)}seg")
            print(f"  {stamp} updated — {' '.join(summary)}", flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n stopped.")


def cmd_show(agents):
    for agent in agents:
        cp = watch_csv(agent)
        print(f"=== {cp.name} ===")
        print(cp.read_text(encoding="utf-8") if cp.exists() else "(no data)")


def cmd_report(agents):
    """Per-agent per-day rollup: sessions / active minutes / tokens."""
    print(f"{'date':12s} {'agent':7s} {'sessions':>8s} {'active_min':>11s} {'total_tok':>12s}")
    print("-" * 54)
    grand = {}
    for agent in agents:
        cp = watch_csv(agent)
        if not cp.exists():
            continue
        days = {}
        with cp.open(encoding="utf-8") as f:
            for r in csv.DictReader(f):
                d = r["date"]
                e = days.setdefault(d, [0, 0.0, 0])
                e[0] += 1
                e[1] += float(r.get("active_min") or 0)
                e[2] += int(float(r.get("total_tok") or 0))
        for d in sorted(days):
            n, mins, tok = days[d]
            print(f"{d:12s} {agent:7s} {n:>8d} {mins:>11.0f} {tok:>12,d}")
            g = grand.setdefault(agent, [0, 0.0, 0])
            g[0] += n
            g[1] += mins
            g[2] += tok
    print("-" * 54)
    for agent, (n, mins, tok) in grand.items():
        print(f"{'TOTAL':12s} {agent:7s} {n:>8d} {mins:>11.0f} {tok:>12,d}")


def main():
    raw = sys.argv[1:]
    agents = ["claude", "codex"]
    idle_min = _idle_min()
    interval = _interval_sec()
    if "--agents" in raw:
        i = raw.index("--agents")
        agents = [a.strip() for a in raw[i + 1].split(",") if a.strip()]
        del raw[i:i + 2]
    if "--agent" in raw:  # singular convenience
        i = raw.index("--agent")
        agents = [raw[i + 1]]
        del raw[i:i + 2]
    if "--idle" in raw:
        i = raw.index("--idle")
        idle_min = float(raw[i + 1])
        del raw[i:i + 2]
    if "--interval" in raw:
        i = raw.index("--interval")
        interval = float(raw[i + 1])
        del raw[i:i + 2]
    cmd = raw[0] if raw else "report"
    {
        "backfill": lambda: cmd_backfill(agents, idle_min),
        "daemon": lambda: cmd_daemon(agents, idle_min, interval),
        "show": lambda: cmd_show(agents),
        "report": lambda: cmd_report(agents),
    }.get(cmd, lambda: (print(__doc__), sys.exit(1)))()


if __name__ == "__main__":
    main()
