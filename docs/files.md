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
├── genres/              題材包（每個題材一個資料夾，見 docs/genres.md）
├── prompts/             給 AI 的提示詞，每種語言一個資料夾（zh-TW/）；怎麼改見 prompts/README.md
├── ui/                  給玩家看的介面文字，每種語言一個資料夾（zh-TW/）
├── preview.py           預覽送給 AI 的完整提示詞（just prompts），不會呼叫 AI
├── evals.py             評估 AI 寫得好不好（just eval），會呼叫真的 AI
├── core/                核心：完全不知道有任何介面，也不 import shells/
│   ├── __init__.py      對外只匯出 StoryCore、Reply、Status 等
│   ├── session.py       StoryCore（單人）
│   ├── party.py         多人模式：PartyEngine（繼承 Engine）、PartyCore（繼承 StoryCore）
│   ├── genres.py        題材包的讀取與檢查
│   ├── prompts.py       讀取 prompts/ 的提示詞與 ui/ 的介面文字
│   ├── engine.py        遊戲規則與 AI
│   ├── models.py        資料結構
│   └── records.py       存讀檔、回合變化、結局紀錄
└── shells/              外殼：只透過 story.core 的公開介面跟核心溝通
    ├── client.py        外殼共用層：跟真人互動的流程（各介面共用）
    ├── textual/         終端機介面：只負責長相，流程交給 client.py
    │   ├── app.py       主畫面 StoryApp
    │   ├── dialogs.py   對話框
    │   ├── style.py     配色、打字節奏
    │   ├── prose.py     懂中文的換行
    │   └── commands.py  指令與快捷鍵
    ├── web/             網頁介面：伺服器、WebView、瀏覽器頁面（static/），流程交給 client.py
    ├── room.py          線上多人的房間
    ├── plain.py         純文字外殼
    ├── players.py       網頁版的玩家
    ├── apikey.py        API key 的存取
    └── prefs.py         偏好設定（配色主題）
