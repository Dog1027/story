# 檔案說明

這是一個由 LLM（Gemini）即時生成劇情的文字冒險遊戲。設計原則是 **LLM 負責說故事，程式負責記憶與把關**：AI 每回合只「提議」劇情與狀態變化，程式驗證後才寫進遊戲狀態。

程式分成**核心**與**外殼**。核心就像一個 LLM：送文字進去、拿回覆出來（`reply = core.send("往上爬")`），記憶、規則、存檔、遊戲流程都藏在裡面。外殼只負責顯示和輸入。

```
外殼 story/shells/（只負責顯示和輸入）
  textual/   Textual 終端機介面 ─┐
  web.py     瀏覽器殼（包住 textual）│   "往上爬"          Reply（文字＋附帶資料）
  plain.py   純文字 input/print ───┴──────────►  ◄──────────────────
                                            │          ▲
┌──────────── 核心 story/core/ ──────────────▼──────────┴──────────┐
│  session.py：StoryCore.send(text) → Reply                         │
│    解析輸入（行動、數字、/指令）、遊戲階段、存檔、背景壓縮記憶       │
│        │                                                          │
│        ▼                                                          │
│  engine.py：組提示詞 → 呼叫 Gemini → 驗證 AI 的提議 → 套用          │
│  models.py：GameState（= 存檔）、StoryBeat 等 AI 回傳格式            │
│  records.py：存讀檔、回合變化、結局紀錄                              │
└───────────────────────────────────────────────────────────────────┘
```

API key、玩家名字、倒數計時、打字效果屬於外殼。核心只告訴外殼「這回合限時 12 秒」，時間到由外殼送出 `/timeout`。

---

## 原始碼 `src/story/`

```
src/story/
├── __init__.py          main()：依參數選外殼
├── __main__.py          python -m story
├── core/                核心：完全不知道有任何介面，也不 import shells/
│   ├── __init__.py      對外只匯出 StoryCore、Reply、Status 等
│   ├── session.py       StoryCore
│   ├── engine.py        遊戲規則與 AI
│   ├── models.py        資料結構
│   └── records.py       存讀檔、回合變化、結局紀錄
└── shells/              外殼：只透過 story.core 的公開介面跟核心溝通
    ├── textual/
    │   ├── app.py       主畫面 StoryApp
    │   ├── dialogs.py   對話框
    │   ├── style.py     配色、打字節奏
    │   └── commands.py  指令與快捷鍵
    ├── web.py           網頁殼
    ├── plain.py         純文字外殼
    ├── players.py       網頁版的玩家
    └── apikey.py        API key 的存取
```

**相依的方向只有一個**：外殼 → `story.core`。核心不 import 任何外殼；外殼只用 `story.core` 匯出的名稱，不直接 import `engine`、`models` 這些內部模組。

### `__main__.py`：`python -m story` 的進入點

讓 `python -m story` 也能啟動終端機版。網頁殼用 `python -m story --web` 在背景啟動遊戲。

### `__init__.py`：程式進入點

只有 `main()`，負責啟動外殼。`uv run story` 執行的就是這個函式（定義在 `pyproject.toml` 的 `[project.scripts]`）。

- 沒有參數：Textual 外殼 `StoryApp`
- `--web`：網頁模式的 `StoryApp`（由網頁殼使用），先問名字、存檔依名字分開、API key 不存到伺服器
- `--plain`：純文字外殼

## 核心 `core/`

### `core/models.py`：資料結構

所有資料的形狀都定義在這裡，用 Pydantic 寫成。分成兩類：

**AI 回傳的格式**（會轉成 JSON schema 交給 Gemini，強制它照格式回答）

| 類別 | 用途 |
|---|---|
| `StoryBeat` | 每回合的回傳：劇情、選項、狀態增減、物品增減、經過時間、限時秒數、里程碑是否達成、是否結束 |
| `ConditionChange` | AI 回報的一個狀態：名稱、類別（身體／精神）、程度（輕／中／重） |
| `StoryArc`、`Act` | 開場前規劃的隱藏大綱：目標、四幕與各自的里程碑、可能的結局 |
| `Epilogue` | 故事結束後的尾聲與結局名稱 |

**程式保存的狀態**

