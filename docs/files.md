# 檔案說明

這是一個由 LLM（Gemini）即時生成劇情的文字遊戲，有兩種玩法：冒險與海龜湯。設計原則是 **LLM 負責說故事，程式負責記憶與把關**：AI 每回合只「提議」劇情與狀態變化（或判斷），程式驗證後才寫進遊戲狀態。

程式由內往外一層一層疊：**核心**是每種玩法共用的內部核心，**玩法**各自平行地建立在核心上，**外殼**只負責顯示和輸入。每種玩法用起來都像一個 LLM：送文字進去、拿回覆出來（`reply = core.send("往上爬")`），記憶、規則、存檔、遊戲流程都藏在裡面。

```
外殼 story/shells/（只負責顯示和輸入）
  web/       網頁版 ──────┐   "往上爬"            Reply（文字＋附帶資料）
  lobby/room ─────────────┴─────────►   ◄──────────────────
                                   │          ▲
┌──────────── 玩法 story/games/（彼此平行，互不 import）────┴──────────┐
│  adventure/：StoryCore（冒險）   soup/：SoupCore（海龜湯）   ……     │
│    自己的規則、提示詞、AI 回傳格式、存檔格式、給玩家看的文字           │
└───────────────────────────────┬──────────────────────────────────┘
                                ▼ 都是 TeamGame 的子類別
┌──────────── 核心 story/core/（不知道有哪些玩法）───────────────────┐
│  team.py：TeamGame（隊伍、存檔接續、收集行動、再玩一次）              │
│  reply.py：Reply（每種玩法同一種回覆）   ai.py：呼叫 Gemini           │
│  saves.py：存讀檔   prompts.py：讀文字檔   vocab.py：遊戲詞彙          │
└──────────────────────────────────────────────────────────────────┘
```

API key、玩家名字、倒數計時、打字效果屬於外殼。核心只告訴外殼「這回合限時 12 秒」，時間到由網頁版的房間送出 `/timeout`。

---

## 原始碼 `src/story/`

```
src/story/
├── __init__.py          web()：啟動網頁伺服器
├── preview.py           預覽冒險送給 AI 的完整提示詞（just prompts），不會呼叫 AI
├── evals.py             評估 AI 寫得好不好（just eval），會呼叫真的 AI
├── settings.py          設定檔 ~/.config/story/config.toml（語言、API key）
├── setup.py             第一次啟動時在終端機裡問語言與 API key
├── core/                核心：每種玩法共用，不 import 玩法與外殼
│   ├── __init__.py      對外只匯出 Game（TeamGame）、Reply、Status、Texts 等
│   ├── team.py          TeamGame：隊伍遊戲的共用流程（每種玩法都是它的子類別）
│   ├── reply.py         核心回給外殼的資料：Reply、Status、Ending、InputMode、ChangeGroups
│   ├── ai.py            AICaller：呼叫 Gemini、串流、記下用量
│   ├── saves.py         存讀檔（原子性寫入）
│   ├── prompts.py       Texts：讀每一層自己的提示詞與介面文字
│   ├── vocab.py         Vocab：遊戲詞彙的代號與這個語言的詞
│   ├── ratelimit.py     所有房間共用的 AI 呼叫次數限制
│   └── ui/語言/core.md  每種玩法都用到的介面文字（選項、通知、錯誤）
├── games/               玩法：每種一個資料夾，彼此平行，只 import 核心與自己
│   ├── __init__.py      對外匯出 StoryCore、SoupCore 與 GAMES（代號 → 玩法）
│   ├── adventure/       冒險：StoryCore
│   │   ├── game.py      StoryCore：冒險的流程
│   │   ├── engine.py    推進一局：串起規則、提示詞與 AI 呼叫
│   │   ├── rules.py     遊戲規則：傷勢、時間、背包、節奏、記憶的預算
│   │   ├── prompting.py 組提示詞
│   │   ├── models.py    資料結構：GameState（存檔）、StoryBeat 等 AI 回傳格式、遊戲詞彙
│   │   ├── records.py   回合變化、結局紀錄、記憶文字
│   │   ├── genres.py    題材包的讀取與檢查
│   │   ├── text.py      讀冒險自己的文字（TEXT、UI）
│   │   ├── prompts/     給 AI 的提示詞，每種語言一個資料夾；怎麼改見 prompts/README.md
│   │   ├── ui/          給玩家看的文字（adventure.md）
│   │   ├── genres/      題材包，每種語言一個資料夾，每個題材一個資料夾，見 docs/genres.md
│   │   └── samples/     範例故事（just prompts、just eval 用的燈塔故事），每種語言一份
│   └── soup/            海龜湯：SoupCore
│       ├── game.py      SoupCore：海龜湯的流程
│       ├── judge.py     SoupJudge：AI 裁判、出題
│       ├── models.py    資料結構：Puzzle、SoupState（存檔）、AI 回傳格式、遊戲詞彙
│       ├── puzzles.py   讀題庫
│       ├── text.py      讀海龜湯自己的文字
│       ├── prompts/     給 AI 的提示詞（soup.md、schema.md、vocab.md）
│       ├── ui/          給玩家看的文字（soup.md）
│       ├── puzzles/     題庫，每種語言一個資料夾，一題一個檔案
│       └── samples/     評估用的猜測（just eval soup）
└── shells/              外殼：只透過 story.core 與 story.games 的公開介面溝通
    ├── client.py        外殼共用層：跟真人互動的流程
    ├── room_client.py   外殼共用層的網頁版：RoomClient 連進大廳與房間
    ├── text.py          讀外殼的介面文字（ui_text）
    ├── ui/              外殼的介面文字：shells.md、dialogs.md、web.md
    ├── web/             網頁介面：伺服器、WebView、瀏覽器頁面（static/），流程交給 client.py
    ├── lobby.py         網頁版的大廳：名字、房間列表、開房與進出房間
    ├── room.py          網頁版的房間：一個房間一局遊戲
    ├── connection.py    大廳、房間與分頁之間的連線（在記憶體裡傳訊息）
    └── players.py       網頁版的玩家
```

**相依的方向只有一個，由外往內**：介面 → 共用層（`client.py`、`room_client.py`）→ 玩法（`story.games`）→ 核心（`story.core`）。

- 核心不 import 任何玩法與外殼
- 每種玩法只 import 核心與自己，玩法之間互不 import，也不 import 外殼
- 外殼只用 `story.core` 與 `story.games` 匯出的名稱，不直接 import `engine`、`models` 這些內部模組
- 介面（網頁的 `web/view.py`）不自己建立核心、不直接連房間，流程一律交給共用層

這些規則都有測試把關（`test_shells.py`）。

新功能放哪裡：每種玩法都用得到的流程 → 核心；只有一種玩法的規則或事實 → 那個玩法；改變真人看到的順序、時機、流程 → 共用層；改變長相 → 介面（`web/`）。

**文字跟著層走**：每一層的文字放在那一層的資料夾裡，每種語言一個子資料夾（`zh-TW/`、`en/`），檔名與段落都一樣。給 AI 的在 `prompts/語言/`，給玩家看的在 `ui/語言/`。

| 層 | 給 AI | 給玩家 |
|---|---|---|
| 核心 | （沒有） | `core/ui/語言/core.md` |
| 冒險 | `games/adventure/prompts/語言/` | `games/adventure/ui/語言/adventure.md` |
| 海龜湯 | `games/soup/prompts/語言/` | `games/soup/ui/語言/soup.md` |
| 外殼 | （沒有） | `shells/ui/語言/`（`shells.md`、`dialogs.md`、`web.md`） |