```

**相依的方向只有一個**：介面 → 共用層（`client.py`）→ `story.core`。核心不 import 任何外殼；外殼只用 `story.core` 匯出的名稱，不直接 import `engine`、`models` 這些內部模組。介面（`textual/`、網頁的 `web/view.py`）不自己建立核心、不直接連房間，流程一律交給共用層。這兩條規則都有測試把關（`test_shells.py`）。

新功能放哪裡：改變遊戲結果或事實 → 核心；改變真人看到的順序、時機、流程 → 共用層；改變長相 → 各介面。

### `__main__.py`：`python -m story` 的進入點

讓 `python -m story` 也能啟動終端機版。

### `__init__.py`：程式進入點

只有 `main()`，負責啟動外殼。`uv run story` 執行的就是這個函式（定義在 `pyproject.toml` 的 `[project.scripts]`）。

- 沒有參數：Textual 外殼 `StoryApp`
- `--plain`：純文字外殼

網頁版（包括線上多人）是另一個指令 `story-web`（`shells/web/`）。

## 核心 `core/`

### `core/models.py`：資料結構

所有資料的形狀都定義在這裡，用 Pydantic 寫成。

**遊戲詞彙**：狀態的程度（`Severity`：`light`／`moderate`／`severe`）、類別（`ConditionKind`：`body`／`mind`）、經過的時間（`TimeSpan`）、時段（`TimeOfDay`）、身體的整體狀態（`Level`：`healthy`……`dead`）在程式與存檔裡都是語言無關的代號。給 AI 看、讓 AI 回傳、顯示給玩家時，換成 `prompts/語言/vocab.md` 裡這個語言的詞：`word(類別, 代號)` 換成詞，`code(類別, 詞)` 換回代號；AI 回傳格式裡的選項用 `words(類別)` 產生，所以 AI 看到、回傳的都是它的語言。讀取舊存檔時，中文的詞會換成代號（`OLD_WORDS`）。

資料分成兩類：

**AI 回傳的格式**（會轉成 JSON schema 交給 Gemini，強制它照格式回答）

| 類別 | 用途 |
|---|---|
| `StoryBeat` | 每回合的回傳：劇情、選項、狀態增減、物品增減、經過時間、限時秒數、里程碑是否達成、是否結束 |
| `ConditionChange` | AI 回報的一個狀態：名稱、類別、程度（這個語言的詞，例如身體／精神、輕／中／重；套用時由程式換成代號） |
| `StoryArc`、`Act` | 開場前規劃的隱藏大綱：目標、隱藏的真相（`twist`，第三幕揭露）與伏筆（`clues`）、四幕與各自的里程碑、可能的結局。舊存檔沒有真相與伏筆時補空值 |
| `GenrePick` | 玩家選「自動」題材時，AI 挑的題材名稱 |
| `Epilogue` | 故事結束後的尾聲與結局名稱 |
| `PartyBeat`、`CharacterUpdate` | 多人模式每回合的回傳：一段包含所有角色的劇情，加上每位角色各自的狀態、物品變化與選項 |

單人模式和多人模式用不同的回傳格式，單人模式送給 AI 的內容因此不受多人模式影響。

**程式保存的狀態**

| 類別 | 用途 |
|---|---|
| `GameState` | 整個遊戲的狀態，存檔就是把它轉成 JSON。包含回合、身體與精神狀況、背包、事實、遊戲內時鐘、大綱進度、分層記憶、目前畫面。`party` 是多人模式的隊伍，空的代表單人模式 |
| `Character` | 多人模式的一位角色：名字、狀態、背包、目前的選項、是否還活著 |
| `Condition` | 玩家身上的一個狀態，另外記錄在目前程度下經過了多久，用來計算痊癒 |
| `Turn` | 一回合的原文紀錄（劇情 + 玩家行動），存在劇情紀錄裡 |

`GameState` 裡的 `_upgrade_old_conditions` 負責相容舊存檔。

### `core/engine.py`：遊戲規則與 AI

負責所有和 AI 的互動，以及遊戲規則。由 `session.py` 呼叫，外殼不會直接用到。

**對外的方法**

| 方法 | 做什麼 |
|---|---|
| `start()` | 開新遊戲：題材選「自動」時先 `pick_genre()`，再 `plan_arc()` 規劃大綱，最後寫開場 |
| `act()` | 玩家行動後推進一回合 |
| `pick_genre()` | 題材選「自動」：給 AI 題材目錄，依故事前提挑一個；不在目錄裡就不套用 |
| `plan_arc()` | 請 AI 規劃隱藏大綱，附上題材的指引、命名素材與隨機抽的轉折靈感；舊存檔沒有大綱時依摘要補一份 |
| `suggest_premise()` | 「幫我想」按鈕：程式隨機挑題材與情境，請 AI 想一個故事前提 |
| `write_epilogue()` | 故事結束後請 AI 寫尾聲 |
| `needs_compaction()`、`compact_memory()` | 劇情紀錄超過 `HISTORY_BUDGET` 時，把最舊的回合壓縮進長期摘要；舊事件與事實太多時也一併併入（由核心在背景執行緒呼叫）。30 回合的故事大約只有七、八千字，通常不會觸發 |

**內部流程**

| 方法 | 做什麼 |
|---|---|
| `_build_prompt()`、`_context()` | 把 `GameState` 組成每回合的提示詞：故事內容（`_context()`）加上這回合的指示。尾聲與傷重死亡的場景也是故事內容加上各自的指示。Gemini 的自動快取只認開頭完全相同的部分，所以順序是：前提、模式 → 摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度、狀態（隨劇情改變）→ 指示 |
| `_progress_section()` | 隱藏的故事進度與節奏提醒（拖太久、進入最後一幕、超過預定長度） |
| `_twist_lines()` | 隱藏的真相：前兩幕列出真相與伏筆、叫 AI 不要說破；第三幕要揭露；最後一幕當作已知 |
| `_call()` | 串流呼叫 Gemini 取得結構化的 `StoryBeat`：收到劇情的同時更新 `draft`（外殼可以邊收邊顯示）。`game_over` 是 AI 第一個輸出的欄位，太早宣告結局時在劇情出現之前就中斷（`EndingTooEarly`），請 AI 重寫 |
| `partial_string()`、`partial_bool()` | 從還沒生成完的 JSON 取出目前收到的欄位內容（串流用） |
| `_apply()` | **驗證並套用** AI 提議的變化：推進時鐘、處理狀態與背包、推進幕次、限制限時秒數 |
| `_apply_conditions()` | 狀態規則：依時間自然痊癒、好轉一回合最多一級、身體的中重傷不能直接移除 |
| `_write_death()` | 程式判定傷重死亡、但 AI 寫的劇情裡主角還活著時，請 AI 補寫死亡結局 |
| `_log_turn()` | 把每回合的變化寫進 `story_log.jsonl`，並附上這段期間的 AI 呼叫（`calls`） |
| `_generate()`、`_stream()` | 所有 AI 呼叫都經過這兩個（一次拿完整結果／串流）：記下種類、秒數與 token 用量（送出、命中快取、輸出、思考），由 `_write_log()` 寫進紀錄；串流因為太早結局而中斷的呼叫標成 `stopped` |

**給多人模式覆寫的掛勾**（這裡是單人的版本）：類別屬性 `system_prompt`、`beat_schema`、`turn_label`、`epilogue_look_back`，以及 `_cast_section()`（規劃大綱時的主角名單）、`_action_text()`（記在劇情紀錄裡的行動）、`_status_section()`（提示詞裡的狀態區塊）、`_instruction_sections()`（提示詞最後的行動與指示）。提示詞的其他部分、呼叫 AI（`_call()`）、尾聲、大綱、記憶壓縮都由單人與多人共用。

**套用規則的函式**（單人、多人共用，單人傳 `GameState`、多人傳 `Character`）：`advance_clock()`、`apply_condition_changes()`、`apply_items()`、`apply_story_progress()`、`clamp_time_limit()`。

**計算規則的函式**：`clock_text()`（遊戲內時間的文字）、`body_score()`、`body_level()`（傷勢分數與整體狀態，只算身體狀態）、`warning_level()`（整體狀態是 `WARNING_LEVELS`（重傷、瀕死）時要警告玩家：再受傷就有生命危險）、`body_conditions()`、`mind_conditions()`、`is_key_error()`（判斷 Gemini 錯誤是不是 key 無效）、`new_client()`（建立 Gemini client：每次請求有逾時，逾時或伺服器忙時自動重送）。

**可以調整的常數**（都在檔案開頭）

| 常數 | 意義 | 目前值 |
|---|---|---|
| `MODEL` | 使用的 Gemini 模型 | `gemini-3.5-flash-lite` |
| `TARGET_TURNS` | 故事預定長度，超過只提醒收尾 | 30 回合 |
| `MIN_ACT_TURNS` | 每一幕至少幾回合；還沒到時 AI 說里程碑達成也不推進 | 5 回合 |
| `TWIST_IDEAS` | 規劃大綱時從題材包的 `twists.md` 隨機抽幾則轉折靈感 | 3 則 |
| `MIN_ENDING_TURN` | 最早第幾回合才接受 AI 宣告的結局（還要進到最後一幕；超過 `TARGET_TURNS` 一律接受）。太早寫出結局時請 AI 重寫一次，還是結局就忽略。因傷死亡不受限制 | 20 回合 |
| `HISTORY_BUDGET` | 劇情紀錄保留原文的字數上限，超過才把最舊的部分壓縮進摘要（一次壓到剩一半） | 20,000 字 |
| `KEEP_EVENTS`、`KEEP_FLAGS` | 重大事件、事實各保留幾條原文 | 6、12 |
| `SEVERITY_POINTS` | 輕／中／重（`light`／`moderate`／`severe`）各幾分 | 1／2／4 |
| `DEATH_SCORE`、`DYING_SCORE`、`HEAVY_SCORE` | 死亡、瀕死、重傷的分數門檻 | 8、6、4 |
| `HEAL_TIME` | 身體與精神狀態各程度的痊癒時間 | 見程式 |
| `TIME_SPANS` | AI 選的時間類別換算成幾分鐘 | 見程式 |
| `MIN_TIME_LIMIT`、`MAX_TIME_LIMIT` | 限時模式的秒數範圍 | 8–60 秒 |
| `REQUEST_TIMEOUT`、`REQUEST_ATTEMPTS` | 一次 AI 請求最多等幾秒；逾時或伺服器忙（429、5xx）時最多送幾次 | 40 秒、3 次 |
| `PREMISE_GENRES`、`PREMISE_SETTINGS` | 「幫我想」隨機挑選的題材與情境（`prompts/語言/premise.md`） | 14 種、8 種 |
| `SYSTEM_PROMPT` | 給 AI 的寫作與遊戲規則（`prompts/語言/system.md`） | — |
| `CONTEXT`、`TURN`、`PROGRESS`、`PLAN`、`PREMISE`、`MEMORY` | 故事內容、每回合的指示、故事進度的提醒、規劃大綱、幫我想、記憶壓縮的提示詞（`prompts/語言/` 裡同名的檔案） | — |

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
core.progress                            # send() 執行中目前在做什麼，例如「規劃故事大綱」（可在另一個執行緒讀）
core.draft                               # send() 執行中 AI 正在寫的劇情（串流中目前收到的部分，可在另一個執行緒讀）
core.phase                               # 目前的遊戲階段（唯讀），和最近一次回覆的 reply.phase 相同
```

