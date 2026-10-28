# 架構

[English](../en/architecture.md) | 繁體中文

給第一次看這個專案的人：先讀完這一頁，就知道東西在哪裡、新功能該放哪裡。每個函式做什麼，寫在每個檔案開頭與函式的說明裡，這裡不重複。

## 一句話

**AI 負責說故事，程式負責記憶與把關。** AI 每回合只「提議」劇情與變化（傷勢、物品、海龜湯說中幾個關鍵點），程式檢查過才寫進遊戲狀態。

每種玩法用起來都像呼叫 LLM：送一句文字進去，拿一個回覆出來。

```python
core = AdventureCore(api_key, players=["阿明", "小華"], save_path=…)
reply = core.start()                    # 有存檔就問要不要繼續，否則問怎麼開局
reply = core.send_as("阿明", "往上爬")   # 大家都行動了才推進一回合
reply.narration, reply.choices, reply.characters …
```

## 三層，由內往外疊

```
shells/   外殼：網頁、大廳與房間、什麼時候顯示什麼        只用 core 與 games 匯出的名稱
games/    玩法：adventure（冒險）、soup（海龜湯）          彼此平行，只用 core
core/     核心：每種玩法共用的流程、回覆格式、呼叫 AI、存檔  不知道有哪些玩法
```

| 目錄 | 主要的檔案 |
|---|---|
| `core/` | `team.py`：`TeamGame`，每種玩法共用的流程（隊伍、接續存檔、收集每個人的行動、重來、再玩一次）。`reply.py`：`Reply`，每種玩法回給外殼的同一種回覆。`ai.py`：呼叫 Gemini（Gemini 偶爾讓請求排隊 15 秒以上，所以一段時間沒回應就再送一份，用先回來的）。`saves.py`、`prompts.py`（讀文字檔）、`vocab.py`（遊戲詞彙）、`evals.py`（評估的共用部分） |
| `games/adventure/` | `game.py`：`AdventureCore`。`engine.py` 串起 `rules.py`（規則，純函式）、`prompting.py`（組提示詞）與 AI 呼叫。`models.py` 是存檔與 AI 回傳的格式。`genres/` 是題材包。`preview.py`（`just prompts`）、`evals.py`（`just eval` 的情境） |
| `games/soup/` | `game.py`：`SoupCore`。`judge.py` 是 AI 裁判與出題，`puzzles/` 是題庫，`evals.py` 是 `just eval soup` 的情境 |
| `shells/` | `client.py`：共用層，一個瀏覽器分頁一個 `Client`。`view.py`：介面要實作的方法（`View`）。`premise.py`：冒險新故事對話框的規則。`lobby.py`、`room.py`：大廳與房間，房間持有一局的核心。`web/`：網頁伺服器與瀏覽器頁面 |

這些規則有測試把關（`tests/test_shells.py`）：核心 import 玩法、玩法互相 import、外殼用了內部模組，測試都會失敗。

## 新功能放哪裡

| 改的是 | 放在 |
|---|---|
| 每種玩法都用得到的流程 | `core/` |
| 一種玩法的規則或事實 | 那個玩法的資料夾 |
| 真人看到的順序、時機（劇情顯示完才出現選項、大家看完才倒數） | `shells/client.py` |
| 長相 | `shells/web/` |

**新增一種玩法**：在 `games/` 加一個資料夾，寫一個 `TeamGame` 的子類別（`title` 是名稱、`description` 是一句介紹），登記到 `games/__init__.py` 的 `GAMES`。房主開局時的選單會自動列出它，不用改核心、其他玩法與外殼。

## 外殼怎麼知道要顯示什麼

外殼只讀 `Reply` 的欄位，不知道現在玩的是哪一種：

- `phase` 決定流程：`ask_continue`（找到存檔）→ `setup`（開局：有 `choices` 時跳選擇框，沒有時是冒險的故事前提表單）→ `playing` → `ending` → `ended`。`confirm_restart` 是確認重來
- `narration`、`choices`：劇情與選項；有 `inputs` 時（海龜湯的提問、猜湯底），選項是切換輸入的方式
- `characters`：狀態列，要顯示的字與警告都由玩法給
- `ending`：結局、尾聲（海龜湯是湯底）、旅程紀錄