**新增一種玩法**：在 `games/` 加一個資料夾，寫一個 `TeamGame` 的子類別（`game.py`）與自己的 `text.py`、`prompts/`、`ui/`，在 `games/__init__.py` 的 `GAMES` 加上代號；網頁版的房間選單（`shells/room.py`）加一個選項。不用改核心與其他玩法。

### `__init__.py`：程式進入點

`web()`：`uv run story-web`（定義在 `pyproject.toml` 的 `[project.scripts]`），網頁版（大廳與房間，見 `shells/web/`）。先做第一次啟動的設定（`setup.py`），再 import 核心與玩法：語言在 import 時就決定了。`--setup-only` 只做第一次的設定就結束，`just start` 在背景啟動前用。

### `settings.py`：玩家的設定檔

`~/.config/story/config.toml`，可以直接編輯：`language`（`zh-TW`、`en`）、`api_key`。程式裡用「區塊.名稱」指一項設定，有區塊的設定寫在 `[區塊]` 底下。環境變數優先：`STORY_LANG` 蓋過 `language`，`GEMINI_API_KEY`（或 `GOOGLE_API_KEY`）蓋過 `api_key`。檔案權限 600（裡面有 API key）。程式改寫時手寫的註解會不見。以前存在 `~/.config/story/api_key` 的 key，讀取時自動搬進來。核心（語言）、玩法（個人題材包與題庫的位置）與外殼都讀它。

| 名稱 | 做什麼 |
|---|---|
| `get(名稱)`、`put(名稱, 值)` | 讀寫一項設定；值是 `None` 時刪掉 |
| `language()`、`api_key()` | 加上環境變數之後的語言與 API key |

### `setup.py`：第一次啟動的設定

在終端機裡依序問設定檔還沒有的：語言（用兩種語言問，選項是 `story/shells/ui/` 底下的語言，名稱是各語言 `shells.md` 的 `language_name`）與 API key（網頁版呼叫 AI 都用架站者的 key，玩家不用輸入）。不是在終端機裡執行時不問。

## 核心 `core/`

每種玩法共用的部分，不知道有哪些玩法。

### `core/team.py`、`core/reply.py`：每種玩法共用的流程與回覆

每一種玩法對外只有一個入口：冒險是 `StoryCore`（`games/adventure/game.py`），海龜湯是 `SoupCore`（`games/soup/game.py`）。輸入一律是文字，回覆和 LLM 的 API 一樣是「文字＋附帶資料」（`Reply`，在 `reply.py`），每種玩法的回覆格式一樣，外殼不用知道現在玩的是哪一種。下面用冒險當例子。

每種玩法共用的流程在 `team.py` 的 `TeamGame`，`StoryCore` 與 `SoupCore` 是它的子類別：玩家名單、找到存檔時問要不要繼續、收集每個人的行動（推進失敗時全部撤回）、確認重新開始、再玩一次、`send()`／`send_as()`／`view()`／`waiting()`、失敗時的回覆、組回覆。子類別只提供不一樣的地方：開新局要問什麼（`setup_phase`：冒險問前提、海龜湯問怎麼出題）、一回合怎麼推進（`_play_round()`）、結局、狀態列、純文字版的樣子、`/help`、存檔的格式（`state_class`），以及時間到、暫時離開時代替玩家的行動（`timeout_action`、`away_action`）。

一局遊戲是一支一到四人的隊伍，冒險裡每人扮演一位角色；一個人玩就是只有一位的隊伍。

**建立與使用**

```python
core = StoryCore(api_key="…", players=["阿明"])  # 網頁版另外傳 save_path、log_path、共用的 client
reply = core.start()                     # 第一個回覆：有存檔就問要不要繼續，否則請你輸入前提
reply = core.send("往上爬")               # 只有一位角色時，send() 就是他的行動
reply = core.send_as("阿明", "往上爬")     # 好幾位角色時，遊戲中的行動要說是誰的
print(reply.text)                        # 只會印文字的外殼，這樣就能完整地玩

core.action_for("2")                     # → "躲起來"：這句輸入代表的行動，讓外殼送出前先顯示
core.set_api_key("…")                    # key 失效時換一個
core.progress                            # send() 執行中目前在做什麼，例如「規劃故事大綱」（可在另一個執行緒讀）
core.draft                               # send() 執行中 AI 正在寫的劇情（串流中目前收到的部分，可在另一個執行緒讀）
core.phase                               # 目前的遊戲階段（唯讀），和最近一次回覆的 reply.phase 相同
```

開新故事要呼叫好幾次 AI（挑題材、規劃大綱、寫開場），比一般回合久，所以 engine 會把目前的階段記在 `stage`，外殼讀 `core.progress` 顯示在「故事生成中」那一行；網頁版由房間把進度推給房間裡的每個人。

劇情是串流產生的：AI 寫的同時，engine 把目前收到的劇情記在 `draft`，外殼讀 `core.draft` 邊收邊顯示，第一個字通常一秒左右就出現。`Reply.narration` 才是最後的完整內容（可能比串流的長，例如有角色傷重倒下時接著補寫的場景）。

不屬於某位玩家的輸入（時間到、對話框的回答、寫尾聲、`/state`）用 `send()`。有好幾位角色時，遊戲中的行動不能用 `send()` 送（不知道是誰的，會丟出 `ValueError`）。每位角色的行動先記下來，所有人都行動後才推進一回合；`/timeout` 時還沒行動的人都算遲疑。這回合失敗時撤回所有人的行動，大家重新選擇。

| 方法 | 做什麼 |
|---|---|
| `send_as(名字, 文字)` | 以某位角色的身分送出輸入，誰先送誰先記；已經行動或倒下的人會收到提示 |
| `players` | 隊伍裡的玩家名字（唯讀） |
| `view(名字, reply=None)` | 某位玩家眼中的畫面：`actor`、`choices` 換成這位角色的。沒給 reply 時是目前這回合的畫面（重新連線用） |
| `waiting()` | 這回合還沒行動的角色名字 |

外殼只能用這幾個方法與屬性，以及讀 `Reply` 的欄位，不直接讀核心的其他屬性（例如 `core.state`），也不 import engine。這樣核心內部怎麼改都不會影響外殼。`test_shells.py` 的 `test_shells_only_use_the_public_core_interface` 會掃描所有外殼的原始碼，確認這條規則沒有被打破。

接續存檔要玩家名字相同（不看順序）。`Reply` 可以用 `to_dict()`／`Reply.from_dict()` 轉成 JSON。

**`Reply` 的欄位**