開新故事要呼叫兩次 AI（先規劃大綱、再寫開場），比一般回合久，所以 engine 會把目前的階段記在 `stage`，外殼讀 `core.progress` 顯示在「故事生成中」那一行；線上多人由房間把進度推給所有人。

劇情是串流產生的：AI 寫的同時，engine 把目前收到的劇情記在 `draft`，外殼讀 `core.draft` 邊收邊顯示，第一個字通常一秒左右就出現。`send()` 的回傳跟以前一樣，`Reply.narration` 才是最後的完整內容（可能比串流的長，例如程式判定傷重死亡時接著補寫的場景）。

外殼只能用這幾個方法與屬性（多人模式另外有 `send_as()`、`view()`、`waiting()` 與唯讀的 `players`，見 `core/party.py`），以及讀 `Reply` 的欄位，不直接讀核心的其他屬性（例如 `core.state`），也不 import engine。這樣核心內部怎麼改都不會影響外殼。`test_shells.py` 的 `test_shells_only_use_the_public_core_interface` 會掃描所有外殼的原始碼，確認這條規則沒有被打破。

**`Reply` 的欄位**

| 欄位 | 內容 |
|---|---|
| `phase` | 目前階段：`ask_continue`（找到存檔）、`ask_premise`（等前提）、`playing`、`confirm_restart`、`ending`（剛結束，下一句會寫尾聲）、`ended` |
| `timed` | 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式） |
| `text` | 完整的純文字 |
| `narration` | 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串 |
| `choices` | 選項 |
| `turn` | 目前是第幾回合（還沒開始故事時是 0） |
| `characters` | 每位角色的狀態列資料（`Status`）。單人模式只有主角一位、`name` 是空的，所以外殼單人多人用同一套顯示。`Status` 有：目前的狀態 `conditions`（名稱, 程度），身體在前、精神在後；要不要警告 `warning`（重傷、瀕死，由核心判斷）；多人模式的 `name`、`alive`。背包不在這裡：變化在 `changes`，完整內容用 `/state` 看 |
| `changes` | 這回合有變化的角色：(名字, 變化)，變化是新增、惡化、好轉、痊癒、獲得、失去。單人模式名字是空的 |
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
| `/away` | 遊戲中（多人） | 這位角色暫時離開、這回合不行動（線上多人替斷線的人送出）。給 AI 的文字是 `AWAY_ACTION`，跟 `/timeout` 的 `TIMEOUT_ACTION` 一樣由核心決定 |
| `/restart` | 遊戲中、結束後 | 重新開始（遊戲中會先確認） |
| `/state`、`/help` | 任何時候 | 記憶、說明 |

**給多人模式覆寫的掛勾**：`_resumable()`、`_new_state()`、`_current_choices()`、`_take_action()`、`_snapshot()`、`_turn_failed()`，見下面的 `core/party.py`。

**內部**：每個階段一個處理函式（`_on_playing()` 等）；LLM 失敗時從存檔還原、留在原階段；回合結束後在背景執行緒壓縮記憶，下一次呼叫 LLM 前會先等它完成；`render_text()` 負責組出純文字。

### `core/party.py`：多人模式

多人模式疊在單人模式上：`PartyEngine` 繼承 `Engine`、`PartyCore` 繼承 `StoryCore`，只覆寫「主角變成一支隊伍」不一樣的地方。規則（傷勢、痊癒、時間、背包、限時）、記憶、大綱與節奏、存檔、文字指令、錯誤處理都直接沿用單人模式。

**`PartyEngine`**：系統提示詞換成 `PARTY_SYSTEM_PROMPT`（`prompts/party_system.md`）、每回合的指示換成 `prompts/party_turn.md`、回傳格式換成 `PartyBeat`；提示詞的狀態區塊改成「隊伍」，並由程式輪流指定「焦點」角色；`_apply()` 對每位角色各自套用單人的規則，傷重的角色倒下（`_write_deaths()` 請 AI 補寫倒下的場景），全員倒下就結束。

