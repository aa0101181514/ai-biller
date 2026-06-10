#!/usr/bin/env python3
"""
AI CLOCK (aiclock) — objective work-time clock for AI coding agents (Claude Code / Codex)

The agent stamps `start` at the beginning of a work segment and `stop` at the
end. Duration is measured by the OS clock (not estimated by the model), and the
token usage for that segment is backfilled by scanning the agent's own
transcript for the matching time window. Output is a per-project CSV you can
turn into a billing spreadsheet (see build_log.py).

Why: when you bill clients by the hour for AI-assisted work, the timing must be
auditable. OS-clock timing + transcript-derived tokens give you objective,
checkable numbers instead of the model's guesses.

USAGE
    aiclock.py init  <project> [--dir PATH]        # set up per-project data dir
    aiclock.py start <project> "<task>"            # begin a segment
    aiclock.py stop  <project> "<deliverable>"     # end it, write a CSV row + Excel
    aiclock.py status <project>                    # is a segment open?
    aiclock.py show   <project>                    # print the project CSV

OPTIONS
    --agent claude|codex   which agent's transcript to read for tokens
                           (default: claude). Each agent writes its own CSV so
                           concurrent agents never pollute each other's tokens.
    --wall HH:MM           wall-clock start (when the *user asked*), used as the
                           billable basis (includes the user's reading/thinking
                           time). Defaults to the moment of `start`.
    --dir PATH             (init only) project root under which the
                           <project>_AI_CLOCK/ data dir is created. Default: CWD.
    --no-excel             (stop only) skip auto-generating the Excel.

PER-PROJECT DATA DIR (recommended)
    aiclock.py init <project> [--dir PATH]   # create <PATH>/<project>_AI_CLOCK/
                                             # and remember it for this project,
                                             # so later start/stop/build write
                                             # there. PATH defaults to the current
                                             # working directory.
    Once a project is init'd, its CSV + Excel live next to the work they bill,
    in <PATH>/<project>_AI_CLOCK/, and `stop` auto-generates the Excel there.

CONFIG (environment variables — everything has a sane default)
    AICLOCK_HOME        fallback data dir when a project has not been init'd
                        (default: ~/.aiclock)
    AICLOCK_PROJECT_DIR project root for THIS invocation; data goes in
                        <AICLOCK_PROJECT_DIR>/<project>_AI_CLOCK/ (overrides the
                        remembered init dir; --dir overrides this)
    AICLOCK_TZ_OFFSET   timezone offset in hours for stamps (default: local)
    AICLOCK_CLAUDE_DIR  Claude Code transcript root  (default: auto-detect
                        ~/.claude/projects ; scans all project subdirs)
    AICLOCK_CODEX_DIR   Codex sessions root          (default: ~/.codex/sessions)

CSV COLUMNS
    seq, date, wall_start_iso, wall_end_iso, wall_min,
    start_iso, stop_iso, duration_sec, duration_min,
    in_tok, out_tok, cache_tok, cache_read_tok, total_tok, task, deliverable
    (total_tok = in + out + cache_creation; cache_read is kept separately but
     NOT counted in total — it is the multi-million-token background context
     reloaded each turn and unrelated to how much work a segment did.)

NOTES / LIMITATIONS
- Token backfill is best-effort: it reverse-engineers the agents' on-disk
  transcript formats, which are not public contracts and may change between
  versions. If a format changes, timing still works; tokens may read 0.
- `stop`'s last turn may not be flushed to the transcript yet, so very short
  segments can read 0 tokens (you'll see a warning). Normal segments are fine.
- Agents do not auto-run this. The agent (or you) must call start/stop.

MIT License. See LICENSE.
"""
import csv
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


# ── configuration (env-overridable, all defaulted) ────────────────────────────
def _fallback_home():
    """Data dir for projects that were never `init`'d (zero-config default)."""
    return Path(os.environ.get("AICLOCK_HOME", str(Path.home() / ".aiclock")))


# Registry mapping project -> its AI_CLOCK data dir, so start/stop/build don't
# need --dir every time. Lives in the fallback home (small, machine-local).
def _registry_path():
    return _fallback_home() / ".aiclock_projects.json"