| 欄位 | 內容 |
|---|---|
| `phase` | 目前階段：`ask_continue`（找到存檔）、`ask_premise`（冒險：等前提）、`ask_puzzle`（海龜湯：從題庫抽或請 AI 出題，`notice` 是問句、`choices` 是兩個選項）、`playing`、`confirm_restart`、`ending`（剛結束，下一句會整理結局；冒險會寫尾聲）、`ended` |
| `timed` | 目前是否為限時模式（遊戲中是這一局的模式，等前提時是開新局會用的模式） |
| `text` | 完整的純文字 |
| `narration` | 這次產生（或讀檔重新顯示）的劇情；沒有新劇情時是空字串 |
| `choices` | 選項 |
| `actor` | 送出輸入的那位玩家（`send_as()`、`view()` 的對象），這回合還沒行動時才有；`choices` 是他的選項 |
| `turn` | 目前是第幾回合（還沒開始故事時是 0） |
| `characters` | 每位角色的狀態列資料（`Status`）：名字 `name`、是否還活著 `alive`、目前的狀態 `conditions`（名稱, 程度），身體在前、精神在後；要不要警告 `warning`（重傷、瀕死，由玩法判斷）與警告顯示的詞 `warning_text`；沒有狀態時顯示的詞 `fine`（「良好」）。只有一位角色時外殼不顯示名字。背包不在這裡：變化在 `changes`，完整內容用 `/state` 看 |
| `changes` | 這回合有變化的角色：(名字, 變化)，變化是新增、惡化、好轉、痊癒、獲得、失去（`ChangeGroups`：每個項目帶的是語氣 `light`／`moderate`／`severe`／`good`／`bad`／`plain`／`muted`，不是顏色，由外殼決定怎麼呈現） |
| `time_limit` | 限時秒數，0 代表不限時 |
| `notice` | 簡短的系統訊息 |
| `resumed` | 這次是讀取存檔、重新顯示上次的劇情 |
| `history`、`history_trimmed` | `resumed` 時之前的劇情：每回合 (劇情, 看完之後的行動，每人一行；只有一位角色時不寫名字)，來自劇情紀錄的原文；更早的部分已經壓縮成摘要時 `history_trimmed` |
| `info` | 要另外顯示的內容（標題, 內容），例如 `/state`、`/help` |
| `premise_default`、`suggestion`、`genres` | 等前提時：留白會用的前提、`/suggest` 想出來的前提、可選的題材 |
| `ending` | 結束時：結局名稱、尾聲（海龜湯是湯底）、旅程紀錄，以及顯示尾聲前的提示（`reveal`，空的時候外殼用「按 Enter 看尾聲」） |
| `inputs` | 輸入的方式（`InputMode`，海龜湯的「提問」「猜湯底」「放棄」）：有的話，`choices` 是切換方式，不是行動本身。選了要打字的方式，接下來打的字用它的 `command`（例如 `/guess`）送出；不用打字的直接送出 |
| `error` | `api_key`：key 無效，外殼換 key（`core.set_api_key()`）後可以重送同一句；`api`：其他錯誤 |

**輸入**

| 輸入 | 何時 | 作用 |
|---|---|---|
| 數字、選項文字 | 有選項時 | 選擇該選項 |
| 任意文字 | 遊戲中 | 自由行動 |
| 任意文字、空白 | 等前提時 | 故事前提；空白使用預設（或剛才 `/suggest` 想出來的） |
| `/suggest`、`/timed on`、`/timed off` | 等前提時 | 讓 AI 想開頭、切換限時模式 |
| `/timeout` | 遊戲中 | 外殼的倒數時間到了 |
| `/away` | 遊戲中 | 這位角色暫時離開、這回合不行動（網頁版的房間替斷線的人送出）。代替的行動跟 `/timeout` 一樣由玩法決定（`away_action`、`timeout_action`；冒險是 `turn.md` 裡給 AI 的那句話） |
| `/restart` | 遊戲中、結束後 | 重新開始（遊戲中會先確認） |
| `/state`、`/help` | 任何時候 | 記憶、說明 |

**內部**：每個階段一個處理函式（`_on_playing()` 等）；LLM 失敗時從存檔還原、留在原階段。

### `core/ai.py`：呼叫 Gemini

| 名稱 | 做什麼 |
|---|---|
| `AICaller` | 每種玩法呼叫 AI 的類別（冒險的 `Engine`、海龜湯的 `SoupJudge`）都繼承它。所有 AI 呼叫都經過它的 `generate()`（一次拿完整結果）與 `stream()`（串流）：記下種類、秒數與 token 用量（送出、命中快取、輸出、思考），由 `write_log()` 寫進紀錄；串流中途丟出 `StopStream`（例如冒險太早寫出結局）而中斷的呼叫標成 `stopped` |
| `partial_string()`、`partial_bool()` | 從還沒生成完的 JSON 取出目前收到的欄位內容 |
| `new_client()` | 建立 Gemini client：每次請求有逾時，逾時或伺服器忙時自動重送 |
| `is_key_error()` | 判斷 Gemini 的錯誤是不是 key 無效 |

### `core/prompts.py`：文字檔

給 AI 的提示詞與給玩家看的介面文字都是 markdown 檔，放在每一層自己的資料夾（見上面「文字跟著層走」）。程式只負責把它們跟遊戲資料組合起來，想調整 AI 的寫法或玩家看到的字時改這些檔案就好，不用動程式；改了文字的地方也能單獨從 git 紀錄看出來。

| 名稱 | 做什麼 |
|---|---|
| `Texts(資料夾)` | 一層自己的文字：`load(檔名)`（整份檔案就是一段提示詞）、`sections(檔名)`（每段以 `## 名稱` 開頭的檔案，讀成 `{名稱: 內容}`）讀 `prompts/語言/`，`ui(檔名)` 讀 `ui/語言/`。外殼從 `story.core` 匯入它 |
| `UI` | 核心共用的介面文字（`core/ui/語言/core.md`）；每種玩法的 `text.py` 把它和自己的合在一起 |
| `sections(檔名, 資料夾)` | 讀任何資料夾裡的這種檔案（題庫、範例故事也是這個格式） |
| `items(文字)`、`table(文字)` | 一段裡一行一項的清單；「代號: 文字」的對照表 |
| `text_length(文字)`、`clip(文字, 上限)` | 文字的長度：中文每個字算一個、英文每個詞算一個，所以字數上限（狀態名稱、題材包、劇情紀錄的預算）在各語言用同一個數字；`clip()` 只留前面幾個 |
| `LANGUAGE` | 語言資料夾，用設定檔的 `language` 或環境變數 `STORY_LANG` 選擇，預設 `zh-TW` |

格式：開頭與每段上面的 `<!-- -->` 註解是給寫文字的人看的說明，不會送給 AI。`{名稱}` 是程式填入的變數，每段可用的變數寫在註解裡。

程式用到的每個介面文字名稱都要在某一層的 `ui/` 裡，每種語言的檔案、段落、變數也要一樣，測試會檢查（`test_prompts.py`），翻譯時漏了哪一段會直接指出來。

### `core/vocab.py`、`core/saves.py`、`core/ratelimit.py`

| 名稱 | 做什麼 |
|---|---|
| `Vocab(段落, 代號)` | 遊戲詞彙：程式與存檔裡用語言無關的代號，給 AI 看、讓 AI 回傳、顯示給玩家時換成這個語言的詞。每種玩法有自己的 `vocab.md`，在 `models.py` 建一個 `Vocab`：`word(類別, 代號)` 換成詞，`code(類別, 詞)` 換回代號，`words(類別)` 產生 AI 回傳格式裡的選項（所以 AI 看到、回傳的都是它的語言）。少了哪個代號的詞，啟動時就報錯 |
| `save()`、`load(路徑, 格式)` | 存讀存檔（網頁版由大廳指定路徑；格式是玩法的 `state_class`）。存檔是**原子性寫入**：先寫暫存檔再一次換上去，背景壓縮記憶時同時存檔、或寫到一半被關掉，都不會讀到壞掉的存檔 |
| `RateLimit` | 所有房間共用的 AI 呼叫次數限制（網頁版） |

## 玩法 `games/`

每種玩法一個資料夾，結構一樣：`game.py` 是對外的入口（`TeamGame` 的子類別），`text.py` 讀自己的文字（`TEXT` 是提示詞，`UI` 是核心共用的文字加上自己的），`models.py` 是 AI 回傳的格式與存檔的格式，加上自己的 `prompts/`、`ui/`。`games/__init__.py` 匯出 `StoryCore`、`SoupCore`、`GENRE_AUTO`、`GENRE_NONE`，以及 `GAMES`（代號 → 玩法，網頁版的大廳用它建立房間的核心；代號也用在存檔的檔名）。

### 冒險 `games/adventure/`

一支隊伍在 AI 寫的故事裡冒險。