**`PartyCore(api_key, players, save_path=…, log_path=…)`**：線上多人的房間（`shells/room.py`）用它，存檔與紀錄的位置由房間決定。介面一樣是 `send(文字) → Reply`。覆寫 `StoryCore` 的掛勾：

| 掛勾 | 單人模式 | 多人模式 |
|---|---|---|
| `_resumable()` | 沒結束的存檔就能接續 | 還要玩家名單相同 |
| `_new_state()` | 一位主角 | 建立隊伍 |
| `_current_choices()` | 主角的選項 | 送出輸入的那位角色的選項 |
| `_take_action()` | 直接推進一回合 | 先記下這位角色的行動，所有人都行動後才推進；`/timeout` 時還沒行動的人都算遲疑 |
| `_snapshot()`、`_turn_reply()` | 主角的變化 | 每位角色各自的變化 |
| `_turn_failed()` | 不用做事 | 撤回這回合所有人的行動，大家重新選擇（時間到或替離線的人填入的行動失敗時，才不會每個人都「已行動」卻沒人能重送而卡住）。線上多人時房間把錯誤送給每個人，限時模式重新倒數 |

回覆的差別：`reply.actor` 是這回合還能行動的角色；`reply.characters`、`reply.changes` 有每位角色（名字不是空的）。

每位玩家的輸入用 `send_as()` 送；不屬於某位玩家的輸入（時間到、房主的回答、寫尾聲）用 `send()`。另外幾個給房間用的方法：

| 方法 | 做什麼 |
|---|---|
| `send_as(名字, 文字)` | 以某位角色的身分送出輸入，誰先送誰先記；已經行動或倒下的人會收到提示 |
| `players` | 隊伍裡的玩家名字（唯讀） |
| `view(名字, reply=None)` | 某位玩家眼中的畫面：`actor`、`choices` 換成這位角色的。沒給 reply 時是目前這回合的畫面（重新連線用） |
| `waiting()` | 這回合還沒行動的角色名字 |

接續存檔只看玩家名字是否相同，不看順序。`Reply` 可以用 `to_dict()`／`Reply.from_dict()` 轉成 JSON，在程序之間傳送。

### `core/prompts.py`：提示詞與介面文字

給 AI 的所有文字都放在 `src/story/prompts/語言/` 的 markdown 檔（目前只有 `zh-TW/`），程式只負責把它們跟遊戲資料組合起來。想調整 AI 的寫法時改這些檔案就好，不用動程式；改了提示詞的地方也能單獨從 git 紀錄看出來。**給改提示詞的人看的說明在 `src/story/prompts/README.md`**：一次呼叫由哪些部分組成、「想改什麼 → 改哪裡」的對照、改完之後要做什麼。

| 檔案 | 內容 |
|---|---|
| `system.md`、`party_system.md` | 單人、多人的寫作與遊戲規則（system prompt），兩邊的規則通常要一起改 |
| `schema.md` | 回傳格式的欄位說明（劇情字數、選項個數……），段落名稱是「格式.欄位」，`models.py` 用 `SCHEMA` 讀 |
| `context.md` | 每回合送給 AI 的故事內容：前提、模式、題材指引、摘要、劇情紀錄、重大事件、遊戲狀態的區塊標題與格式，遊戲狀態 JSON 的欄位名稱與空值、時間的寫法 |
| `turn.md`、`party_turn.md` | 每回合的指示：模式、開場、一般回合、太早結局時重寫、傷重死亡、尾聲，以及時間到（`timeout_action`）、暫時離開（`away_action`）時代替玩家行動的那句話；多人另外有主角名單、焦點與「隊伍」狀態 |
| `progress.md` | 「故事進度」裡的提醒：節奏、結局限制、收尾、隱藏的真相與伏筆 |
| `plan.md` | 開新故事：挑題材、規劃大綱、補大綱（舊存檔）、命名素材、轉折靈感 |
| `premise.md` | 預設的故事開頭、「幫我想」的規則與隨機挑的題材、情境 |
| `memory.md` | 記憶壓縮：給 AI 的規則（system prompt）與各區塊 |
| `vocab.md` | 遊戲詞彙：程度、類別、經過的時間、時段、整體狀態的代號各對應到這個語言的哪個詞 |
| `eval.md` | 評估（`just eval`）的評審標準，不會出現在遊戲裡 |

| 名稱 | 做什麼 |
|---|---|
| `load(檔名)` | 整份檔案就是一段提示詞 |
| `sections(檔名)` | 每段以 `## 名稱` 開頭的檔案，讀成 `{名稱: 內容}` |
| `items(文字)`、`table(文字)` | 一段裡一行一項的清單；「代號: 文字」的對照表 |
| `ui(檔名)` | 介面文字（`src/story/ui/語言/`），格式同 `sections()`；外殼從 `story.core` 匯入的 `ui_text` 就是它 |
| `LANGUAGE` | 語言資料夾，用環境變數 `STORY_LANG` 選擇，預設 `zh-TW` |

格式：開頭與每段上面的 `<!-- -->` 註解是給寫提示詞的人看的說明，不會送給 AI。`{名稱}` 是程式填入的變數，每段可用的變數寫在註解裡。

每一種 AI 呼叫的提示詞都由 `Engine` 的一個方法組出來，不會呼叫 AI：`turn_prompt()`（一般回合與開場：故事內容 `_context()` 加上這回合的指示）、`death_prompt()`、`epilogue_prompt()`、`genre_prompt()`、`arc_prompt()`、`premise_prompt()`、`compaction_prompt()`，多人另外有 `deaths_prompt()`。`story/preview.py`（`just prompts`）用範例情境呼叫這些方法，把完整的提示詞印出來。