def _load_registry():
    p = _registry_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_registry(reg):
    p = _registry_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")


def _data_home(project=None):
    """Resolve the data dir for a project, in priority order:
      1. AICLOCK_PROJECT_DIR env  -> <env>/<project>_AI_CLOCK/
      2. registered init dir      -> the path saved by `init`
      3. fallback home            -> ~/.aiclock (or AICLOCK_HOME)
    """
    if project:
        env_dir = os.environ.get("AICLOCK_PROJECT_DIR")
        if env_dir:
            return Path(env_dir) / f"{project}_AI_CLOCK"
        reg = _load_registry()
        if project in reg:
            return Path(reg[project])
    return _fallback_home()


def _tz():
    off = os.environ.get("AICLOCK_TZ_OFFSET")
    if off is not None:
        try:
            return timezone(timedelta(hours=float(off)))
        except ValueError:
            pass
    # local timezone
    return datetime.now().astimezone().tzinfo


def now():
    return datetime.now(_tz())


def _claude_dirs():
    """Claude Code transcript roots. Env overrides; else auto-detect every
    project subdir under ~/.claude/projects (usage is keyed by UTC timestamp,
    so scanning all projects and filtering by the time window is correct)."""
    env = os.environ.get("AICLOCK_CLAUDE_DIR")
    if env:
        return [Path(p) for p in env.split(os.pathsep) if p]
    root = Path.home() / ".claude" / "projects"
    if root.exists():
        return [d for d in root.iterdir() if d.is_dir()]
    return []


def _codex_dir():
    env = os.environ.get("AICLOCK_CODEX_DIR")
    if env:
        return Path(env)
    return Path.home() / ".codex" / "sessions"


# ── paths ─────────────────────────────────────────────────────────────────────
def csv_path(project, agent="claude"):
    home = _data_home(project)
    if agent == "claude":
        return home / f"aiclock_{project}.csv"
    return home / f"aiclock_{project}_{agent}.csv"


def pending_path(project, agent="claude"):
    home = _data_home(project)
    if agent == "claude":
        return home / f".aiclock_open_{project}.json"
    return home / f".aiclock_open_{project}_{agent}.json"


# ── token collection ──────────────────────────────────────────────────────────
def _collect_tokens(start_epoch, stop_epoch, agent="claude"):
    """Dispatch to the per-agent transcript scanner. Sum token usage whose
    timestamp falls in [start_epoch, stop_epoch]. Returns
    (in, out, cache_creation, cache_read) or None if nothing found.
    Unified rule: total = in + out + cache_creation (cache_read kept separate)."""
    if agent == "codex":
        return _collect_tokens_codex(start_epoch, stop_epoch)
    return _collect_tokens_claude(start_epoch, stop_epoch)


def _iter_jsonl(path):
    try:
        fh = path.open(encoding="utf-8")
    except OSError:
        return
    with fh:
        for line in fh:
            yield line