#### `models.py`：資料結構

所有資料的形狀都定義在這裡，用 Pydantic 寫成。

**遊戲詞彙**：狀態的程度（`Severity`：`light`／`moderate`／`severe`）、類別（`ConditionKind`：`body`／`mind`）、經過的時間（`TimeSpan`）、時段（`TimeOfDay`）、身體的整體狀態（`Level`：`healthy`……`dead`）在程式與存檔裡都是語言無關的代號。給 AI 看、讓 AI 回傳、顯示給玩家時，換成 `prompts/語言/vocab.md` 裡這個語言的詞（`VOCAB`，見 `core/vocab.py`）：`word(類別, 代號)` 換成詞，`code(類別, 詞)` 換回代號；AI 回傳格式裡的選項用 `words(類別)` 產生，所以 AI 看到、回傳的都是它的語言。

資料分成兩類：

**AI 回傳的格式**（會轉成 JSON schema 交給 Gemini，強制它照格式回答）

| 類別 | 用途 |
|---|---|
| `StoryBeat` | 每回合的回傳：一段包含所有角色的劇情、每位角色的變化（`character_updates`）、經過時間、限時秒數、里程碑是否達成、是否結束 |
| `CharacterUpdate` | 一位角色這回合的變化：名字、選項、狀態增減、物品增減 |
| `ConditionChange` | AI 回報的一個狀態：名稱、類別、程度（這個語言的詞，例如身體／精神、輕／中／重；套用時由程式換成代號） |
| `StoryArc`、`Act` | 開場前規劃的隱藏大綱：目標、隱藏的真相（`twist`，第三幕揭露）與伏筆（`clues`）、四幕與各自的里程碑、可能的結局 |
| `GenrePick` | 玩家選「自動」題材時，AI 挑的題材名稱 |
| `Epilogue` | 故事結束後的尾聲與結局名稱 |

**程式保存的狀態**

| 類別 | 用途 |
|---|---|
| `GameState` | 整個遊戲的狀態，存檔就是把它轉成 JSON。包含隊伍（`characters`）、回合、事實、遊戲內時鐘、大綱進度、分層記憶、目前畫面。`solo` 是隊伍是不是只有一位角色（提示詞與文字用第二人稱、不寫名字） |
| `Character` | 一位角色：名字、狀態、背包、目前的選項、是否還活著 |
| `Condition` | 角色身上的一個狀態，另外記錄在目前程度下經過了多久，用來計算痊癒 |
| `Turn` | 一回合的原文紀錄（劇情 + 每位角色的行動），存在劇情紀錄裡 |

#### `rules.py`：遊戲規則

AI 只「提議」變化，套不套用、套用多少由這裡決定。都是純粹的函式，只讀寫 `GameState` 與 `Character`，不呼叫 AI、不組提示詞，所以規則可以單獨測試。

| 名稱 | 做什麼 |
|---|---|
| `advance_clock()` | 推進回合數與遊戲內時鐘：開場由 AI 挑時段，之後由 AI 選的時間類別換算成分鐘 |
| `apply_condition_changes()` | 狀態規則：依時間自然痊癒、好轉一回合最多一級、身體的中重傷不能直接移除、狀態名稱太長就截短 |
| `apply_items()` | 背包：不能失去沒有的東西 |
| `apply_story_progress()` | 事實、重大事件；這一幕演夠了 `MIN_ACT_TURNS` 回合、AI 說里程碑達成才推進下一幕 |
| `ending_allowed()` | 這回合能不能接受 AI 宣告的結局 |
| `clamp_time_limit()` | 限時秒數：非限時模式一律 0，限時模式夾在範圍裡 |
| `body_score()`、`body_level()`、`warning_level()` | 傷勢分數與整體狀態（只算身體狀態）；整體狀態是 `WARNING_LEVELS`（重傷、瀕死）時要警告玩家 |
| `needs_compaction()`、`to_compact()` | 劇情紀錄、重大事件、事實超過預算時，這次要併入摘要的部分 |

#### `prompting.py`：組提示詞

把 `GameState` 組成送給 AI 的文字，文字本身在 `prompts/語言/`（見下面的提示詞檔案）。不呼叫 AI。

`PromptBuilder` 每一種 AI 呼叫一個方法：`turn()`（開場與一般回合）、`death()`（傷重倒下）、`epilogue()`、`pick_genre()`、`arc()`、`premise()`、`compaction()`。每回合的提示詞是故事內容（`context()`）加上這回合的指示（`instructions()`）。Gemini 的自動快取只認開頭完全相同的部分，所以順序是：前提、模式、題材指引 → 摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度（`progress()`）、遊戲狀態（隨劇情改變）→ 指示。

- `progress()`：隱藏的故事進度與節奏提醒（拖太久、進入最後一幕、超過預定長度）；`twist_lines()`：前兩幕列出真相與伏筆、叫 AI 不要說破，第三幕要揭露，最後一幕當作已知
- 有好幾位角色還活著時，程式輪流指定一位「焦點」角色，讓每個人都有戲份
- 只有一位角色時，系統提示詞要 AI 用第二人稱寫（`system.md`）

`story/preview.py`（`just prompts`）用範例情境呼叫這些方法，把完整的提示詞印出來；`--players 2` 是兩位角色的隊伍。範例故事（燈塔、主角的傷勢、行動、評估用的劇情）在 `games/adventure/samples/語言.md`，每種語言一份、段落相同，所以預覽與評估都能用英文跑。

#### `engine.py`：推進一局遊戲

`Engine` 繼承核心的 `AICaller`，把規則、提示詞、AI 呼叫串起來。由 `game.py` 呼叫，外殼不會直接用到。每回合用 `stream_beat()` 串流取得結構化的 `StoryBeat`：收到劇情的同時更新 `draft`（外殼可以邊收邊顯示）；`game_over` 是 AI 第一個輸出的欄位，太早宣告結局時在劇情出現之前就中斷（`EndingTooEarly`）。

| 方法 | 做什麼 |
|---|---|
| `start()` | 開新遊戲：題材選「自動」時先 `pick_genre()`，再 `plan_arc()` 規劃大綱，最後寫開場。進度記在 `stage` |
| `act(state, {名字: 行動})` | 每位角色都行動後推進一回合 |
| `pick_genre()` | 題材選「自動」：給 AI 題材目錄，依故事前提挑一個；不在目錄裡就不套用 |
| `plan_arc()` | 請 AI 規劃隱藏大綱，附上題材的指引、命名素材與隨機抽的轉折靈感；開場前規劃失敗時，之後的回合依目前的劇情補一份 |
| `suggest_premise()` | 「幫我想」按鈕：程式隨機挑題材與情境，請 AI 想一個故事前提 |
| `write_epilogue()` | 故事結束後請 AI 寫尾聲 |
| `needs_compaction()`、`compact_memory()` | 劇情紀錄超過 `HISTORY_BUDGET` 時，把最舊的回合壓縮進長期摘要；舊事件與事實太多時也一併併入（由核心在背景執行緒呼叫）。30 回合的故事大約只有七、八千字，通常不會觸發 |

一回合的流程（`_advance()`）：`_next_beat()` 請 AI 寫（太早寫出結局就請它重寫一次，還是結局就忽略）→ `_apply()` 對每位角色各自套用 `rules.py` 的規則，傷重的角色倒下，全員倒下就結束（AI 漏掉的角色時間照樣經過、選項留空；只有一位角色時，AI 寫錯名字也算他的）→ `_log_turn()` 把 AI 提議的變化和套用後的結果寫進紀錄 → 有人倒下時 `_write_deaths()` 請 AI 接著寫倒下的場景。