`story/evals.py`（`just eval`）用同一組範例情境讓 AI 真的寫一回合，再由程式（字數、選項個數、有沒有結束、傷勢總分）與評審（另一次 AI 呼叫，標準在 `eval.md`）檢查：開場不說破真相、第二幕不會太早寫出結局、第三幕揭露真相、不替玩家做決定、魯莽的行動要付出代價、瀕死還冒險會死、各題材包的文風。`judge` 情境只檢查評審本身：給它故意寫壞的劇情（替玩家說話、寫成結局、說破真相、只暗示不揭露、武俠出現手機），它要判不通過，沒問題的要判通過，其他情境的「通過」才可信。每個情境跑幾次（預設 3 次）統計通過的比例，每次的劇情與評審理由存到 `eval_results/`。免費方案每分鐘只能呼叫 15 次，所以呼叫會排隊，全部跑完約六、七分鐘；付費方案可以用 `--rpm` 調快。

遊戲詞彙（輕／中／重、片刻／一夜、清晨／傍晚……）在程式裡是代號，各語言的詞寫在 `vocab.md`（見上面的 `core/models.py`）。

**介面文字**：給玩家看的文字放在 `src/story/ui/語言/`，跟提示詞分開（提示詞給 AI，這裡給人），格式一樣：每段以 `## 名稱` 開頭，`{名稱}` 是程式填入的變數。

| 檔案 | 誰用 | 內容 |
|---|---|---|
| `core.md` | 核心 | 通知、錯誤、`/help`、`/state`、結局紀錄、回合變化的標籤、選項（繼續、確定……）、純文字版的整段輸出、題材包格式問題 |
| `shells.md` | 共用層、房間、網頁伺服器、純文字版 | 等待提示、輸入框提示、大廳與房間的通知、名字檢查、伺服器啟動時的訊息 |
| `dialogs.md` | 終端機版與網頁版 | 對話框（API key、名字、新的故事、結局）的標題、按鈕與說明 |
| `terminal.md` | 終端機版 | 狀態列、倒數條、指令與說明 |
| `web.md` | 網頁版 | 頁面、選單、說明；伺服器把它和 `dialogs.md` 放進頁面 |

程式用到的每個名稱都要在這些檔案裡，測試會檢查（`test_prompts.py`），翻譯時漏了哪一段會直接指出來。

### `core/genres.py`：題材包

讀取 `genres/` 底下的題材包。結構仿照 Agent Skills：每個題材一個資料夾，`GENRE.md` 開頭是設定欄位（`name`、`description`），後面是寫作指引；可以附 `premises.md`、`names.md`、`twists.md`。寫法見 [docs/genres.md](genres.md)。

| 名稱 | 做什麼 |
|---|---|
| `load_genres()` | 讀取內建（`story/genres/`）與個人（`~/.config/story/genres/`）的題材包，`name` 相同時個人的優先。回傳題材與被略過的題材及原因 |
| `parse_genre()` | 讀一個題材資料夾並檢查格式與長度上限（描述 200 字、指引與附屬檔案各 2,000 字） |
| `Genre` | 一個題材：名稱、描述、指引、開頭靈感、命名素材、轉折靈感 |

engine 用題材的方式：玩家選「自動」時，開局先用 `pick_genre()` 請 AI 從題材目錄挑一個；選定的題材指引整局放在每回合提示詞的前段，規劃大綱時也會附上；`names.md` 給大綱與開場；`twists.md` 給大綱（隨機抽 `TWIST_IDEAS` 則）；`premises.md` 給「幫我想」，核心也直接從裡面隨機抽「留白時使用的前提」（`/random` 重抽；再玩一次時延續上一局的前提）。核心用 `/genre` 指令接收玩家的選擇（`GENRE_AUTO`、`GENRE_NONE` 或題材名稱），題材記在存檔的 `GameState.genre`。

### `core/records.py`：紀錄工具

| 名稱 | 做什麼 |
|---|---|
| `save()`、`load()` | 存讀存檔（終端機版 `save.json`，網頁版由 `players.py` 指定路徑）。存檔是**原子性寫入**：先寫暫存檔再一次換上去，背景壓縮記憶時同時存檔、或寫到一半被關掉，都不會讀到壞掉的存檔 |
| `snapshot()`、`change_groups()` | 比較回合前後，列出「新增／惡化／好轉／痊癒／獲得／失去」（放進 `Reply.changes`）。每個項目帶的是**語氣**（`輕`／`中`／`重`／`good`／`bad`／`plain`／`muted`），不是顏色，由外殼決定怎麼呈現 |
| `ending_record()` | 結局的旅程紀錄（回合數、天數、重大事件） |
| `memory_text()` | 「程式記住的東西」（`/state`）顯示的內容：背包（多人時每個人的）、事實、重大事件、摘要 |
| `DEFAULT_PREMISE` | 預設的故事前提 |

---

## 外殼 `shells/`

### `shells/client.py`：外殼共用層

跟真人玩家互動的流程，所有介面共用。核心只管「送文字進去、拿 `Reply` 出來」，沒有時間感；這一層負責「什麼時候顯示什麼」，介面只負責「長什麼樣子」。以後要做網頁等其他介面時，只要實作 `View`，流程不用再寫一次。