| 類別 | 用途 |
|---|---|
| `GameState` | 整個遊戲的狀態，存檔就是把它轉成 JSON。包含回合、身體與精神狀況、背包、事實、遊戲內時鐘、大綱進度、分層記憶、目前畫面 |
| `Condition` | 玩家身上的一個狀態，另外記錄在目前程度下經過了多久，用來計算痊癒 |
| `Turn` | 一回合的原文紀錄（劇情 + 玩家行動），用於近期記憶 |

`GameState` 裡的 `_upgrade_old_conditions` 負責相容舊存檔。

### `core/engine.py`：遊戲規則與 AI

負責所有和 AI 的互動，以及遊戲規則。由 `session.py` 呼叫，外殼不會直接用到。

**對外的方法**

| 方法 | 做什麼 |
|---|---|
| `start()` | 開新遊戲：先 `plan_arc()` 規劃大綱，再寫開場 |
| `act()` | 玩家行動後推進一回合 |
| `plan_arc()` | 請 AI 規劃隱藏大綱；舊存檔沒有大綱時依摘要補一份 |
| `suggest_premise()` | 「幫我想」按鈕：程式隨機挑題材與情境，請 AI 想一個故事前提 |
| `write_epilogue()` | 故事結束後請 AI 寫尾聲 |
| `needs_compaction()`、`compact_memory()` | 把舊回合、舊事件與事實壓縮進長期摘要（由核心在背景執行緒呼叫） |

**內部流程**

| 方法 | 做什麼 |
|---|---|
| `_build_prompt()` | 把 `GameState` 組成每回合的提示詞。順序是不常變的在前（前提、模式、故事進度、摘要），每回合會變的在後（近期劇情、狀態、行動） |
| `_progress_section()` | 隱藏的故事進度與節奏提醒（拖太久、進入最後一幕、超過預定長度） |
| `_call_story()` | 呼叫 Gemini 並取得結構化的 `StoryBeat` |
| `_apply()` | **驗證並套用** AI 提議的變化：推進時鐘、處理狀態與背包、推進幕次、限制限時秒數 |
| `_apply_conditions()` | 狀態規則：依時間自然痊癒、好轉一回合最多一級、身體的中重傷不能直接移除 |
| `_write_death()` | 程式判定傷重死亡、但 AI 寫的劇情裡主角還活著時，請 AI 補寫死亡結局 |
| `_log_turn()` | 把每回合的變化寫進 `story_log.jsonl` |

**計算規則的函式**：`clock_text()`（遊戲內時間的文字）、`body_score()`、`body_level()`（傷勢分數與整體狀態，只算身體狀態）、`body_conditions()`、`mind_conditions()`、`is_key_error()`（判斷 Gemini 錯誤是不是 key 無效）。

**可以調整的常數**（都在檔案開頭）

| 常數 | 意義 | 目前值 |
|---|---|---|
| `MODEL` | 使用的 Gemini 模型 | `gemini-3.5-flash-lite` |
| `TARGET_TURNS` | 故事預定長度，超過只提醒收尾 | 40 回合 |
| `RECENT_WINDOW` | 近期記憶保留幾回合原文 | 4 |
| `SUMMARIZE_EVERY` | 累積幾回合就壓縮一次 | 4 |
| `KEEP_EVENTS`、`KEEP_FLAGS` | 重大事件、事實各保留幾條原文 | 6、12 |
| `SEVERITY_POINTS` | 輕／中／重各幾分 | 1／2／4 |
| `DEATH_SCORE`、`DYING_SCORE`、`HEAVY_SCORE` | 死亡、瀕死、重傷的分數門檻 | 8、6、4 |
| `HEAL_TIME` | 身體與精神狀態各程度的痊癒時間 | 見程式 |
| `TIME_SPANS` | AI 選的時間類別換算成幾分鐘 | 見程式 |
| `MIN_TIME_LIMIT`、`MAX_TIME_LIMIT` | 限時模式的秒數範圍 | 8–60 秒 |
| `PREMISE_GENRES`、`PREMISE_SETTINGS` | 「幫我想」隨機挑選的題材與情境 | 14 種、8 種 |
| `SYSTEM_PROMPT` | 給 AI 的寫作與遊戲規則 | — |

### `core/session.py`：最小核心