**可以調整的常數**（在各檔案開頭）

| 常數 | 檔案 | 意義 | 目前值 |
|---|---|---|---|
| `MODEL` | `core/ai.py` | 使用的 Gemini 模型 | `gemini-3.5-flash-lite` |
| `REQUEST_TIMEOUT`、`REQUEST_ATTEMPTS` | `core/ai.py` | 一次 AI 請求最多等幾秒；逾時或伺服器忙（429、5xx）時最多送幾次 | 40 秒、3 次 |
| `TARGET_TURNS` | `rules.py` | 故事預定長度，超過只提醒收尾 | 30 回合 |
| `MIN_ACT_TURNS` | `rules.py` | 每一幕至少幾回合；還沒到時 AI 說里程碑達成也不推進 | 5 回合 |
| `MIN_ENDING_TURN` | `rules.py` | 最早第幾回合才接受 AI 宣告的結局（還要進到最後一幕；超過 `TARGET_TURNS` 一律接受）。因傷死亡不受限制 | 20 回合 |
| `HISTORY_BUDGET` | `rules.py` | 劇情紀錄保留原文的字數上限，超過才把最舊的部分壓縮進摘要（一次壓到剩一半） | 20,000 字 |
| `KEEP_EVENTS`、`KEEP_FLAGS` | `rules.py` | 重大事件、事實各保留幾條原文 | 6、12 |
| `SEVERITY_POINTS` | `rules.py` | 輕／中／重（`light`／`moderate`／`severe`）各幾分 | 1／2／4 |
| `DEATH_SCORE`、`DYING_SCORE`、`HEAVY_SCORE` | `rules.py` | 死亡、瀕死、重傷的分數門檻 | 8、6、4 |
| `HEAL_TIME`、`TIME_SPANS` | `rules.py` | 身體與精神狀態各程度的痊癒時間；AI 選的時間類別換算成幾分鐘 | 見程式 |
| `MIN_TIME_LIMIT`、`MAX_TIME_LIMIT` | `rules.py` | 限時模式的秒數範圍 | 8–60 秒 |
| `TWIST_IDEAS` | `prompting.py` | 規劃大綱時從題材包的 `twists.md` 隨機抽幾則轉折靈感 | 3 則 |
| `MAX_PLAYERS` | `core/reply.py` | 一隊最多幾位角色 | 4 |

#### `game.py`：`StoryCore`

冒險的入口，用法見上面的 `core/team.py`。開新局先問前提（`ask_premise`：`/suggest`、`/timed`、`/genre`），每回合所有還活著的角色都行動了才請 `Engine` 寫；回合結束後在背景執行緒壓縮記憶，下一次呼叫 LLM 前會先等它完成；`render_text()` 負責組出純文字，`character_status()` 是狀態列上的一位角色。

#### `genres.py`：題材包

讀取 `games/adventure/genres/語言/` 底下的題材包。結構仿照 Agent Skills：每個題材一個資料夾，`GENRE.md` 開頭是設定欄位（`name`、`description`），後面是寫作指引；可以附 `premises.md`、`names.md`、`twists.md`。寫法見 [docs/genres.md](genres.md)。

| 名稱 | 做什麼 |
|---|---|
| `load_genres()` | 讀取這個語言的內建（`games/adventure/genres/語言/`）與個人（`~/.config/story/genres/語言/`）的題材包，`name` 相同時個人的優先。回傳題材與被略過的題材及原因 |
| `parse_genre()` | 讀一個題材資料夾並檢查格式與長度上限（描述 200 字、指引與附屬檔案各 2,000 字） |
| `Genre` | 一個題材：名稱、描述、指引、開頭靈感、命名素材、轉折靈感 |

engine 用題材的方式：玩家選「自動」時，開局先用 `pick_genre()` 請 AI 從題材目錄挑一個；選定的題材指引整局放在每回合提示詞的前段，規劃大綱時也會附上；`names.md` 給大綱與開場；`twists.md` 給大綱（隨機抽 `TWIST_IDEAS` 則）；`premises.md` 給「幫我想」，核心也直接從裡面隨機抽「留白時使用的前提」（`/random` 重抽；再玩一次時延續上一局的前提）。核心用 `/genre` 指令接收玩家的選擇（`GENRE_AUTO`、`GENRE_NONE` 或題材名稱），題材記在存檔的 `GameState.genre`。

#### `records.py`：紀錄工具

| 名稱 | 做什麼 |
|---|---|
| `snapshot()`、`change_groups()` | 比較回合前後，列出「新增／惡化／好轉／痊癒／獲得／失去」（放進 `Reply.changes`，格式見 `core/reply.py` 的 `ChangeGroups`） |
| `ending_record()` | 結局的旅程紀錄（回合數、天數、重大事件） |
| `memory_text()` | 「程式記住的東西」（`/state`）顯示的內容：背包（有好幾位角色時每個人的）、事實、重大事件、摘要 |
| `DEFAULT_PREMISE` | 預設的故事前提 |

#### 提示詞與介面文字

給 AI 的文字在 `games/adventure/prompts/語言/`，**給改提示詞的人看的說明在 `games/adventure/prompts/README.md`**：一次呼叫由哪些部分組成、「想改什麼 → 改哪裡」的對照、改完之後要做什麼。

| 檔案 | 內容 |
|---|---|
| `system.md` | 寫作與遊戲規則（system prompt） |
| `schema.md` | 回傳格式的欄位說明（劇情字數、選項個數……），段落名稱是「格式.欄位」，`models.py` 用 `SCHEMA` 讀 |
| `context.md` | 每回合送給 AI 的故事內容：前提、模式、題材指引、摘要、劇情紀錄、重大事件、遊戲狀態的區塊標題與格式，遊戲狀態 JSON 的欄位名稱與空值、時間的寫法 |
| `turn.md` | 每回合的指示：模式、主角名單、焦點、開場、一般回合、太早結局時重寫、傷重倒下、尾聲，以及時間到（`timeout_action`）、暫時離開（`away_action`）時代替玩家行動的那句話 |
| `progress.md` | 「故事進度」裡的提醒：節奏、結局限制、收尾、隱藏的真相與伏筆 |
| `plan.md` | 開新故事：挑題材、規劃大綱、補大綱（舊存檔）、命名素材、轉折靈感 |
| `premise.md` | 預設的故事開頭、「幫我想」的規則與隨機挑的題材、情境 |
| `memory.md` | 記憶壓縮：給 AI 的規則（system prompt）與各區塊 |
| `vocab.md` | 遊戲詞彙：程度、類別、經過的時間、時段、整體狀態的代號各對應到這個語言的哪個詞 |
| `eval.md` | 評估（`just eval`）的評審標準，不會出現在遊戲裡 |

給玩家看的文字在 `games/adventure/ui/語言/adventure.md`：通知、`/help`、`/state`、結局紀錄、回合變化的標籤、純文字版的整段輸出、題材包格式問題。

`story/evals.py`（`just eval`）用同一組範例情境讓 AI 真的寫一回合，再由程式（字數、選項個數、有沒有結束、傷勢總分）與評審（另一次 AI 呼叫，標準在 `eval.md`）檢查：開場不說破真相、第二幕不會太早寫出結局、第三幕揭露真相、不替玩家做決定、魯莽的行動要付出代價、瀕死還冒險會死、各題材包的文風；`soup` 情境檢查海龜湯的裁判：真的玩過的猜測（`games/soup/samples/語言.md` 的 `soup_cases`）各自說中幾個關鍵點要在範圍內，不完整的猜測不能給滿分。`judge` 情境只檢查評審本身：給它故意寫壞的劇情（替玩家說話、寫成結局、說破真相、只暗示不揭露、武俠出現手機），它要判不通過，沒問題的要判通過，其他情境的「通過」才可信。每個情境跑幾次（預設 3 次）統計通過的比例，每次的劇情與評審理由存到 `eval_results/`。免費方案每分鐘只能呼叫 15 次，所以呼叫會排隊，全部跑完約六、七分鐘；付費方案可以用 `--rpm` 調快。