各欄位的說明在 `core/reply.py`。大廳、房間、瀏覽器之間的訊息格式寫在 `lobby.py`、`room.py`、`web/view.py` 的開頭。

## 文字

所有文字都是 markdown，跟著用它的那一層放，每種語言一個資料夾（`zh-TW/`、`en/`），段落一樣：

- 給 AI 的：`prompts/語言/`。冒險的怎麼改，見 `games/adventure/prompts/README.zh-TW.md`
- 給玩家看的：`ui/語言/`

新增語言就是在每一層複製一份 `en/` 再翻譯。

每段以 `## 名稱` 開頭，`{名稱}` 是程式填入的變數，`<!-- -->` 是給寫文字的人看的說明，不會送給 AI。測試會檢查每種語言的段落與變數都一樣、程式用到的文字都存在。

## 想調整什麼

路徑都在 `src/story/` 底下。

| 想改 | 在哪裡 |
|---|---|
| AI 的寫法（寫作規則、字數、節奏） | `games/adventure/prompts/`，先看裡面的 [README](../../src/story/games/adventure/prompts/README.zh-TW.md) |
| 海龜湯裁判的標準 | `games/soup/prompts/` |
| 題材包 | `games/adventure/genres/`（個人的放 `~/.config/story/genres/`），寫法見[怎麼寫題材包](genres.md) |
| 海龜湯題庫 | `games/soup/puzzles/`，一題一個檔案（個人的放 `~/.config/story/puzzles/`） |
| 模型、逾時 | `core/ai.py` 的 `MODEL`、`REQUEST_TIMEOUT` |
| 故事長度、最早第幾回合能結束、每一幕至少幾回合 | `games/adventure/rules.py` 的 `TARGET_TURNS`、`MIN_ENDING_TURN`、`MIN_ACT_TURNS` |
| 傷勢的分數、死亡門檻、痊癒時間 | `games/adventure/rules.py` |
| 一隊最多幾人 | `core/reply.py` 的 `MAX_PLAYERS` |
| 房間數、每分鐘最多呼叫幾次 AI | `shells/lobby.py` 的 `MAX_ROOMS`、`AI_PER_MINUTE` |
| 配色、打字速度 | `shells/web/static/`：`style.css`，以及 `app.js` 的 `CHAR_DELAY` |

## 執行時產生的檔案

不管從哪個資料夾啟動，都放在專案資料夾裡（`settings.DATA_DIR`）。

| 檔案 | 內容 |
|---|---|
| `saves/team-名字.玩法.json` | 每一隊每種玩法的存檔（好幾個人時名字用 `+` 串起來） |
| `saves/team-名字.玩法.log.jsonl` | 每回合一行：玩家行動、AI 提議與程式套用的變化、每次 AI 呼叫的種類（`kind`）、秒數、token 用量，以及有沒有再送一份（`hedged`）。覺得慢或結果奇怪時看這裡 |
| `server.log` | `just start` 的伺服器輸出 |
| `~/.config/story/config.toml` | 語言與 API key |

## 測試與其他指令

| 指令 | 做什麼 |
|---|---|
| `just test` | 全部測試（約 10 秒） |
| `just lint` | 用 ruff 檢查程式（可能的 bug、import 順序）；`just lint --fix` 自動修正 |
| `just prompts` | 預覽送給 AI 的完整提示詞，不會呼叫 AI |
| `just eval` | 用真的 AI 跑固定情境，檢查節奏、揭露真相、不替玩家做決定、文風、海龜湯的判斷（`just eval soup`）；結果存在 `eval_results/` |
| `just clean-logs` | 刪除紀錄（`saves/*.log.jsonl`），不動存檔 |

測試不會連到 Gemini，也不會動到你的存檔：AI 由假物件代替（`tests/conftest.py`），每個測試在暫存資料夾裡執行。真的 AI 寫得好不好用 `just eval` 檢查：情境寫在每種玩法自己的 `evals.py`，`story/evals.py` 把它們收集起來執行。

每次 push 到 GitHub 時，GitHub Actions 會自動跑 `just lint` 與 `just test`（`.github/workflows/test.yml`）。

程式出了意料之外的錯誤時（不是 AI 呼叫失敗），核心會從存檔還原這回合，讓玩家再試一次；房間也有最後一道保護，連線與房間都保留。完整的錯誤原因寫在伺服器的輸出（`just start` 時是 `server.log`）。
