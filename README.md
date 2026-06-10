# AI CLOCK

**給 AI 編程代理（Claude Code / Codex）用的客觀工時 + token 計時器。**

**繁體中文** ｜ [English](#ai-clock-english)

> 指令名、環境變數、資料檔都用前綴 `aiclock`（無空格，對命令列友善）。專案／品牌名是 **AI CLOCK**，repo 是 `ai-clock`。

當你按小時向客戶計費 AI 輔助的工作時，「AI 到底花了多久」不能用猜的。`aiclock` 用**作業系統時鐘**（不是模型估值）量每一段工作的時間，並從代理自己的 transcript 回填該段的 **token 用量**。產出是每個專案一份 CSV，可轉成計費試算表。

支援 **Claude Code** 與 **OpenAI Codex**——每個代理的 token 各自從自己的 transcript 讀取、存在獨立檔案，所以同時跑兩個代理也不會互相污染數字。

> ⚠️ **手動模式不會自動執行。** 沒有 daemon、沒有 hook、沒有背景程式。由代理（或你）顯式呼叫 `start` / `stop`。通常你告訴代理「這個專案用 aiclock」，它就會在工作時自動打點。（若想要全自動，見下方 [背景常駐 watch 模式](#背景常駐-watch-模式)。）

---

## 為什麼要分兩個時間欄？

| 欄位 | 是什麼 | 用途 |
|------|--------|------|
| **法顧投入時間**（`wall_min`） | 你發問 → 交付，含你的閱讀／思考／溝通 | 對客戶計費的基礎 |
| **AI 處理時間**（`duration_min`） | 該段純 OS 時鐘執行時間 | 透明度／成本分析 |

可計費工時 = 法顧投入時間，以計費單位**無條件進位**（預設 15 分）。用 `AICLOCK_BILLING_INCREMENT` 調整。

## 為什麼 `total_tok` 不含 `cache_read`？

LLM 代理每個回合都會重新載入龐大的快取上下文——往往是數百萬 token，跟「這段做了多少事」無關。`aiclock` 把 `cache_read` 記在獨立欄位以保持透明，但**不計入 `total_tok`**（`total = in + out + cache_creation`），讓 token 總數反映真實工作量，而非背景重載。

---

## 安裝

```bash
git clone https://github.com/aa0101181514/ai-clock
cd ai-clock
pip install openpyxl    # 只有要產 Excel 才需要
```

沒有其他相依套件；`aiclock.py` 是純標準庫。

## 使用

```bash
# 開始一段工作（代理開始工作時呼叫）
python3 aiclock.py start myproject "研究 API 並起草修改"

# ...工作中...

# 結束——寫一列 CSV，並從 transcript 回填 token
python3 aiclock.py stop  myproject "完成 PR，改了 3 個檔"

# 目前有未結束的段落嗎？／印出 log
python3 aiclock.py status myproject
python3 aiclock.py show   myproject

# 產計費試算表
python3 build_log.py --project myproject
```

### Codex

```bash
python3 aiclock.py start myproject "工作" --agent codex
python3 aiclock.py stop  myproject "完成" --agent codex
python3 build_log.py --project myproject --agent codex   # 獨立的 .xlsx
```

### 計費用的牆鐘起點

如果使用者在 09:30 發問，但代理 09:42 才打 `start`，記下真實的計費起點：

```bash
python3 aiclock.py start myproject "工作" --wall 09:30
```

---

## 叫你的代理使用它

在代理的指示檔（如 `CLAUDE.md`、`AGENTS.md`、system prompt 或 memory）放類似這段：

> 做按時計費的專案時，每段工作開頭跑
> `python3 /path/to/aiclock.py start <project> "<工作項目>"`，
> 交付時跑 `... stop <project> "<產出說明>"`。如果你是 Codex 就加 `--agent codex`。
> stop 後重跑 `build_log.py --project <project>` 更新試算表。

代理仍然得記得去做——手動模式沒有魔法自動追蹤。

---

## 背景常駐 watch 模式

如果你**不想**手動打點，就跑 watcher。它常駐背景，讀 Claude Code / Codex 的 transcript，把連續的 token 用量事件切成「活動段」（中間閒置超過門檻就切新段），記每段的時間 + token——全自動，不用 start/stop。

```bash
python3 aiclock_watch.py backfill          # 從現有 transcript 重建活動段
python3 aiclock_watch.py daemon            # 持續執行（自動偵測活動）
python3 aiclock_watch.py report            # 每代理每天彙總（段數／分鐘／token）
python3 aiclock_watch.py show --agent codex
```

選項：`--idle N`（閒置幾分鐘算切段，預設 5）、`--interval N`（daemon 輪詢秒數，預設 30）、`--agents claude,codex`。

### 設成開機自動啟動（macOS launchd）

建立 `~/Library/LaunchAgents/com.aiclock.watch.plist`：

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
launchctl load ~/Library/LaunchAgents/com.aiclock.watch.plist   # 啟動 + 開機自動啟動
launchctl unload ~/Library/LaunchAgents/com.aiclock.watch.plist # 停止
```

（Linux：用 `systemd --user` service 或 cron `@reboot` 同理可達。）

### ⚠️ watcher 僅供內部參考，不可用於計費

watcher 用準確度換取零負擔。把它當粗略的產能／成本儀表板，**不要**當客戶帳單：

- **段落邊界是用閒置門檻猜的**，不是工作語意。
- **沒有工作項目／產出說明**——watcher 看不到你在做什麼。
- 記的時間是「transcript 有活動」的時間，不是「發問 → 交付」。
- token 總數會比手動單段大很多，因為 watcher 抓的是時間窗內的「全部」活動。

它寫進**獨立**檔案（`aiclock_watch_<agent>.csv`），絕不碰你手動 `aiclock.py` 的資料。要可計費、有描述的段落，繼續用 `aiclock.py start/stop`。

---

## 設定（全部是環境變數，皆有預設值）

| 變數 | 預設 | 意義 |
|------|------|------|
| `AICLOCK_HOME` | `~/.aiclock` | CSV + pending 檔存放位置 |
| `AICLOCK_TZ_OFFSET` | 本機時區 | 時間戳的時區偏移（小時） |
| `AICLOCK_CLAUDE_DIR` | 自動 `~/.claude/projects/*` | Claude transcript 根目錄 |
| `AICLOCK_CODEX_DIR` | `~/.codex/sessions` | Codex sessions 根目錄 |
| `AICLOCK_BILLING_INCREMENT` | `0.25` | 計費進位單位（小時） |
| `AICLOCK_WATCH_IDLE_MIN` | `5` | watcher：閒置幾分鐘算切段 |
| `AICLOCK_WATCH_INTERVAL_SEC` | `30` | watcher daemon：輪詢秒數 |

## CSV 欄位

```
seq, date, wall_start_iso, wall_end_iso, wall_min,
start_iso, stop_iso, duration_sec, duration_min,
in_tok, out_tok, cache_tok, cache_read_tok, total_tok, task, deliverable
```

範例見 `examples/aiclock_demo.csv`（假資料）。

---

## 限制（請務必閱讀）

- **token 回填是 best-effort。** 它讀的是代理在硬碟上的 transcript 格式（Claude Code 的 `usage`、Codex 的 `token_count` 事件），這些**不是公開 API**，版本更新可能改變。格式變了的話，**計時仍正常**，token 可能讀到 0。
- **極短的段落可能讀到 0 token**——`stop` 執行時最後一個回合可能還沒寫進 transcript。正常長度的段落不受影響。
- **兩種模式，兩種用途。** `aiclock.py`（手動 start/stop）給你精準、有描述、可計費的段落；`aiclock_watch.py`（背景 daemon）給你省力但粗略的內部參考。不要用 watcher 計費。

## 授權

MIT — 見 [LICENSE](LICENSE)。

---
<a name="ai-clock-english"></a>

# AI CLOCK (English)

**Objective work-time + token clock for AI coding agents.**

[繁體中文](#ai-clock) ｜ **English**

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
> each segment as it works. (For a fully automatic option, see
> [Automatic mode](#automatic-mode-aiclock_watchpy-background-daemon) below.)

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
git clone https://github.com/aa0101181514/ai-clock
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