整個遊戲對外只有一個入口：`StoryCore.send(text) → Reply`。輸入一律是文字，回覆和 LLM 的 API 一樣是「文字＋附帶資料」。

**建立與使用**

```python
core = StoryCore(api_key="…")            # 網頁版另外傳 save_path、log_path
reply = core.start()                     # 第一個回覆：有存檔就問要不要繼續，否則請你輸入前提
reply = core.send("往上爬")               # 之後每一句輸入
print(reply.text)                        # 只會印文字的外殼，這樣就能完整地玩

core.action_for("2")                     # → "躲起來"：這句輸入代表的行動，讓外殼送出前先顯示
core.set_api_key("…")                    # key 失效時換一個
```

外殼只能用這四個方法，以及讀 `Reply` 的欄位，不直接讀核心的屬性，也不 import engine。這樣核心內部怎麼改都不會影響外殼。

**`Reply` 的欄位**

| 欄位 | 內容 |
|---|---|
| `phase` | 目前階段：`ask_continue`（找到存檔）、`ask_premise`（等前提）、`playing`、`confirm_restart`、`ending`（剛結束，下一句會寫尾聲）、`ended` |
| `timed` | 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式） |
| `text` | 完整的純文字 |
| `narration` | 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串 |
| `choices` | 選項 |
| `status` | 狀態列資料（`Status`）：回合、整體狀態、身體、精神、背包 |
| `changes` | 這回合的變化：新增、惡化、好轉、痊癒、獲得、失去 |
| `time_limit` | 限時秒數，0 代表不限時 |
| `notice` | 簡短的系統訊息 |
| `resumed` | 這次是讀取存檔、重新顯示上次的劇情 |
| `info` | 要另外顯示的內容（標題, 內容），例如 `/state`、`/help` |
| `premise_default`、`suggestion` | 等前提時：留白會用的前提、`/suggest` 想出來的前提 |
| `ending` | 結束時：結局名稱、尾聲、旅程紀錄 |
| `error` | `api_key`：key 無效，外殼換 key（`core.set_api_key()`）後可以重送同一句；`api`：其他錯誤 |

**輸入**

| 輸入 | 何時 | 作用 |
|---|---|---|
| 數字、選項文字 | 有選項時 | 選擇該選項 |
| 任意文字 | 遊戲中 | 自由行動 |
| 任意文字、空白 | 等前提時 | 故事前提；空白使用預設（或剛才 `/suggest` 想出來的） |
| `/suggest`、`/timed on`、`/timed off` | 等前提時 | 讓 AI 想開頭、切換限時模式 |
| `/timeout` | 遊戲中 | 外殼的倒數時間到了 |
| `/restart` | 遊戲中、結束後 | 重新開始（遊戲中會先確認） |
| `/state`、`/help` | 任何時候 | 記憶、說明 |

**內部**：每個階段一個處理函式（`_on_playing()` 等）；LLM 失敗時從存檔還原、留在原階段；回合結束後在背景執行緒壓縮記憶，下一次呼叫 LLM 前會先等它完成；`render_text()` 負責組出純文字。

### `core/records.py`：紀錄工具

| 名稱 | 做什麼 |
|---|---|
| `save()`、`load()` | 存讀存檔（終端機版 `save.json`，網頁版由 `players.py` 指定路徑）。存檔是**原子性寫入**：先寫暫存檔再一次換上去，背景壓縮記憶時同時存檔、或寫到一半被關掉，都不會讀到壞掉的存檔 |
| `snapshot()`、`change_groups()` | 比較回合前後，列出「新增／惡化／好轉／痊癒／獲得／失去」（放進 `Reply.changes`）。每個項目帶的是**語氣**（`輕`／`中`／`重`／`good`／`bad`／`plain`／`muted`），不是顏色，由外殼決定怎麼呈現 |
| `ending_record()` | 結局的旅程紀錄（回合數、天數、重大事件） |
| `memory_text()` | 「程式記住的東西」顯示的內容 |
| `DEFAULT_PREMISE` | 預設的故事前提 |

---

## 外殼 `shells/`

### `shells/textual/`：Textual 外殼