### 海龜湯 `games/soup/`

AI 當裁判、大家一起猜的情境猜謎。共用的流程在核心的 `TeamGame`，這裡只有海龜湯自己的部分。

| 檔案 | 內容 |
|---|---|
| `game.py`：`SoupCore` | 開新局問房主從題庫抽一題（`/random` 那種隨機，先抽這個房間沒玩過的）或請 AI 出一題；每回合收集大家的行動（`/ask 問題`、`/guess 推理`、`/give_up`，直接打字就是提問），全部到齊後請裁判一次判斷；說中所有關鍵點的人獲勝（同一回合好幾個人就一起獲勝），同一回合所有人都放棄時公布湯底。回覆用 `inputs` 告訴外殼輸入的方式 |
| `judge.py`：`SoupJudge` | 呼叫 AI：`judge()` 判斷一回合的提問（是、不是、無關、是也不是、不是是非題）與猜測（每個關鍵點分開判斷，並引用猜測裡講到它的原文；引用不到原文的、不存在或重複的編號都不算，漏判任何一個行動就算失敗，這回合重來）；`make_puzzle()` 請 AI 出題（用比較強的 `WRITER_MODEL`），再請它嚴格檢查有沒有矛盾、牽強，沒通過就帶著問題重出一次，還是不行就回傳 `None`，改從題庫抽 |
| `models.py` | 回答用的詞（`VOCAB`，`vocab.md` 的 `soup_answer`）、`Puzzle`（題目）、`SoupState`（存檔：題目、每回合每個人的行動與判斷、獲勝的人）、AI 回傳的 `Judgement`、`Ruling`、`PuzzleDraft`、`PuzzleCheck` |
| `puzzles.py` | 讀題庫：`games/soup/puzzles/語言/`（內建）與 `~/.config/story/puzzles/語言/`（個人，同名時優先）。一題一個 markdown 檔，段落是 `title`、`surface`（湯面）、`truth`（湯底）、`key_points`（2-4 個關鍵點，一行一個）；格式不對的題目會略過並說明原因 |

照「AI 只提議、程式決定」：AI 判斷說中了哪幾個關鍵點，算不算解開由程式依關鍵點的數量決定，不只靠 AI 一句「你答對了」。提示詞在 `prompts/語言/soup.md`（回傳格式的欄位說明在同一個資料夾的 `schema.md`），給玩家看的文字在 `ui/語言/soup.md`，評估用的猜測在 `samples/語言.md`。海龜湯的存檔是 `saves/team-名字.soup.json`，跟冒險的分開。

---

## 外殼 `shells/`

外殼的介面文字在 `shells/ui/語言/`，用 `shells/text.py` 的 `ui_text(檔名)` 讀：

| 檔案 | 誰用 | 內容 |
|---|---|---|
| `shells.md` | 共用層、房間、網頁伺服器 | 等待提示、輸入框提示、大廳與房間的通知、名字檢查、伺服器啟動時的訊息 |
| `dialogs.md` | 共用層與網頁版 | 對話框（名字、新的故事、結局）的標題、按鈕與說明 |
| `web.md` | 網頁版 | 頁面、選單、說明；伺服器把它和 `dialogs.md` 放進頁面 |

### `shells/client.py`：外殼共用層

跟真人玩家互動的流程。核心只管「送文字進去、拿 `Reply` 出來」，沒有時間感；這一層負責「什麼時候顯示什麼」，介面（`View`，網頁版是 `WebView`）只負責「長什麼樣子」。

| 名稱 | 做什麼 |
|---|---|
| `View` | 介面要實作的方法：故事區（`start_narration()`、`extend_narration()`、`finish_narration()`、`discard_narration()`：劇情邊收邊顯示；`show_action()`、`show_changes()`、`show_past_narration()`（讀檔時之前的劇情，不打字）、`wait_enter()`…）、選項與提示（`prepare_choices()`、`show_choices()`、`set_hint()`）、狀態列（`set_status()`）、大廳與房間的等人畫面（`show_lobby()`）、等待與倒數（`set_busy()`、`show_busy()`、`start_timer()`）、通知與對話框（`notify()`、`show_activity()`（網頁版右上角短暫出現的「小華 已行動」）、`ask_premise()`、`ask_confirm()`、`ask_ending()`、`ask_name()`…） |
| `Client` | 兩種玩法共用的流程。子類別決定輸入交給誰：`run()`（開始）、`deliver()`（把一句輸入交給房間）、`echo_for()`（送出前先顯示的行動）、`progress()` 等掛勾 |
| `RoomClient`（`room_client.py`） | 網頁版：連進大廳、問名字、收大廳與房間推來的訊息；輸入送給房間，由房間呼叫核心 |
| `act()`、`command()` | 介面把玩家的輸入交給這裡：行動（先顯示在故事區）、指令。回覆有 `inputs` 時（海龜湯），選項是切換輸入的方式（`View.mark_choice()` 標出來、提示換成那個方式的說明），打的字用目前的方式送出 |
| `send()` | 把一句文字送給房間；回覆、進度與寫到一半的劇情由房間推回來 |
| `follow_draft()`、`narrate()` | 串流：AI 寫的劇情有新的字就交給介面（網頁版是房間轉來的 `draft` 訊息）；回覆到了再接著顯示完。這回合失敗時收回寫到一半的劇情 |
| `handle()` | 依 `reply.phase` 決定要跳出哪個對話框、顯示劇情或結局 |
| `show_turn()` | 先放好選項（看不見）→ 劇情 → 變化 → 選項出現 → 更新狀態列 → 開始倒數（網頁版改成告訴房間看完了） |
| `show_ending()` | 按 Enter → 尾聲 → 按 Enter → 結局對話框（一段一段來，先讀完最後的劇情） |
| `refresh_hint()`、`RoomClient.update_waiting()` | 輸入框的提示：網頁版行動完之後提示還在等誰，還沒行動時提示誰已經行動了（不用通知，才不會蓋住劇情） |
| `RoomClient.show_lobby()` | 大廳或房間的等人畫面：內容（房間、在線的人、座位、選項、輸入框提示）都由大廳與房間決定，介面把選項畫成按鈕，下方的選項區不再列一次（輸入框打編號一樣能選）。剛進來或剛離開房間時先清空畫面 |
| `PremiseForm` | 新故事對話框的規則：題材選單（自動、不指定在最前面）與題材介紹、換題材時玩家沒改過文字框才換上新題材的開頭、「換一個」（`/random`）與「幫我想」（`/suggest`）一定換、被後來的操作取代的結果不用、留白就用預設的開頭。介面只負責畫出來，把操作與文字框的內容交給它，照回傳的文字更新 |
| `status_line()` | 把 `Status` 轉成狀態列要顯示的內容（`StatusLine`）：直接列出每個狀態與程度、核心判斷的警告（`Status.warning`）、沒有狀態時是「良好」，只說程度不說顏色；`named` 是要不要顯示名字（有好幾位角色時）。背包不放在狀態列（完整內容用 `/state` 看） |

介面的對話框也會用到的規則（名字的長度上限 `MAX_NAME_LEN`）也從這裡取用。

### `shells/web/`：網頁版