| 名稱 | 做什麼 |
|---|---|
| `View` | 介面要實作的方法：故事區（`start_narration()`、`extend_narration()`、`finish_narration()`、`discard_narration()`：劇情邊收邊顯示；`show_action()`、`show_changes()`、`wait_enter()`…）、選項與提示（`prepare_choices()`、`show_choices()`、`set_hint()`）、狀態列（`set_status()`、`show_lobby()`）、等待與倒數（`set_busy()`、`show_busy()`、`start_timer()`）、通知與對話框（`ask_premise()`、`ask_confirm()`、`ask_ending()`、`ask_name()`、`ask_api_key()`…） |
| `Client.run()` | 開局：取得名字（網頁模式）與 API key，建立 `StoryCore`／`PartyCore`；線上多人時改成連到房間、收房間推來的訊息 |
| `Client.act()`、`command()`、`timeout()` | 介面把玩家的輸入交給這裡：行動（先顯示在故事區）、指令、倒數到了 |
| `send()`、`ask_core()` | 把一句文字送給核心（在背景執行緒，超過 `BUSY_DELAY` 才顯示「故事生成中…」）；等待時每 `DRAFT_POLL` 秒讀一次 `core.draft`；key 無效時請玩家換 key 後重送 |
| `follow_draft()`、`narrate()` | 串流：AI 寫的劇情有新的字就交給介面（線上多人時是房間轉來的 `draft` 訊息）；回覆到了再接著顯示完。這回合失敗時收回寫到一半的劇情 |
| `handle()` | 依 `reply.phase` 決定要跳出哪個對話框、顯示劇情或結局 |
| `show_turn()` | 先放好選項（看不見）→ 劇情 → 變化 → 選項出現 → 更新狀態列 → 開始倒數（線上多人改成告訴房間看完了） |
| `show_ending()` | 按 Enter → 尾聲 → 按 Enter → 結局對話框（一段一段來，先讀完最後的劇情） |
| `refresh_hint()`、`update_waiting()` | 輸入框的提示：線上多人行動完之後提示還在等誰，有人行動時通知 |
| `status_line()` | 把 `Status` 轉成狀態列要顯示的內容（`StatusLine`）：直接列出每個狀態與程度、核心判斷的警告（`Status.warning`）、沒有狀態時是「良好」，只說程度不說顏色。背包不放在狀態列（完整內容用 `/state` 看） |

介面的對話框也會用到的規則（名字的檢查 `check_name()`、key 的存放位置 `KEY_PATH`）也從這裡取用。

### `shells/textual/`：Textual 外殼