def _ep(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return None


def _collect_tokens_claude(start_epoch, stop_epoch):
    """Scan Claude Code transcripts (*.jsonl) for assistant `usage` blocks.
    Dedupe identical consecutive usage rows by the full token tuple."""
    seen = set()
    totals = [0, 0, 0, 0]  # in, out, cache_creation, cache_read
    found = False
    for d in _claude_dirs():
        if not d.exists():
            continue
        for jf in d.glob("*.jsonl"):
            try:
                if jf.stat().st_mtime < start_epoch - 3600:
                    continue
            except OSError:
                continue
            for line in _iter_jsonl(jf):
                if '"usage"' not in line:
                    continue
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                ts = o.get("timestamp")
                ep = _ep(ts) if ts else None
                if ep is None or ep < start_epoch or ep > stop_epoch:
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
                found = True
                totals[0] += inp
                totals[1] += out
                totals[2] += cc
                totals[3] += cr
    return tuple(totals) if found else None


def _collect_tokens_codex(start_epoch, stop_epoch):
    """Scan Codex sessions (rollout-*.jsonl) for `token_count` events; sum each
    in-window `last_token_usage` (deltas add up to the window total).
    Mapping: in = input - cached, out = output + reasoning, cache_read = cached,
    cache_creation = 0 (Codex has no such concept)."""
    root = _codex_dir()
    if not root.exists():
        return None
    totals = [0, 0, 0, 0]
    found = False
    for jf in root.rglob("rollout-*.jsonl"):
        try:
            if jf.stat().st_mtime < start_epoch - 3600:
                continue
        except OSError:
            continue
        for line in _iter_jsonl(jf):
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
            ep = _ep(ts) if ts else None
            if ep is None or ep < start_epoch or ep > stop_epoch:
                continue
            last = ((payload.get("info") or {}).get("last_token_usage")) or {}
            if not last:
                continue
            inp = last.get("input_tokens", 0) or 0
            cached = last.get("cached_input_tokens", 0) or 0
            out = last.get("output_tokens", 0) or 0
            reason = last.get("reasoning_output_tokens", 0) or 0
            found = True
            totals[0] += max(inp - cached, 0)
            totals[1] += out + reason
            totals[3] += cached
    return tuple(totals) if found else None


# ── commands ──────────────────────────────────────────────────────────────────
def _parse_wall(hm):
    """Parse 'HH:MM' into today's ISO + epoch (current tz)."""
    t = now()
    try:
        h, m = (int(x) for x in hm.split(":"))
    except ValueError:
        return None
    w = t.replace(hour=h, minute=m, second=0, microsecond=0)
    return w.isoformat(timespec="seconds"), w.timestamp()


def cmd_init(project, base_dir=None):
    """Create <base_dir>/<project>_AI_CLOCK/ and remember it for this project.
    base_dir defaults to the current working directory."""
    root = Path(base_dir).expanduser().resolve() if base_dir else Path.cwd()
    data_dir = root / f"{project}_AI_CLOCK"
    data_dir.mkdir(parents=True, exist_ok=True)
    reg = _load_registry()
    reg[project] = str(data_dir)
    _save_registry(reg)
    print(f"📁 init [{project}] → {data_dir}")
    # Generate an (empty-but-valid) Excel skeleton so the folder is ready.
    try:
        import build_log
        build_log.build(project, "claude")
    except Exception as e:  # build_log optional (needs openpyxl); never block init
        print(f"   (Excel skeleton skipped: {e})", file=sys.stderr)


def cmd_start(project, item, agent="claude", wall=None):
    _data_home(project).mkdir(parents=True, exist_ok=True)
    p = pending_path(project, agent)
    if p.exists():
        prev = json.loads(p.read_text())
        print(f"⚠️ open segment exists (start={prev['start_iso']}, task={prev['item']}); "
              f"stop it first or this start overwrites it.", file=sys.stderr)
    t = now()
    wall_start_iso = t.isoformat(timespec="seconds")
    if wall:
        parsed = _parse_wall(wall)
        if parsed:
            wall_start_iso = parsed[0]
        else:
            print(f"⚠️ --wall '{wall}' must be HH:MM; using start time instead.", file=sys.stderr)
    p.write_text(json.dumps({
        "start_iso": t.isoformat(timespec="seconds"),
        "start_epoch": t.timestamp(),
        "wall_start_iso": wall_start_iso,
        "item": item,
        "agent": agent,
    }, ensure_ascii=False))
    extra = f" (wall start {wall_start_iso[11:16]})" if wall else ""
    print(f"⏱️ START [{project}/{agent}] {t.strftime('%Y-%m-%d %H:%M:%S')} — {item}{extra}")


def cmd_stop(project, note, agent="claude", make_excel=True):
    p = pending_path(project, agent)
    if not p.exists():
        print(f"❌ no open segment to close ({project}/{agent}).", file=sys.stderr)
        sys.exit(1)
    open_seg = json.loads(p.read_text())
    agent = open_seg.get("agent", agent)
    t_stop = now()
    dur_sec = t_stop.timestamp() - open_seg["start_epoch"]
    dur_min = dur_sec / 60.0

    tok = _collect_tokens(open_seg["start_epoch"], t_stop.timestamp(), agent)
    if tok is None:
        in_tok = out_tok = cc_tok = cr_tok = 0
        tok_note = f"⚠️ no {agent} tokens found in transcript (recorded 0)"
    else:
        in_tok, out_tok, cc_tok, cr_tok = tok
        tok_note = None
    total_tok = in_tok + out_tok + cc_tok  # excludes cache_read

    wall_start_iso = open_seg.get("wall_start_iso", open_seg["start_iso"])
    wall_end_iso = t_stop.isoformat(timespec="seconds")
    try:
        wall_min = (t_stop.timestamp()
                    - datetime.fromisoformat(wall_start_iso).timestamp()) / 60.0
    except ValueError:
        wall_min = dur_min

    HEADER = ["seq", "date", "wall_start_iso", "wall_end_iso", "wall_min",
              "start_iso", "stop_iso", "duration_sec", "duration_min",
              "in_tok", "out_tok", "cache_tok", "cache_read_tok", "total_tok",
              "task", "deliverable"]
    cp = csv_path(project, agent)
    new = not cp.exists()
    seq = 1
    if not new:
        with cp.open(encoding="utf-8") as f:
            seq = sum(1 for _ in f)
    with cp.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerow([
            seq, now().strftime("%Y-%m-%d"),
            wall_start_iso, wall_end_iso, round(wall_min, 2),
            open_seg["start_iso"], t_stop.isoformat(timespec="seconds"),
            round(dur_sec, 1), round(dur_min, 2),
            in_tok, out_tok, cc_tok, cr_tok, total_tok,
            open_seg["item"], note,
        ])
    p.unlink()
    msg = (f"✅ STOP  [{project}/{agent}] {t_stop.strftime('%H:%M:%S')} — "
           f"wall {wall_min:.1f}m / AI {dur_sec:.1f}s ({dur_min:.2f}m) — {open_seg['item']}\n"
           f"   tokens: in={in_tok} out={out_tok} cache_create={cc_tok} "
           f"cache_read={cr_tok} → total={total_tok} (excl. cache_read)")
    if tok_note:
        msg += f"\n   {tok_note}"
    print(msg)

    # Auto-generate the Excel next to the CSV (best-effort; needs openpyxl).
    if make_excel:
        try:
            import build_log
            out = build_log.build(project, agent)
            if out:
                print(f"   📊 Excel: {out}")
        except ImportError:
            print("   (Excel skipped: openpyxl not installed — `pip install openpyxl`)",
                  file=sys.stderr)
        except Exception as e:
            print(f"   (Excel skipped: {e})", file=sys.stderr)


def cmd_status(project, agent="claude"):
    p = pending_path(project, agent)
    if p.exists():
        seg = json.loads(p.read_text())
        elapsed = now().timestamp() - seg["start_epoch"]
        print(f"🟢 open [{project}/{agent}]: {seg['item']} "
              f"(start {seg['start_iso']}, {elapsed:.0f}s elapsed)")
    else:
        print(f"⚪ no open segment ({project}/{agent})")


def cmd_show(project, agent="claude"):
    cp = csv_path(project, agent)
    if not cp.exists():
        print(f"(no data yet: {cp})")
        return
    print(cp.read_text(encoding="utf-8"))


def _take_opt(raw, name):
    """Pop `--name VALUE` from raw, return VALUE or None."""
    if name in raw:
        i = raw.index(name)
        val = raw[i + 1] if i + 1 < len(raw) else None
        del raw[i:i + 2]
        return val
    return None


def _take_flag(raw, name):
    if name in raw:
        raw.remove(name)
        return True
    return False


def main():
    raw = sys.argv[1:]
    agent = _take_opt(raw, "--agent") or "claude"
    wall = _take_opt(raw, "--wall")
    base_dir = _take_opt(raw, "--dir")
    no_excel = _take_flag(raw, "--no-excel")
    if len(raw) < 2:
        print(__doc__)
        sys.exit(1)
    cmd, project = raw[0], raw[1]
    arg = raw[2] if len(raw) > 2 else ""
    {
        "init": lambda: cmd_init(project, base_dir),
        "start": lambda: cmd_start(project, arg, agent, wall),
        "stop": lambda: cmd_stop(project, arg, agent, make_excel=not no_excel),
        "status": lambda: cmd_status(project, agent),
        "show": lambda: cmd_show(project, agent),
    }.get(cmd, lambda: (print(f"unknown command: {cmd}"), sys.exit(1)))()


if __name__ == "__main__":
    main()
