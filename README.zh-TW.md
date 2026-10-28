# Story

[English](README.md) | 繁體中文

由 Gemini 即時生成劇情的文字遊戲，用手機或電腦的瀏覽器玩，可以一個人玩，也可以和朋友連線一起玩。有兩種玩法：

- **冒險**：AI 寫故事，你的每個選擇都會影響走向
- **海龜湯**：AI 當裁判，大家一起猜一個離奇情境背後的真相

設計原則是 **AI 負責說故事，程式負責記憶與把關**：AI 只「提議」劇情與變化，程式驗證後才寫進遊戲狀態。所以 AI 沒辦法一句話讓你死掉，也不會忘記你背包裡有什麼；魯莽的選擇則會帶來真正的傷勢。

## 特色

- **完整的故事結構**：開場前先規劃隱藏的四幕大綱與一個玩家不知道的真相，前兩幕埋伏筆、第三幕揭露，約 30 回合走到結局，最後附上尾聲
- **身體與精神狀態**：沒有生命值，改用「右臂撕裂傷（重）」「恐懼（中）」這類狀態，會隨遊戲內時間痊癒；身體傷勢累積到致命才會死
- **限時模式**：情勢緊迫時要在倒數內做決定
- **長期記憶**：保留每回合的原文，故事太長時最舊的部分才壓縮成摘要
- **題材包**：武俠、克蘇魯、靈異、怪物與異形、賽博龐克，可以自動挑選或自己指定；也能自己寫（見 [docs/zh-TW/genres.md](docs/zh-TW/genres.md)）
- **一個人或和朋友一起玩**：一隊 1 到 4 人，各自有狀態、背包與選項，大家都行動後才推進。在大廳開房間，好幾個房間可以同時玩
- **海龜湯**：每回合大家同時提問（是非題）或猜湯底，看得到彼此的問答；說中所有關鍵點就解開，同一回合說中就一起獲勝。題目從題庫抽，或請 AI 出

## 開始玩

需要 [uv](https://docs.astral.sh/uv/)（會自動安裝 Python 3.14 與套件）、[Gemini API key](https://aistudio.google.com/apikey)（免費申請），建議裝 [just](https://github.com/casey/just)。

| 指令 | 不用 just 的寫法 | 說明 |
|---|---|---|
| `just serve` | `uv run story --host 0.0.0.0` | 啟動伺服器，預設 8080 埠（`just serve 9000` 換埠） |
| `just start`／`just stop` | | 在背景啟動／關閉伺服器（輸出在 `server.log`） |

第一次執行時會問語言與 API key，存在 `~/.config/story/config.toml`（可以直接編輯）。環境變數優先：`STORY_LANG`（`zh-TW`、`en`）、`GEMINI_API_KEY`。

在瀏覽器打開 `http://這台電腦的IP:8080`（本機是 <http://localhost:8080>），手機和電腦都能用。AI 用架站者的 key，玩家只要輸入名字。

- 名字就是你的角色，瀏覽器會記住。同一組人用同樣的名字開房間，就能接著玩上次的存檔
- 在大廳開房間或加入別人的房間（最多 10 個房間、每間 4 人）。房主選要玩冒險還是海龜湯
- 誰先行動都可以，大家都行動後才推進；別人行動時右上角會短暫提示
- 斷線後用同一個名字回來，會回到原本的房間；從同一個瀏覽器回來會直接取代舊的連線
- 所有房間共用一把 key：免費方案每分鐘最多 15 次 AI 呼叫，忙的時候會排隊

> ⚠ 目前沒有 HTTPS，名字也沒有密碼保護（知道名字就能接著玩那一隊的存檔），只建議在信任的網路使用。

### 操作

直接點選項（或按數字），也可以自己打字寫行動。文字顯示中按 Enter 加速。`/help` 看所有指令，`/state` 看程式記住的東西，也可以用右上角的 ⋯ 選單。每回合自動存檔在 `saves/team-名字.玩法.json`。

## 程式架構

```
src/story/
├── core/        核心：每種玩法共用的流程、回覆格式、呼叫 AI、存檔
├── games/       玩法，彼此平行，都建立在核心上
│   ├── adventure/   冒險：規則、提示詞、題材包
│   └── soup/        海龜湯：裁判、提示詞、題庫
└── shells/      外殼：client.py 是玩家看到的流程，lobby.py 與 room.py 是房間，web/ 是伺服器與網頁
```

由內往外一層一層疊：核心不知道有哪些玩法，玩法彼此不相依、也不知道畫面的存在，外殼只負責顯示和輸入。每種玩法用起來都像呼叫 LLM：送一句文字進去，拿回覆出來。架構說明見 [docs/zh-TW/architecture.md](docs/zh-TW/architecture.md)，待辦見 [ROADMAP.md](ROADMAP.md)（英文）。

## 調整

| 想改什麼 | 在哪裡 |
|---|---|
| AI 的寫法（寫作規則、字數、節奏） | `src/story/games/adventure/prompts/`，先看裡面的 [README](src/story/games/adventure/prompts/README.zh-TW.md) |
| 海龜湯裁判的標準 | `src/story/games/soup/prompts/` |
| 故事長度、傷勢規則 | `src/story/games/adventure/rules.py` |
| 使用的模型 | `src/story/core/ai.py` |
| 題材包 | `src/story/games/adventure/genres/`（個人的放 `~/.config/story/genres/`） |
| 海龜湯題庫 | `src/story/games/soup/puzzles/`，一題一個檔案（個人的放 `~/.config/story/puzzles/`） |
| 配色、打字速度 | `src/story/shells/web/static/` |

文字都是 markdown 檔，放在每一層自己的 `prompts/語言/`（給 AI）與 `ui/語言/`（給玩家）。新增語言就是在每一層複製一份 `en/` 再翻譯。

## 測試與評估

| 指令 | 做什麼 |
|---|---|
| `just test` | 全部測試（約 10 秒），不會連到 Gemini，也不會動到你的存檔 |
| `just lint` | 用 ruff 檢查程式（可能的 bug、import 順序）；`just lint --fix` 自動修正 |
| `just prompts` | 預覽送給 AI 的完整提示詞，不會呼叫 AI |
| `just eval` | 用真的 AI 跑固定情境，檢查節奏、揭露真相、不替玩家做決定、文風、海龜湯的判斷（`just eval soup`）；結果存在 `eval_results/` |

每回合 AI 提議了什麼、程式套用了什麼、每次呼叫花了多久，記在 `saves/team-名字.玩法.log.jsonl`。`just clean-logs` 只刪紀錄，不動存檔。