瀏覽器打開就能玩，手機和電腦用同一個頁面（`uv run story-web`）。伺服器用 aiohttp，對每個瀏覽器分頁建立一個共用層的 `RoomClient`，介面是 `WebView`：共用層的每個呼叫變成一則 JSON 訊息，經由 WebSocket 送到瀏覽器，瀏覽器只負責畫出來。流程在共用層（`client.py`），所以改流程時不用改網頁。

| 檔案／名稱 | 做什麼 |
|---|---|
| `__init__.py`：`make_app()` | 網頁伺服器：首頁、靜態檔、WebSocket（`/ws`）。首頁是 `index.html` 換上這個語言的文字（`render_page()`：雙大括號包起來的名稱換成 `web.md`、`dialogs.md` 的文字，再把整份字串表放進頁面給 `app.js` 用）。限制同時在線人數（`MAX_SESSIONS`），滿了就顯示提示。大廳跟著伺服器一起關閉。頁面與 JS、CSS 都要求瀏覽器每次確認有沒有更新（`Cache-Control: no-cache`），`index.html` 引用時也帶版本號（`?v=`），更新後不會用到快取的舊檔 |
| `__init__.py`：`main()` | `uv run story-web` 的進入點；參數 `--host`、`--port`。用設定檔的 API key 建立大廳（`Lobby.for_server()`） |
| `view.py`：`WebView` | 實作共用層的 `View`。要等玩家的（劇情顯示完、按 Enter、對話框）帶一個 `id`，等瀏覽器回覆；前提對話框開著時，瀏覽器把玩家的操作（換題材、換一個、幫我想）連同文字框的內容送過來，交給共用層的 `PremiseForm`，再把要顯示的開頭送回去。訊息格式寫在檔案開頭 |
| `static/index.html`、`style.css` | 頁面與外觀：上方狀態列（第幾回、限時模式、每位角色的狀態）、中間故事、下方選項按鈕與輸入框；手機上對話框從下方滑出，要打字的（名字、故事前提）改從上方出現，鍵盤才不會蓋住。跟著系統的淺色／深色，也可以在選單裡切換（存在這個瀏覽器） |
| `static/app.js` | 把訊息畫出來：記住上次的名字（下次直接用它進去，不能用時才問；選單的「換名字」忘掉它）與瀏覽器的識別碼、大廳（房間與在線的人，手機上是兩個分頁、寬螢幕左右並排）與房間的座位、打字效果（劇情邊收邊打；點故事區或按 Enter 加速、再按一次全部顯示）、往上捲時不自動跟隨、選項（點擊，或在輸入框用 ↑↓ 選擇）、倒數條（只負責顯示，時間到由房間處理）、對話框排隊、通知。手機上不會自動把焦點移到輸入框，不然鍵盤會一直跳出來 |

**手機**：用一般的網頁輸入框打字（中文選字正常）、原生的捲動、字級 16px 以上（手機不會自動放大畫面）。

**大廳與房間**：每個分頁的 `RoomClient` 都連進同一個大廳（`lobby.py`），輸入名字後開房間或加入別人的房間，每個房間各自玩一局（`room.py`）。呼叫 AI 用架站者的 API key，玩家不用輸入。同時在線的人數上限（`MAX_SESSIONS`）是每個房間都坐滿的人數。

預設只監聽 `127.0.0.1`。`--host 0.0.0.0`（`just serve`、`just start`）會開放其他電腦連線，但目前沒有 HTTPS，連線內容以明文傳送。

### `shells/lobby.py`：網頁版的大廳

整台伺服器一個大廳。玩家用 `Lobby.connect()` 連進來，拿到一端 `Connection`（見 `connection.py`）。訊息格式寫在檔案開頭的說明裡。

| 名稱 | 做什麼 |
|---|---|
| `Lobby` | 名字（整台伺服器不重複）、房間列表、開房與進出房間。在大廳的人看到所有房間（等人中、已滿、遊戲中，只有等人中的能加入）與所有在線的人在哪裡；選了就交給那個房間（`Room.add()`），之後的訊息都轉給房間，直到離開（`/leave` 或在等人的畫面選「離開房間」）回到大廳 |
| `Lobby.for_server(api_key)` | 網頁伺服器用：每個房間的核心都用架站者的 key 與同一個 `RateLimit`（每分鐘 `AI_PER_MINUTE` 次），排隊時畫面顯示「排隊中」 |
| `team_save()` | 一隊的存檔與紀錄：`saves/team-阿明+小華.json`（名字排序，所以順序不同也是同一隊），海龜湯是 `team-阿明+小華.soup.json`；同一組人再開房間時可以接著玩 |
| `MAX_ROOMS` | 同時最多幾個房間（10） |

- **斷線**：遊戲中斷線的人用同一個名字回來時，直接回到原本的房間
- **同一個瀏覽器再連進來**：瀏覽器記著一個識別碼（`token`），同名、同 token 再連進來時（重新整理、手機切到背景時舊的連線還沒斷），新的連線直接取代舊的、坐回原本的位置（不經過離開，房間不會因為沒人而關掉），舊的連線收到 `replaced` 後關閉。token 不同的人用這個名字還是會被拒絕
- **關閉**：房間裡沒有人在線就關閉。存檔還在，同一組人再開房間時，房主會被問要不要接著玩
- 大廳的畫面內容沒變就不重送，選項才不會一直閃

### `shells/room.py`：網頁版的房間

一個房間就是一局遊戲。玩家的連線與名字由大廳管理，大廳把進來的人交給 `add()`、離開或斷線時呼叫 `remove()`、房間裡的訊息交給 `handle()`。房間持有一份 `StoryCore`，一個人玩也是一個房間（只有一位角色的隊伍）。訊息格式寫在檔案開頭的說明裡。

| 名稱 | 做什麼 |
|---|---|
| `Room` | 等人（房主選「開始冒險」或「開始海龜湯」，`make_core(玩家, on_queue, 玩法)` 建立那一種核心）→ 房主回答對話框 → 遊戲中（每個人用 `send_as()` 各自行動，推進後用 `view()` 送給每個人自己的選項）→ 結局 → 回到等人的畫面 |

- **房主**：開房間的人。只有房主能開始遊戲、回答「接續存檔、故事前提、確認重新開始」；房主離開時交給下一位在線的人，並重送正在等的對話框
- **斷線**：遊戲中斷線的人保留角色，用同一個名字回來會看到目前這回合。在線的人都行動了、只剩離線的人時，替他們送出 `/away`（給 AI 的「暫時離開」文字由核心決定）
- **限時**：倒數由房間負責。新劇情送出後，等每個人回報看完（`ready`）才開始倒數，最多等 `READY_WAIT` 秒；時間到由房間送出 `/timeout`，玩家不能自己送
- 一次只處理一則輸入（`lock`），核心不會被同時呼叫；會呼叫 AI 的輸入在背景執行緒執行，並讓大家看到「故事生成中」（排隊時是「排隊中」）

### `shells/connection.py`：連線

房間、大廳和所有分頁都在同一個程式裡，訊息直接在記憶體裡傳。`Connection.pair()` 建立一對連線的兩端：一端 `send()` 的訊息由另一端的 `receive()` 收到（為了兩端不共用物件，每則訊息都轉成 JSON 再轉回來）；一端 `close()` 之後，另一端收到 `None`。

### `shells/players.py`：網頁版的玩家名字

| 名稱 | 做什麼 |
|---|---|
| `check_name()` | 檢查名字：不能空白、最多 20 字、只能有文字數字底線連字號（名字會變成存檔的檔名，所以擋掉 `../` 這類字元） |

同一個名字不能同時有兩個人在線，由大廳（`lobby.py`）負責。

---

## 測試 `tests/`

```bash
uv run pytest                  # 全部（約 30 秒）
```