用 [Textual](https://textual.textualize.io/) 寫成的終端機介面，實作共用層的 `View`：只負責長相（版面、配色、打字效果、捲動、倒數條、按鍵），把玩家的輸入交給 `Client`。不建立核心、不連房間，也不碰 `GameState`。

**`dialogs.py`：對話框**

| 類別 | 用途 |
|---|---|
| `Dialog` | 所有對話框共用的樣式、「離開」按鈕與 Esc，以及方向鍵規則（←→ 在按鈕間移動、↑↓ 在列之間移動） |
| `ApiKeyDialog` | 輸入 Gemini API key，可以選擇存起來 |
| `PremiseDialog` + `PremiseArea` | 新故事，由上到下：題材選單、題材介紹、故事前提（一開始就填好預設的開頭，玩家改了才用玩家寫的；換題材時沒改過就跟著換，「換一個」一定換）、限時模式勾選，最後是「換一個」（`/random`）、「幫我想」（`/suggest`）、「開始」。透過 app 給的 `ask(指令…)` 把指令送給核心並讀回覆 |
| `ConfirmDialog` | 是／否確認（找到存檔、重新開始） |
| `EndingDialog` | 結局名稱、旅程紀錄、再玩一次（`ConfirmDialog` 加上說明） |
| `InfoDialog` | 顯示 `Reply.info`（記憶、說明） |

**`app.py`：主畫面 `StoryApp`**

| 方法 | 做什麼 |
|---|---|
| `start_narration()`、`type_narration()` | 打字效果追著目前收到的劇情打，AI 還沒寫到的地方就等；按 Enter 加速，再按一次全部顯示 |
| `prepare_choices()`、`show_choices()` | 選項框和倒數條在打字前先佔好位置（看不見），打完才淡入，版面不會突然往上跳 |
| `follow_log()`、`scroll_log()` | 故事區停在最底時，新內容出現就自動捲到最底；玩家往上捲（包括文字還在打的時候）就不跟，捲回最底再恢復。自己行動時一定捲到最底 |
| `set_status()` | 畫共用層給的 `StatusLine`：回合旁邊顯示模式，接著列出每個狀態並依程度上色，警告醒目標出；放不下時換行，不會把一個狀態拆成兩行 |
| `start_timer()`、`tick()` | 限時倒數條（開著對話框時暫停），時間到交給 `client.timeout()` |
| `submit()` | 處理輸入框：等 Enter 繼續、打字中按 Enter 加速、介面的指令（`/help`、`/theme`…），其他交給 `client.act()`／`client.command()` |

**輔助函式**：`describe_changes()`，把 `Reply.changes` 依語氣轉成彩色文字。

**`style.py`：外觀**

| 常數 | 意義 |
|---|---|
| `THEME` | 預設配色主題（`tokyo-night`）。遊戲中用 `/theme`（F2）打開 Textual 內建的主題選擇器；終端機版的選擇存在 `~/.config/story/theme`（`prefs.py`），網頁版不存（設定檔在伺服器上，存了會影響所有玩家） |
| `CHAR_DELAY`、`FAST_FACTOR`、`PAUSE_AFTER` | 打字效果的速度、按 Enter 後的加速倍率、標點停頓 |
| `palette(主題)` | 狀態程度、整體狀態、變化語氣、倒數的顏色，從主題的成功／警告／錯誤色算出來，換主題時跟著變；並轉成 Rich 認得的寫法（ansi 主題的 `ansi_red` 要換成 `color(1)`） |

**`prose.py`：中文換行**

Textual 底層的 Rich 只會在空格處換行，是為英文設計的。AI 常在英文名字前後加空格（「看向 Bob，發現……」），空格後面整段中文會被當成一個長單字推到下一行，造成提早換行；句號也可能落在行首。`wrap()` 改用中文的規則：中文字之間哪裡都能換行、英文單字保持完整、標點不放行首、開頭的引號不留在行尾。`Prose` 是用這個規則顯示的文字區塊，劇情和尾聲都用它，視窗寬度改變時會重新排版。

**`commands.py`：指令與快捷鍵**

`COMMANDS` 定義四個指令（`/state`、`/restart`、`/help`、`/quit`）的快捷鍵與說明；`help_text()` 產生 F1 說明的內容。

新增遊戲指令時，先在 `core/session.py` 的 `send()` 或對應階段的處理函式加上處理；若要有快捷鍵，再到這裡加一行，並在 `app.py` 的 `StoryApp` 加上 `action_<名稱>` 方法。

### `shells/plain.py`：純文字外殼

只用 `input()` 和 `print()` 跟核心對話，不到 30 行。示範核心可以接任何外殼：`uv run story --plain`。



### `shells/web/`：網頁版

瀏覽器打開就能玩，手機和電腦用同一個頁面（`uv run story-web`）。伺服器用 aiohttp，對每個瀏覽器分頁建立一個共用層的 `Client`，介面是 `WebView`：共用層的每個呼叫變成一則 JSON 訊息，經由 WebSocket 送到瀏覽器，瀏覽器只負責畫出來。流程跟終端機版是同一份（`client.py`），所以改流程時不用改網頁。

| 檔案／名稱 | 做什麼 |
|---|---|
| `__init__.py`：`make_app()` | 網頁伺服器：首頁、靜態檔、WebSocket（`/ws`）。首頁是 `index.html` 換上這個語言的文字（`render_page()`：雙大括號包起來的名稱換成 `web.md`、`dialogs.md` 的文字，再把整份字串表放進頁面給 `app.js` 用）。限制同時在線人數（`MAX_SESSIONS`），滿了就顯示提示。線上多人時房間跟著伺服器一起啟動與關閉。頁面與 JS、CSS 都要求瀏覽器每次確認有沒有更新（`Cache-Control: no-cache`），`index.html` 引用時也帶版本號（`?v=`），更新後不會用到快取的舊檔 |
| `__init__.py`：`main()` | `uv run story-web` 的進入點；參數 `--host`、`--port`、`--party` |
| `view.py`：`WebView` | 實作共用層的 `View`。要等玩家的（劇情顯示完、按 Enter、對話框）帶一個 `id`，等瀏覽器回覆；前提對話框開著時，瀏覽器可以送指令給核心（換題材、換一個、幫我想）。訊息格式寫在檔案開頭 |
| `static/index.html`、`style.css` | 頁面與外觀：上方狀態列（第幾回、限時模式、每位角色的狀態）、中間故事、下方選項按鈕與輸入框；手機上對話框從下方滑出，要打字的（名字、API key、故事前提）改從上方出現，鍵盤才不會蓋住。跟著系統的淺色／深色，也可以在選單裡切換（存在這個瀏覽器） |
| `static/app.js` | 把訊息畫出來：打字效果（劇情邊收邊打；點故事區或按 Enter 加速、再按一次全部顯示）、往上捲時不自動跟隨、選項（點擊，或在輸入框用 ↑↓ 選擇）、倒數條（單人開著對話框時暫停）、對話框排隊、通知。手機上不會自動把焦點移到輸入框，不然鍵盤會一直跳出來 |

**手機**：用一般的網頁輸入框打字（中文選字正常）、原生的捲動、字級 16px 以上（手機不會自動放大畫面）。

**單人**（沒加 `--party`）：先問名字（每個名字有自己的存檔 `saves/名字.json`，同一個名字同時只能有一個人在線），再請玩家輸入自己的 API key（只留在這次連線，不存到伺服器）。

**線上多人**（`--party`）：伺服器裡開一個房間（`room.py`），每個分頁的 `Client` 都連到這個房間，大家一起玩同一局，呼叫 AI 用伺服器的 API key。

預設只監聽 `127.0.0.1`。`--host 0.0.0.0` 會開放其他電腦連線，但目前沒有 HTTPS，玩家的 API key 會以明文傳送。

### `shells/room.py`：線上多人的房間

線上多人時，每個瀏覽器分頁的 `Client` 用 `Room.connect()` 連進網頁伺服器裡的房間；房間持有唯一一份 `PartyCore`，呼叫 AI 用伺服器的 API key。房間和所有分頁都在同一個程式裡，訊息直接在記憶體裡傳（為了兩端不共用物件，每則訊息都轉成 JSON 再轉回來）。訊息格式寫在檔案開頭的說明裡。

| 名稱 | 做什麼 |
|---|---|
| `Room` | 大廳（等人加入、房主開始）→ 房主回答對話框 → 遊戲中（每個人用 `send_as()` 各自行動，推進後用 `view()` 送給每個人自己的選項）→ 結局 → 回到大廳 |
| `Connection` | 連線的一端：`send()` 的訊息由另一端的 `receive()` 收到；一端 `close()` 之後，另一端收到 `None` |

- **房主**：第一位加入的人。只有房主能回答「接續存檔、故事前提、確認重新開始」；房主離線時交給下一位在線的玩家，並重送正在等的對話框
- **斷線**：遊戲中斷線的人保留角色，用同一個名字回來會看到目前這回合。在線的人都行動了、只剩離線的人時，替他們送出 `/away`（給 AI 的「暫時離開」文字由核心決定）
- **限時**：倒數由房間負責。新劇情送出後，等每個人回報看完（`ready`）才開始倒數，最多等 `READY_WAIT` 秒；時間到由房間送出 `/timeout`，玩家不能自己送
- 一次只處理一則輸入（`lock`），核心不會被同時呼叫；會呼叫 AI 的輸入在背景執行緒執行，並讓大家看到「故事生成中」

`StoryApp` 收到 `room` 時不建立自己的核心：輸入送到房間，回覆由房間推回來，畫面照常用 `handle()` 顯示。

### `shells/players.py`：網頁版的玩家

| 名稱 | 做什麼 |
|---|---|
| `check_name()` | 檢查名字：不能空白、最多 20 字、只能有文字數字底線連字號（名字會變成檔名，所以擋掉 `../` 這類字元） |
| `Player` | 一個玩家的存檔、紀錄檔路徑（都在 `saves/`）；`acquire()` 佔用名字，`release()` 釋放 |

同一個名字同時只能有一個連線：在線的名字記在 `Player.online`。整個網頁伺服器是同一個程式，所以記在記憶體裡就夠了，伺服器重開時自然清空；分頁關掉或斷線時，連線結束就會釋放。

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
```

測試都不會連到 Gemini，也不會動到你真的存檔或 API key：每個測試都在暫存資料夾裡執行，AI 的回覆由假物件提供。

| 檔案 | 驗證什麼 |
|---|---|
| `conftest.py` | 共用的假物件：`FakeGemini`（假的 Gemini，讓真的 `Engine`／`PartyEngine` 跑規則）、`FakeEngine`／`FakePartyEngine`（假的 engine，讓核心與外殼的測試能精準控制每回合）、`beat()`、`pbeat()`、`upd()`、`cond()` |
| `test_engine.py` | 遊戲規則：狀態增減與好轉限制、身體／精神、整體狀態與死亡、時間與痊癒、限時秒數、背包與事實、大綱與節奏提醒、轉折的伏筆與揭露、提示詞內容、記憶壓縮；串流：從還沒生成完的 JSON 取出劇情、`draft` 跟著劇情變長、太早的結局在劇情出現之前就中斷重寫 |
| `test_records.py` | 存讀檔、舊存檔相容、回合變化的語氣、結局紀錄 |
| `test_core.py` | 核心的文字協定：開新局、幫我想、限時切換、`action_for()`、各種指令、key 失效與重送、重新開始、結局、讀檔接續 |
| `test_prompts.py` | 提示詞檔案：每個檔案都讀得到、說明註解不會送給 AI、各種情境組出來的提示詞沒有留下沒填的變數、尾聲不會帶到一般回合的指示、`just prompts` 的每個情境（單人、多人、套用題材包）都組得出來 |
| `test_evals.py` | `just eval`：用假的 Gemini 跑情境，確認檢查、報告與結果檔正常、評審的校準範例要判不通過，不會寫到存檔或遊戲紀錄；超過呼叫上限時等一下再送 |
| `test_genres.py` | 題材包：內建題材都通過檢查、資料夾解析、格式錯誤會略過並說明原因、個人覆蓋內建、指引在提示詞的位置、AI 先挑題材再規劃大綱、轉折靈感、「幫我想」、`/genre` 指令、隨機開頭與 `/random`、再玩一次延續前提 |
| `test_party.py` | 多人模式：每位角色各自的規則、未知角色與漏掉的角色、單人倒下與全員倒下、焦點輪替、依序收行動、時間到、失敗重試、讀檔；線上多人的 `send_as()`、`view()`、回覆轉 JSON；以及接上真的 engine 的整合測試 |
| `test_room.py` | 線上多人的房間（用 `connect()` 連進去的好幾位玩家）：不照順序行動、名字檢查與人數上限、遊戲中只有隊員能回來、只有房主能回答與重來、斷線重連與替離線的人行動、換房主、大家看完才倒數、結局回到大廳、一個人也能開始、AI 寫劇情時大家都收到串流的劇情 |
| `test_players.py` | 名字檢查、同名鎖定 |
| `test_prose.py` | 中文換行：英文名字不造成提早換行、英文單字不拆開、標點不在行首、引號不留在行尾 |
| `test_client.py` | 外殼共用層：用只記錄呼叫的假介面確認流程，不需要 Textual。開新故事先顯示前提、劇情顯示完才出現選項與狀態再開始倒數、結局一段一段出現、key 無效時換 key 重送、狀態列的內容；串流：回覆到之前就開始顯示劇情、寫到一半失敗時收回 |
| `test_textual.py` | Textual 外殼：模擬按鍵跑完整流程，包括打字與狀態列時機、倒數與暫停、對話框方向鍵、結局、讀檔、窄畫面樣式、狀態在窄畫面換行時不拆開 |
| `test_web.py` | 網頁版：用 WebSocket 扮演瀏覽器。頁面有手機支援、單人玩一回合（存檔依名字分開）、名字不能用時說明原因再問、前提對話框裡的操作、離開、同時在線人數上限、線上多人時每個分頁進到同一個大廳並一起開始 |
| `test_shells.py` | 純文字外殼玩完整局；架構規則：外殼只用核心的公開介面、介面的流程一律交給共用層 |

改了遊戲規則或流程後跑一次 `uv run pytest`，就能確認原本的功能沒有被弄壞。新增功能時，在對應的測試檔加上測試。

---

## 專案設定

| 檔案 | 用途 |
|---|---|
| `pyproject.toml` | 專案設定：相依套件（`google-genai`、`pydantic`、`textual`、`aiohttp`）、開發用套件（`pytest`、`pytest-asyncio`）、執行指令 `story` 與 `story-web`、pytest 設定 |
| `uv.lock` | `uv` 鎖定的套件版本，確保每台電腦裝到一樣的版本 |
| `.python-version` | 使用的 Python 版本（3.14） |
| `.gitignore` | 不進版本控制的檔案：虛擬環境、存檔、紀錄檔等 |
| `README.md` | 專案說明 |
| `docs/files.md` | 本文件 |

## 執行時產生的檔案（不進版本控制）

| 檔案 | 用途 |
|---|---|
| `save.json` | 終端機版的存檔，每回合自動更新。內容就是 `GameState` |
| `saves/名字.json`、`saves/名字.log.jsonl` | 網頁版每個玩家的存檔、每回合紀錄 |
| `saves/party.json`、`saves/party.log.jsonl` | 線上多人的存檔與每回合紀錄 |
| `story_log.jsonl` | 終端機版每回合一行的紀錄：玩家行動、AI 提議的變化、套用前後的狀態、遊戲內時間。用來查「為什麼會這樣」 |
| `~/.config/story/api_key` | 儲存的 API key（在家目錄，不在專案裡） |

這些檔案會產生在執行 `uv run story` 或 `uv run story-web` 時所在的資料夾。
