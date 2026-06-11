# AI BILLER

**給 AI 編程代理（Claude Code / Codex）用的客觀工時 + token 計時器。**

**繁體中文** ｜ [English](#ai-biller-english)

> 指令名、環境變數、資料檔都用前綴 `aibiller`（無空格，對命令列友善）。專案／品牌名是 **AI BILLER**，repo 是 `ai-biller`。

當你按小時向客戶計費 AI 輔助的工作時，「AI 到底花了多久」不能用猜的。`aibiller` 用**作業系統時鐘**（不是模型估值）量每一段工作的時間，並從代理自己的 transcript 回填該段的 **token 用量**。產出是每個專案一份 CSV，可轉成計費試算表。

支援 **Claude Code** 與 **OpenAI Codex**——每個代理的 token 各自從自己的 transcript 讀取、存在獨立檔案，所以同時跑兩個代理也不會互相污染數字。

> ⚠️ **手動模式不會自動執行。** 沒有 daemon、沒有 hook、沒有背景程式。由代理（或你）顯式呼叫 `start` / `stop`。通常你告訴代理「這個專案用 aibiller」，它就會在工作時自動打點。（若想要全自動，見下方 [背景常駐 watch 模式](#背景常駐-watch-模式)。）

---

## 60 秒快速開始

```bash
git clone https://github.com/aa0101181514/ai-biller
cd ai-biller
python3 aibiller.py start demo "我的第一段工作"   # 開始計時
python3 aibiller.py stop  demo "完成了"            # 結束，自動回填 token + 產 Excel
python3 aibiller.py show  demo                     # 看結果
```

`aibiller.py` 零相依、純標準庫，clone 完直接能跑。只有要產 Excel（`build_log.py`）才需要 `pip install openpyxl`。

> **想讓每個專案的計費 log 放在自己的資料夾？** 在專案根目錄跑一次
> `python3 /path/to/aibiller.py init <project> --dir .`，之後該專案的 CSV 與
> Excel 都會生在 `<專案根>/<project>_AI_BILLER/`，且 `stop` 後**自動產出/更新
> Excel**，不必再手動跑 `build_log.py`。詳見 [每個專案獨立資料夾](#每個專案獨立資料夾)。

---

## 計費時間怎麼算？

| 欄位 | 是什麼 | 用途 |
|------|--------|------|
| **AI 處理時間**（`duration_min`） | 從 `start` 到 `stop` 的純 OS 時鐘執行時間 | **計費基礎** |

可計費工時 = AI 處理時間，以計費單位**無條件進位**（預設 15 分）。用 `AIBILLER_BILLING_INCREMENT` 調整。

> 註：`aibiller` 每段只量「一個」OS 時鐘區間（start→stop），**無法**把你的閱讀／思考時間和 AI 跑的時間分開，因此不另設「法顧投入」欄——AI 處理時間就是唯一、誠實的計費基礎。

## 為什麼 `total_tok` 不含 `cache_read`？

LLM 代理每個回合都會重新載入龐大的快取上下文——往往是數百萬 token，跟「這段做了多少事」無關。`aibiller` 把 `cache_read` 記在獨立欄位以保持透明，但**不計入 `total_tok`**（`total = in + out + cache_creation`），讓 token 總數反映真實工作量，而非背景重載。

---

## 安裝

**需求：** Python 3.8+、git。（產 Excel 另需 `openpyxl`；計時與 watch 本身不用。）

```bash
git clone https://github.com/aa0101181514/ai-biller
cd ai-biller
pip install -r requirements.txt    # 只有要產 Excel 才需要（裝 openpyxl）
```

沒有其他相依套件；`aibiller.py` 與 `aibiller_watch.py` 都是純標準庫。

## 使用

```bash
# 開始一段工作（代理開始工作時呼叫）
python3 aibiller.py start myproject "研究 API 並起草修改"

# ...工作中...

# 結束——寫一列 CSV，並從 transcript 回填 token
python3 aibiller.py stop  myproject "完成 PR，改了 3 個檔"

# 目前有未結束的段落嗎？／印出 log
python3 aibiller.py status myproject
python3 aibiller.py show   myproject

# 產計費試算表（stop 已自動產，此指令用於手動重產）
python3 build_log.py --project myproject
```

### 每個專案獨立資料夾

預設所有專案的 CSV 都放在 `~/.aibiller`（零設定即可用）。若你按專案對不同客戶計費，
通常希望每個案子的計費 log 就放在**該案資料夾旁**，方便連同書狀一起交付／歸檔。
跑一次 `init` 即可：

```bash
# 在專案根目錄（或用 --dir 指定）建立 <project>_AI_BILLER/ 並記住它
cd /path/to/我的客戶案
python3 /path/to/aibiller.py init 我的客戶案 --dir .
# → 建立 /path/to/我的客戶案/我的客戶案_AI_BILLER/，含一個空的 Excel 骨架

# 之後 start/stop 不必再帶 --dir，自動寫到該資料夾，且 stop 後自動產 Excel
python3 /path/to/aibiller.py start 我的客戶案 "起草書狀"
python3 /path/to/aibiller.py stop  我的客戶案 "交付 v1"
# → CSV + Excel 都在 我的客戶案_AI_BILLER/，已含這段
```

`init` 把 `<project> → 資料夾` 的對應記在 `~/.aibiller/.aibiller_projects.json`，
所以同一台機器之後任何 `start`/`stop`/`build_log` 都會自動找到正確資料夾。
單次想換位置可用環境變數 `AIBILLER_PROJECT_DIR=/some/root`（會在其下建
`<project>_AI_BILLER/`），優先序：`--dir` > `AIBILLER_PROJECT_DIR` > init 記住的 > `~/.aibiller`。

> 想跳過 `stop` 的自動 Excel（例如 CI 環境沒裝 openpyxl）：`stop ... --no-excel`。

> **Excel 語言（繁中／英文）**：預設英文。要繁體中文，`init` 時加 `--lang zh`
> （語言會記進 registry，之後 `stop` 自動產的 Excel 也跟著用繁中，不必再設環境
> 變數）：`python3 aibiller.py init 我的客戶案 --dir . --lang zh`。單次覆寫可用環境
> 變數 `AIBILLER_LANG=zh` 或 `build_log.py --lang zh`。優先序：`AIBILLER_LANG` 環境
> 變數 > registry 記的語言 > 英文預設。

### Codex

```bash
python3 aibiller.py start myproject "工作" --agent codex
python3 aibiller.py stop  myproject "完成" --agent codex
python3 build_log.py --project myproject --agent codex   # 獨立的 .xlsx
```

### 計費用的牆鐘起點

如果使用者在 09:30 發問，但代理 09:42 才打 `start`，記下真實的計費起點：

```bash
python3 aibiller.py start myproject "工作" --wall 09:30
```

---

## 叫你的代理使用它

在代理的指示檔（如 `CLAUDE.md`、`AGENTS.md`、system prompt 或 memory）放類似這段：

> 做按時計費的專案時，先在專案資料夾跑一次
> `python3 /path/to/aibiller.py init <project> --dir .`，
> 之後每段工作開頭跑 `python3 /path/to/aibiller.py start <project> "<工作項目>"`，
> 交付時跑 `... stop <project> "<產出說明>"`（stop 會自動更新 Excel）。
> 如果你是 Codex 就加 `--agent codex`。

代理仍然得記得去做——手動模式沒有魔法自動追蹤。

---

## 背景常駐 watch 模式

如果你**不想**手動打點，就跑 watcher。它常駐背景，讀 Claude Code / Codex 的 transcript，把連續的 token 用量事件切成「活動段」（中間閒置超過門檻就切新段），記每段的時間 + token——全自動，不用 start/stop。

```bash
python3 aibiller_watch.py backfill          # 從現有 transcript 重建活動段
python3 aibiller_watch.py daemon            # 持續執行（自動偵測活動）
python3 aibiller_watch.py report            # 每代理每天彙總（段數／分鐘／token）
python3 aibiller_watch.py show --agent codex
```

選項：`--idle N`（閒置幾分鐘算切段，預設 5）、`--interval N`（daemon 輪詢秒數，預設 30）、`--agents claude,codex`。

### 設成開機自動啟動（macOS launchd）

建立 `~/Library/LaunchAgents/com.aibiller.watch.plist`：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.aibiller.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABSOLUTE/PATH/TO/ai-biller/aibiller_watch.py</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.aibiller.watch.plist   # 啟動 + 開機自動啟動
launchctl unload ~/Library/LaunchAgents/com.aibiller.watch.plist # 停止
```

（Linux：用 `systemd --user` service 或 cron `@reboot` 同理可達。）

### ⚠️ watcher 僅供內部參考，不可用於計費

watcher 用準確度換取零負擔。把它當粗略的產能／成本儀表板，**不要**當客戶帳單：

- **段落邊界是用閒置門檻猜的**，不是工作語意。
- **沒有工作項目／產出說明**——watcher 看不到你在做什麼。
- 記的時間是「transcript 有活動」的時間，不是「發問 → 交付」。
- token 總數會比手動單段大很多，因為 watcher 抓的是時間窗內的「全部」活動。

它寫進**獨立**檔案（`aibiller_watch_<agent>.csv`），絕不碰你手動 `aibiller.py` 的資料。要可計費、有描述的段落，繼續用 `aibiller.py start/stop`。

---

## 設定（全部是環境變數，皆有預設值）

| 變數 | 預設 | 意義 |
|------|------|------|
| `AIBILLER_HOME` | `~/.aibiller` | 未 `init` 專案的 fallback 資料夾（也存 registry） |
| `AIBILLER_PROJECT_DIR` | （無） | 本次呼叫的專案根；資料寫到 `<dir>/<project>_AI_BILLER/` |
| `AIBILLER_TZ_OFFSET` | 本機時區 | 時間戳的時區偏移（小時） |
| `AIBILLER_CLAUDE_DIR` | 自動 `~/.claude/projects/*` | Claude transcript 根目錄 |
| `AIBILLER_CODEX_DIR` | `~/.codex/sessions` | Codex sessions 根目錄 |
| `AIBILLER_BILLING_INCREMENT` | `0.25` | 計費進位單位（小時） |
| `AIBILLER_LANG` | `en` | Excel 語言：`en`／`zh`（繁中）。`init --lang zh` 可記進 registry 當該專案預設 |
| `AIBILLER_WATCH_IDLE_MIN` | `5` | watcher：閒置幾分鐘算切段 |
| `AIBILLER_WATCH_INTERVAL_SEC` | `30` | watcher daemon：輪詢秒數 |

## CSV 欄位

```
seq, date, wall_start_iso, wall_end_iso, wall_min,
start_iso, stop_iso, duration_sec, duration_min,
in_tok, out_tok, cache_tok, cache_read_tok, total_tok, task, deliverable
```

範例見 `examples/aibiller_demo.csv`（假資料）。

---

## 限制（請務必閱讀）

- **token 回填是 best-effort。** 它讀的是代理在硬碟上的 transcript 格式（Claude Code 的 `usage`、Codex 的 `token_count` 事件），這些**不是公開 API**，版本更新可能改變。格式變了的話，**計時仍正常**，token 可能讀到 0。
- **極短的段落可能讀到 0 token**——`stop` 執行時最後一個回合可能還沒寫進 transcript。正常長度的段落不受影響。
- **兩種模式，兩種用途。** `aibiller.py`（手動 start/stop）給你精準、有描述、可計費的段落；`aibiller_watch.py`（背景 daemon）給你省力但粗略的內部參考。不要用 watcher 計費。

## 授權

MIT — 見 [LICENSE](LICENSE)。

---
<a name="ai-biller-english"></a>

# AI BILLER (English)

**Objective work-time + token clock for AI coding agents.**

[繁體中文](#ai-biller) ｜ **English**

> Command name, env vars and data files use the prefix `aibiller` (no space —
> command-line friendly). The project / brand name is **AI BILLER**; the repo is
> `ai-biller`.

When you bill clients by the hour for AI-assisted work, "how long did the AI
actually take?" can't be a guess. `aibiller` measures each work segment by the
**OS clock** (not the model's estimate) and backfills the **token usage** for
that segment by reading the agent's own transcript. Out comes a per-project CSV
you can turn into a billing spreadsheet.

Works with **Claude Code** and **OpenAI Codex** — each agent's tokens are read
from its own transcript and kept in separate files, so concurrent agents never
pollute each other's numbers.

> ⚠️ **The agent does not auto-run this.** There is no daemon, no hook, no
> background process. The agent (or you) explicitly calls `start` / `stop`.
> Typically you tell your agent: *"use aibiller for project X"* and it stamps
> each segment as it works. (For a fully automatic option, see
> [Automatic mode](#automatic-mode-aibiller_watchpy-background-daemon) below.)

---

## 60-second quick start

```bash
git clone https://github.com/aa0101181514/ai-biller
cd ai-biller
python3 aibiller.py start demo "my first work segment"   # begin timing
python3 aibiller.py stop  demo "done"                    # end, auto-backfill tokens + Excel
python3 aibiller.py show  demo                           # see the result
```

`aibiller.py` has zero dependencies (pure standard library) and runs straight
after clone. Only `build_log.py` (the Excel sheet) needs `pip install openpyxl`.

> **Want each project's billing log in its own folder?** Run once in the project
> root: `python3 /path/to/aibiller.py init <project> --dir .`. After that the
> project's CSV and Excel live in `<project-root>/<project>_AI_BILLER/`, and
> `stop` **auto-generates/updates the Excel** for you. See
> [Per-project data dir](#per-project-data-dir).

---

## How is billable time measured?

| column | what it is | use |
|--------|-----------|-----|
| **AI time** (`duration_min`) | pure OS-clock run time from `start` to `stop` | **billing basis** |

Billable hours = AI time rounded **up** to a billing increment (default
15 min). Set your own with `AIBILLER_BILLING_INCREMENT`.

> Note: `aibiller` measures a single OS-clock interval per segment (start→stop);
> it cannot separate your reading/thinking from AI run time, so there is no
> separate "consultant input" column — AI time is the single, honest billing basis.

## Why is `cache_read` excluded from `total_tok`?

LLM agents reload a large cached context every turn — often millions of tokens
that have nothing to do with how much work a segment did. `aibiller` records
`cache_read` in its own column for transparency but **excludes it from
`total_tok`** (`total = in + out + cache_creation`), so the token total reflects
real work, not background reloads.

---

## Install

**Requirements:** Python 3.8+, git. (Producing the Excel sheet also needs
`openpyxl`; timing and the watcher do not.)

```bash
git clone https://github.com/aa0101181514/ai-biller
cd ai-biller
pip install -r requirements.txt    # only needed for build_log.py (installs openpyxl)
```

No other dependencies; `aibiller.py` and `aibiller_watch.py` are pure standard library.

## Use

```bash
# begin a segment (agent calls this when it starts working)
python3 aibiller.py start myproject "research the API and draft the change"

# ... work happens ...

# end it — writes a CSV row, backfills tokens from the transcript
python3 aibiller.py stop  myproject "drafted PR, 3 files changed"

# is something open? / show the log
python3 aibiller.py status myproject
python3 aibiller.py show   myproject

# build the billing spreadsheet (stop already does this; use to rebuild manually)
python3 build_log.py --project myproject
```

### Per-project data dir

By default every project's CSV lives in `~/.aibiller` (zero config). If you bill
different clients per project, you usually want each case's billing log to sit
**next to that case's folder**, so it can be archived/delivered with the work.
Run `init` once:

```bash
# create <project>_AI_BILLER/ under the project root (or --dir PATH) and remember it
cd /path/to/my-client-case
python3 /path/to/aibiller.py init my-client-case --dir .
# → creates /path/to/my-client-case/my-client-case_AI_BILLER/ with an empty Excel skeleton

# afterwards start/stop need no --dir; they write there, and stop auto-builds the Excel
python3 /path/to/aibiller.py start my-client-case "draft the brief"
python3 /path/to/aibiller.py stop  my-client-case "delivered v1"
# → CSV + Excel both in my-client-case_AI_BILLER/, including this segment
```

`init` records the `<project> → folder` mapping in
`~/.aibiller/.aibiller_projects.json`, so any later `start`/`stop`/`build_log` on
this machine finds the right folder automatically. For a one-off override use
`AIBILLER_PROJECT_DIR=/some/root` (creates `<project>_AI_BILLER/` under it).
Priority: `--dir` > `AIBILLER_PROJECT_DIR` > the dir remembered by `init` > `~/.aibiller`.

> To skip `stop`'s auto-Excel (e.g. CI without openpyxl): `stop ... --no-excel`.

> **Excel language (English / Traditional Chinese)**: English by default. For a
> zh-Hant sheet, pass `--lang zh` to `init` (the language is stored in the
> registry, so `stop`'s auto-Excel uses it too — no env var needed):
> `python3 aibiller.py init my-client-case --dir . --lang zh`. One-off override:
> `AIBILLER_LANG=zh` or `build_log.py --lang zh`. Priority: `AIBILLER_LANG` env >
> the project's registered lang > English default.

### Codex

```bash
python3 aibiller.py start myproject "task" --agent codex
python3 aibiller.py stop  myproject "done" --agent codex
python3 build_log.py --project myproject --agent codex   # separate .xlsx
```

### Recording when the user actually asked (optional)

`--wall` lets you record when the user first asked (e.g. 09:30) even if the
agent only stamped `start` at 09:42. It is kept in the CSV (`wall_min`) for your
own records only — **billing is on AI processing time**, so `--wall` does not
change the billable hours.

```bash
python3 aibiller.py start myproject "task" --wall 09:30
```

---

## Telling your agent to use it

Put something like this in your agent's instructions (e.g. `CLAUDE.md`,
`AGENTS.md`, a system prompt, or a memory):

> When working on a billable project, run
> `python3 /path/to/aibiller.py init <project> --dir .` once in the project root,
> then `python3 /path/to/aibiller.py start <project> "<task>"` at the start of
> each work segment and `... stop <project> "<deliverable>"` when you deliver
> (stop auto-refreshes the Excel). Use `--agent codex` if you are Codex.

The agent still has to remember to do it — there is no magic auto-tracking.

---

## Automatic mode: `aibiller_watch.py` (background daemon)

If you'd rather **not** stamp anything by hand, run the watcher. It sits in the
background, reads the Claude Code / Codex transcripts, groups consecutive
token-usage events into "activity sessions" (a gap longer than the idle
threshold starts a new session), and logs each session's time + tokens — fully
automatic, no start/stop.

```bash
python3 aibiller_watch.py backfill          # build sessions from existing transcripts
python3 aibiller_watch.py daemon            # run continuously (auto-detects activity)
python3 aibiller_watch.py report            # per-agent per-day rollup (sessions/min/tokens)
python3 aibiller_watch.py show --agent codex
```

Options: `--idle N` (idle-gap minutes that ends a session, default 5),
`--interval N` (daemon poll seconds, default 30), `--agents claude,codex`.

### Run it on login (macOS launchd)

Create `~/Library/LaunchAgents/com.aibiller.watch.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.aibiller.watch</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/ABSOLUTE/PATH/TO/ai-biller/aibiller_watch.py</string>
    <string>daemon</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.aibiller.watch.plist   # start + auto-start on login
launchctl unload ~/Library/LaunchAgents/com.aibiller.watch.plist # stop
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

It writes to **separate** files (`aibiller_watch_<agent>.csv`) so it never
touches your manual `aibiller.py` data. For billable, described segments, keep
using `aibiller.py start/stop`.

---

## Configuration (all env vars, all defaulted)

| var | default | meaning |
|-----|---------|---------|
| `AIBILLER_HOME` | `~/.aibiller` | fallback dir for non-`init`'d projects (also holds the registry) |
| `AIBILLER_PROJECT_DIR` | (none) | project root for this call; data goes to `<dir>/<project>_AI_BILLER/` |
| `AIBILLER_TZ_OFFSET` | local tz | timezone offset (hours) for timestamps |
| `AIBILLER_CLAUDE_DIR` | auto `~/.claude/projects/*` | Claude transcript root(s) |
| `AIBILLER_CODEX_DIR` | `~/.codex/sessions` | Codex sessions root |
| `AIBILLER_BILLING_INCREMENT` | `0.25` | billing round-up unit (hours) |
| `AIBILLER_LANG` | `en` | Excel language: `en` / `zh` (Traditional Chinese). `init --lang zh` stores it per-project in the registry |
| `AIBILLER_WATCH_IDLE_MIN` | `5` | watcher: idle-gap minutes that ends a session |
| `AIBILLER_WATCH_INTERVAL_SEC` | `30` | watcher daemon: poll interval seconds |

## CSV columns

```
seq, date, wall_start_iso, wall_end_iso, wall_min,
start_iso, stop_iso, duration_sec, duration_min,
in_tok, out_tok, cache_tok, cache_read_tok, total_tok, task, deliverable
```

See `examples/aibiller_demo.csv` for a sample (fake data).

---

## Limitations (read this)

- **Token backfill is best-effort.** It reads the agents' on-disk transcript
  formats (`usage` for Claude Code, `token_count` events for Codex), which are
  **not public APIs** and may change between versions. If a format changes,
  **timing still works**; tokens may read 0.
- **Very short segments can read 0 tokens** — the last turn may not be flushed
  to the transcript when `stop` runs. Normal-length segments are unaffected.
- **Two modes, two purposes.** `aibiller.py` (manual start/stop) gives precise,
  described, billable segments. `aibiller_watch.py` (background daemon) gives
  effortless but approximate internal reference. Don't bill from the watcher.

## License

MIT — see [LICENSE](LICENSE).