用 [Textual](https://textual.textualize.io/) 寫成的終端機介面。只負責顯示和輸入：把玩家的輸入轉成文字送給核心，再依照 `Reply` 的階段和欄位更新畫面。不呼叫 engine，也不碰 `GameState`。

**`dialogs.py`：對話框**

| 類別 | 用途 |
|---|---|
| `Dialog` | 所有對話框共用的樣式，以及方向鍵規則（←→ 在按鈕間移動、↑↓ 在列之間移動） |
| `ApiKeyDialog` | 輸入 Gemini API key（網頁模式不提供儲存） |
| `NameDialog` | 網頁模式：輸入名字並佔用 |
| `PremiseDialog` + `PremiseArea` | 新故事：多行輸入框、限時模式勾選、「幫我想」按鈕（送 `/suggest` 給核心） |
| `ConfirmDialog` | 是／否確認（找到存檔、重新開始） |
| `EndingDialog` | 結局名稱、旅程紀錄、再玩一次 |
| `InfoDialog` | 顯示 `Reply.info`（記憶、說明） |

**`app.py`：主畫面 `StoryApp`**

| 方法 | 做什麼 |
|---|---|
| `boot()` | 取得名字（網頁模式）與 API key，建立 `StoryCore`，顯示第一個回覆 |
| `send()`、`ask_core()` | 把一句文字送給核心（在背景執行緒，超過 0.15 秒才顯示「故事生成中…」）；key 無效時請玩家換 key 後重送 |
| `handle()` | 依 `reply.phase` 決定要跳出哪個對話框、顯示劇情或結局 |
| `show_turn()` | 打字效果顯示劇情，打完才顯示變化摘要、更新狀態列、出現選項與倒數 |
| `show_ending()` | 尾聲 → 按 Enter → 結局對話框 |
| `set_status()` | 用 `Reply.status` 畫狀態列；最右邊固定顯示模式 |
| `start_timer()`、`tick()` | 限時倒數（開著對話框時暫停），時間到送 `/timeout` |
| `submit()` | 處理輸入框：打字中按 Enter 加速、指令、數字選項、自由行動 |

**輔助函式**：`describe_changes()`，把 `Reply.changes` 依語氣轉成彩色文字。

**`style.py`：外觀**

| 常數 | 意義 |
|---|---|
| `THEME` | 配色主題（`tokyo-night`，可換成 `catppuccin-mocha`、`rose-pine`、`nord` 等） |
| `CHAR_DELAY`、`FAST_FACTOR`、`PAUSE_AFTER` | 打字效果的速度、按 Enter 後的加速倍率、標點停頓 |
| `SEVERITY_COLORS`、`LEVEL_COLORS`、`TONE_STYLES` | 狀態程度、整體狀態、變化語氣的顏色 |

**`commands.py`：指令與快捷鍵**

`COMMANDS` 定義四個指令（`/state`、`/restart`、`/help`、`/quit`）的快捷鍵與說明；`help_text()` 產生 F1 說明的內容。

新增遊戲指令時，先在 `core/session.py` 的 `send()` 或對應階段的處理函式加上處理；若要有快捷鍵，再到這裡加一行，並在 `app.py` 的 `StoryApp` 加上 `action_<名稱>` 方法。

### `shells/plain.py`：純文字外殼

只用 `input()` 和 `print()` 跟核心對話，不到 30 行。示範核心可以接任何外殼：`uv run story --plain`。



### `shells/web.py`：網頁殼

用 [textual-serve](https://github.com/Textualize/textual-serve) 把終端機版原封不動地放進瀏覽器。每開一個分頁，伺服器就在背景用 `python -m story --web` 啟動一個網頁模式的遊戲，畫面透過網頁上的終端機模擬器（xterm.js）顯示。這裡不寫任何介面或遊戲邏輯，所以改功能時只要改 Textual 外殼，網頁版會一起變。

| 名稱 | 做什麼 |
|---|---|
| `LimitedServer` | 限制同時在線人數（`MAX_SESSIONS`），滿了就顯示提示並關閉連線 |
| `game_command()` | 每個連線要啟動的遊戲指令 |
| `main()` | `uv run story-web` 的進入點；參數 `--host`、`--port`、`--public-url` |

預設只監聽 `127.0.0.1`。`--host 0.0.0.0` 會開放其他電腦連線，但目前沒有 HTTPS，玩家的 API key 會以明文傳送。

### `shells/players.py`：網頁版的玩家

| 名稱 | 做什麼 |
|---|---|
| `check_name()` | 檢查名字：不能空白、最多 20 字、只能有文字數字底線連字號（名字會變成檔名，所以擋掉 `../` 這類字元） |
| `Player` | 一個玩家的存檔、紀錄檔、鎖定檔路徑（都在 `saves/`）；`acquire()` 佔用名字，`release()` 釋放 |

同一個名字同時只能有一個連線：佔用時建立 `saves/名字.lock`，裡面記錄程序編號。連線異常中斷沒有釋放時，下一個人會發現那個程序已經不存在，直接接手。

### `shells/apikey.py`：API key 的存取

| 函式 | 做什麼 |
|---|---|
| `get_saved_api_key()` | 依序從環境變數（`GEMINI_API_KEY`、`GOOGLE_API_KEY`）、設定檔取得 key |
| `save_api_key()` | 存到 `~/.config/story/api_key`，權限 600（只有自己能讀） |
| `forget_api_key()` | 刪除已儲存的 key（key 無效時使用） |

---

## 測試 `tests/`

```bash
uv run pytest                  # 全部（約 30 秒）
uv run pytest -m "not slow"    # 略過會啟動真的伺服器的測試（約 10 秒）
```

測試都不會連到 Gemini，也不會動到你真的存檔或 API key：每個測試都在暫存資料夾裡執行，AI 的回覆由假物件提供。

| 檔案 | 驗證什麼 |
|---|---|
| `conftest.py` | 共用的假物件：`FakeGemini`（假的 Gemini，讓真的 Engine 跑規則）、`FakeEngine`（假的 engine，讓核心與外殼的測試能精準控制每回合）、`beat()`、`cond()` |
| `test_engine.py` | 遊戲規則：狀態增減與好轉限制、身體／精神、整體狀態與死亡、時間與痊癒、限時秒數、背包與事實、大綱與節奏提醒、提示詞內容、記憶壓縮 |
| `test_records.py` | 存讀檔、舊存檔相容、回合變化的語氣、結局紀錄 |
| `test_core.py` | 核心的文字協定：開新局、幫我想、限時切換、`action_for()`、各種指令、key 失效與重送、重新開始、結局、讀檔接續 |
| `test_players.py` | 名字檢查、同名鎖定、接手異常中斷的鎖 |
| `test_textual.py` | Textual 外殼：模擬按鍵跑完整流程，包括打字與狀態列時機、倒數與暫停、對話框方向鍵、結局、讀檔、網頁模式 |
| `test_shells.py` | 純文字外殼玩完整局；網頁殼（`slow`）：每個連線是獨立的遊戲、同時在線人數上限 |

改了遊戲規則或流程後跑一次 `uv run pytest`，就能確認原本的功能沒有被弄壞。新增功能時，在對應的測試檔加上測試。

---

## 專案設定

| 檔案 | 用途 |
|---|---|
| `pyproject.toml` | 專案設定：相依套件（`google-genai`、`pydantic`、`textual`、`textual-serve`）、開發用套件（`pytest`、`pytest-asyncio`）、執行指令 `story` 與 `story-web`、pytest 設定 |
| `uv.lock` | `uv` 鎖定的套件版本，確保每台電腦裝到一樣的版本 |
| `.python-version` | 使用的 Python 版本（3.14） |
| `.gitignore` | 不進版本控制的檔案：虛擬環境、存檔、紀錄檔等 |
| `README.md` | 專案說明 |
| `docs/files.md` | 本文件 |

## 執行時產生的檔案（不進版本控制）

| 檔案 | 用途 |
|---|---|
| `save.json` | 終端機版的存檔，每回合自動更新。內容就是 `GameState` |
| `saves/名字.json`、`saves/名字.log.jsonl`、`saves/名字.lock` | 網頁版每個玩家的存檔、每回合紀錄、在線鎖定 |
| `story_log.jsonl` | 終端機版每回合一行的紀錄：玩家行動、AI 提議的變化、套用前後的狀態、遊戲內時間。用來查「為什麼會這樣」 |
| `~/.config/story/api_key` | 儲存的 API key（在家目錄，不在專案裡） |

這些檔案會產生在執行 `uv run story` 或 `uv run story-web` 時所在的資料夾。