測試都不會連到 Gemini，也不會動到你真的存檔或 API key：每個測試都在暫存資料夾裡執行，AI 的回覆由假物件提供。

| 檔案 | 驗證什麼 |
|---|---|
| `conftest.py` | 共用的假物件：`FakeGemini`（假的 Gemini，讓真的 `Engine` 跑規則）、`FakeEngine`／`FakeGroupEngine`（假的 engine，讓核心與外殼的測試能精準控制每回合）、`solo()`（只有一位角色 `HERO` 的遊戲狀態）、`beat()`（`HERO` 這回合的回傳）、`pbeat()`、`upd()`（好幾位角色的回傳）、`cond()` |
| `test_engine.py` | 遊戲規則：狀態增減與好轉限制、身體／精神、整體狀態與死亡、時間與痊癒、限時秒數、背包與事實、大綱與節奏提醒、轉折的伏筆與揭露、提示詞內容、記憶壓縮；串流：從還沒生成完的 JSON 取出劇情、`draft` 跟著劇情變長、太早的結局在劇情出現之前就中斷重寫 |
| `test_records.py` | 存讀檔（`core/saves.py`）、冒險的回合變化的語氣、結局紀錄 |
| `test_core.py` | 冒險的文字協定（核心共用的流程也在這裡測）：開新局、幫我想、限時切換、`action_for()`、各種指令、key 失效與重送、重新開始、結局、讀檔接續 |
| `test_prompts.py` | 文字檔：每個檔案都讀得到、每種語言每一層的檔案與段落一樣、程式用到的介面文字都存在、遊戲詞彙沒有重複、說明註解不會送給 AI、各種情境組出來的提示詞沒有留下沒填的變數、尾聲不會帶到一般回合的指示、`just prompts` 的每個情境（一位角色、兩位角色、套用題材包）都組得出來 |
| `test_evals.py` | `just eval`：用假的 Gemini 跑情境，確認檢查、報告與結果檔正常、評審的校準範例要判不通過，不會寫到存檔或遊戲紀錄；超過呼叫上限時等一下再送 |
| `test_genres.py` | 題材包：每種語言的內建題材都通過檢查、資料夾解析、格式錯誤會略過並說明原因、個人覆蓋內建、指引在提示詞的位置、AI 先挑題材再規劃大綱、轉折靈感、「幫我想」、`/genre` 指令、隨機開頭與 `/random`、再玩一次延續前提 |
| `test_characters.py` | 好幾位角色：每位角色各自的規則、未知角色與漏掉的角色、只有一位角色時沒有焦點、AI 寫錯名字也算他的、一人倒下與全員倒下、焦點輪替、行動一定要用 send_as 說是誰的、時間到、失敗重試、讀檔；網頁版房間用的 `send_as()`、`view()`、回覆轉 JSON；以及接上真的 engine 的整合測試 |
| `test_room.py` | 網頁版的大廳與房間（用 `connect()` 連進大廳的好幾位玩家）：兩個房間同時玩、離開房間回大廳與空房間關閉、房間數上限、名字整台伺服器不重複與每間人數上限、不照順序行動、遊戲中只有隊員能回來、只有房主能回答與重來、斷線後直接回到原本的房間、換房主、大家看完才倒數、結局回到等人的畫面、一個人也能開始、AI 寫劇情時大家都收到串流的劇情、AI 呼叫的次數限制、同一個瀏覽器再連進來取代舊的連線、一起玩海龜湯 |
| `test_players.py` | 名字檢查 |
| `test_settings.py` | 設定檔：讀寫與權限、環境變數優先、舊的 api_key 檔搬進來、其他區塊的設定照樣保留、第一次啟動只問還沒設定的、不在終端機裡時不問 |
| `test_client.py` | 外殼共用層：用只記錄呼叫的假介面、真的大廳與房間確認流程。開新故事先顯示前提、劇情顯示完才出現選項與狀態、大家看完才開始倒數、結局一段一段出現、狀態列的內容、新故事對話框的規則（玩家改過的開頭不換掉、被取代的結果不用、留白用預設的）；串流：回覆到之前就開始顯示劇情、寫到一半失敗時收回 |
| `test_web.py` | 網頁版：用 WebSocket 扮演瀏覽器。頁面有手機支援、一個人開房間玩一回合（用架站者的 key，存檔跟著隊伍）、名字不能用時說明原因再問、前提對話框裡的操作、離開、同時在線人數上限、朋友加入同一個房間一起開始 |
| `test_soup.py` | 海龜湯（真的 AI 的判斷用 `just eval soup` 檢查：真的玩過的猜測，不完整的不能給滿分、意思一樣的分數一樣）：一個人問到解開、沒選方式直接打字就是提問、大家同時行動並看到每個人的問答、同一回合一起獲勝、所有人都放棄才公布湯底、裁判失敗時撤回整回合、AI 出題與改從題庫抽、讀檔；真的 `SoupJudge` 配假的 Gemini（關鍵點的編號、漏判、出題的檢查與重出）；每種語言的題庫一樣、格式不對的題目略過、個人的題目優先 |
| `test_shells.py` | 架構規則：一層一層往外疊（核心不 import 玩法與外殼、玩法之間互不 import）、外殼只用核心與玩法的公開介面、介面的流程一律交給共用層 |

改了遊戲規則或流程後跑一次 `uv run pytest`，就能確認原本的功能沒有被弄壞。新增功能時，在對應的測試檔加上測試。

---

## 專案設定

| 檔案 | 用途 |
|---|---|
| `pyproject.toml` | 專案設定：相依套件（`google-genai`、`pydantic`、`aiohttp`）、開發用套件（`pytest`、`pytest-asyncio`）、執行指令 `story-web`、pytest 設定 |
| `uv.lock` | `uv` 鎖定的套件版本，確保每台電腦裝到一樣的版本 |
| `.python-version` | 使用的 Python 版本（3.14） |
| `.gitignore` | 不進版本控制的檔案：虛擬環境、存檔、紀錄檔等 |
| `README.md` | 專案說明 |
| `docs/files.md` | 本文件 |

## 執行時產生的檔案（不進版本控制）

| 檔案 | 用途 |
|---|---|
| `saves/team-名字.json` | 每一隊的存檔，每回合自動更新（好幾個人時名字用 `+` 串起來；海龜湯是 `team-名字.soup.json`）。冒險的內容就是 `GameState` |
| `saves/team-名字.log.jsonl` | 每一隊每回合一行的紀錄：玩家行動、AI 提議的變化、套用前後的狀態、遊戲內時間。用來查「為什麼會這樣」 |
| `server.log` | `just start` 在背景啟動的伺服器的畫面輸出 |
| `~/.config/story/config.toml` | 設定：語言、API key（在家目錄，不在專案裡） |

這些檔案會產生在執行 `uv run story-web` 時所在的資料夾。

紀錄每一行的 `calls` 列出這段期間的每次 AI 呼叫：種類（`kind`：`genre` 挑題材、`arc` 規劃大綱、`turn` 劇情、`rewrite` 太早寫出結局時重寫、`death` 傷重倒下、`epilogue` 尾聲、`suggest` 幫我想、`compaction` 記憶壓縮；海龜湯是 `judge` 裁判、`puzzle` 出題、`puzzle_check` 檢查題目）、花了幾秒（`seconds`），以及 Gemini 回報的 token 用量：送出（`prompt`）、其中命中快取（`cached`）、輸出（`output`）、思考（`thinking`）。覺得等很久時，可以從這裡看時間花在哪裡。紀錄只會一直往後加，一局 30 回合約 50 KB；`just clean-logs` 只刪紀錄，不會動到存檔。
