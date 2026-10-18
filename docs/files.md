# 檔案說明

這是一個由 LLM（Gemini）即時生成劇情的文字冒險遊戲。設計原則是 **LLM 負責說故事，程式負責記憶與把關**：AI 每回合只「提議」劇情與狀態變化，程式驗證後才寫進遊戲狀態。

```
玩家行動
   │
   ▼
ui.py ──────► engine.py ──────► Gemini
（介面）       （組提示詞）        （寫劇情、提議變化）
   ▲              │
   │              ▼
   │         驗證並套用到 GameState（models.py）
   │              │
   └──── 顯示劇情、變化摘要、更新狀態列 ◄──┘
                  │
                  ▼
            save.json / story_log.jsonl
```

---

## 原始碼 `src/story/`

### `__init__.py`：程式進入點

只有 `main()`，負責啟動介面 `StoryApp`。`uv run story` 執行的就是這個函式（定義在 `pyproject.toml` 的 `[project.scripts]`）。

### `models.py`：資料結構

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

### `engine.py`：Harness 核心

遊戲的大腦，負責所有和 AI 的互動，以及遊戲規則。不依賴介面，可以單獨測試。

**對外的方法**

| 方法 | 做什麼 |
|---|---|
| `start()` | 開新遊戲：先 `plan_arc()` 規劃大綱，再寫開場 |
| `act()` | 玩家行動後推進一回合 |
| `plan_arc()` | 請 AI 規劃隱藏大綱；舊存檔沒有大綱時依摘要補一份 |
| `suggest_premise()` | 「幫我想」按鈕：程式隨機挑題材與情境，請 AI 想一個故事前提 |
| `write_epilogue()` | 故事結束後請 AI 寫尾聲 |
| `needs_compaction()`、`compact_memory()` | 把舊回合、舊事件與事實壓縮進長期摘要（由介面在背景呼叫） |

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

**計算規則的函式**：`clock_text()`（遊戲內時間的文字）、`body_score()`、`body_level()`（傷勢分數與整體狀態，只算身體狀態）、`body_conditions()`、`mind_conditions()`。

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

### `ui.py`：終端機介面

用 [Textual](https://textual.textualize.io/) 寫成的介面，負責顯示、輸入、存讀檔與遊戲流程。所有 AI 呼叫都透過 `Engine`，自己不寫遊戲規則。

**對話框**

| 類別 | 用途 |
|---|---|
| `Dialog` | 所有對話框共用的樣式，以及方向鍵規則（←→ 在按鈕間移動、↑↓ 在列之間移動） |
| `ApiKeyDialog` | 輸入 Gemini API key |
| `PremiseDialog` + `PremiseArea` | 新故事：多行輸入框、限時模式勾選、「幫我想」按鈕 |
| `ConfirmDialog` | 是／否確認 |
| `EndingDialog` | 結局名稱、旅程紀錄、再玩一次 |
| `InfoDialog` | 說明與記憶檢視 |

**主畫面 `StoryApp`**

| 方法 | 做什麼 |
|---|---|
| `boot()` | 啟動流程：取得 key → 讀存檔或開新局 |
| `new_game()`、`act()` | 開新局、送出行動 |
| `generate()` | 在背景執行緒呼叫 AI，期間顯示「故事生成中…」；key 無效時請玩家重新輸入 |
| `show_turn()` | 打字效果顯示劇情，打完才顯示變化摘要並更新狀態列 |
| `show_ending()` | 尾聲 → 按 Enter → 結局對話框 |
| `compact_in_background()` | 玩家讀劇情時在背景壓縮記憶 |
| `set_status()` | 狀態列：回合、整體狀態、身體與精神狀況、背包；最右邊固定顯示模式 |
| `start_timer()`、`tick()` | 限時模式的倒數（開著對話框時暫停） |
| `submit()` | 處理輸入框：指令、數字選項、自由行動、打字中按 Enter 加速 |

**輔助函式**：`save()`、`load()`（存讀檔）、`snapshot()`、`describe_changes()`（比較回合前後，產生「新增／惡化／痊癒／獲得」那一行）、`memory_text()`（`/state` 顯示的內容）。

**可以調整的常數**：`THEME`（配色主題）、`CHAR_DELAY`、`FAST_FACTOR`、`PAUSE_AFTER`（打字速度與停頓）、`SEVERITY_COLORS`、`LEVEL_COLORS`（狀態顏色）、`DEFAULT_PREMISE`（預設故事前提）。

### `commands.py`：指令清單

`COMMANDS` 定義四個指令（`/state`、`/restart`、`/help`、`/quit`）的快捷鍵與說明；`help_text()` 產生 F1 說明的內容。新增指令時，在這裡加一行，再到 `ui.py` 的 `StoryApp` 加上對應的 `action_<名稱>` 方法。

### `apikey.py`：API key 管理

| 函式 | 做什麼 |
|---|---|
| `get_saved_api_key()` | 依序從環境變數（`GEMINI_API_KEY`、`GOOGLE_API_KEY`）、設定檔取得 key |
| `save_api_key()` | 存到 `~/.config/story/api_key`，權限 600（只有自己能讀） |
| `forget_api_key()` | 刪除已儲存的 key（key 無效時使用） |
| `is_key_error()` | 判斷 API 錯誤是不是 key 無效造成的 |

---

## 專案設定

| 檔案 | 用途 |
|---|---|
| `pyproject.toml` | 專案設定：相依套件（`google-genai`、`pydantic`、`textual`）、執行指令 `story` |
| `uv.lock` | `uv` 鎖定的套件版本，確保每台電腦裝到一樣的版本 |
| `.python-version` | 使用的 Python 版本（3.14） |
| `.gitignore` | 不進版本控制的檔案：虛擬環境、存檔、紀錄檔等 |
| `README.md` | 專案說明（目前是空的） |
| `docs/files.md` | 本文件 |

## 執行時產生的檔案（不進版本控制）

| 檔案 | 用途 |
|---|---|
| `save.json` | 存檔，每回合自動更新。內容就是 `GameState` |
| `story_log.jsonl` | 每回合一行的紀錄：玩家行動、AI 提議的變化、套用前後的狀態、遊戲內時間。用來查「為什麼會這樣」 |
| `~/.config/story/api_key` | 儲存的 API key（在家目錄，不在專案裡） |

這兩個檔案（`save.json`、`story_log.jsonl`）會產生在執行 `uv run story` 時所在的資料夾。
