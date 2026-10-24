# 提示詞

這裡是送給 AI 的所有文字。想調整 AI 怎麼寫故事，改這裡的檔案就好，不用動程式。

```
prompts/
└── zh-TW/          繁體中文（目前唯一的語言）
    ├── system.md        單人的寫作與遊戲規則
    ├── party_system.md  多人的寫作與遊戲規則
    ├── schema.md        回傳格式的欄位說明（劇情字數、選項個數……）
    ├── context.md       每回合的故事內容：前提、劇情紀錄、遊戲狀態的格式
    ├── turn.md          每回合的指示（單人）：開場、一般回合、尾聲、傷重死亡……
    ├── party_turn.md    每回合的指示（多人另外的部分）
    ├── progress.md      故事進度裡的提醒：節奏、結局時機、隱藏的真相與伏筆
    ├── plan.md          開新故事：挑題材、規劃大綱
    ├── premise.md       預設的開頭、「幫我想」
    ├── memory.md        記憶壓縮
    ├── vocab.md         遊戲詞彙：輕／中／重、片刻／一夜……
    └── eval.md          評估（just eval）的評審標準，不會出現在遊戲裡
```

題材包（武俠、克蘇魯……各自的寫作指引）不在這裡，在 `story/genres/`，寫法見 `docs/genres.md`。給玩家看的介面文字（按鈕、通知、說明）也不在這裡，在 `story/ui/語言/`。

## 一次呼叫由哪些部分組成

寫一回合劇情時，AI 收到三樣東西：

1. **寫作與遊戲規則**（`system.md`；多人是 `party_system.md`）：整局都一樣。
2. **回傳格式**：要填哪些欄位、每個欄位填什麼（`schema.md`）。
3. **這回合的內容**，由上到下：
   - 故事內容（`context.md`）：故事前提 → 模式 → 題材指引 → 長期摘要 → 劇情紀錄 → 重大事件 → 故事進度（`progress.md`）→ 遊戲狀態
   - 這回合的指示（`turn.md`、`party_turn.md`）：開場、一般回合、尾聲或傷重死亡

不常變的放前面、會變的放後面，是為了讓 Gemini 的自動快取命中，比較快也比較便宜。改的時候盡量不要打亂這個順序。

**想看拼起來的樣子**：執行 `just prompts`，會用範例情境印出每一種呼叫的完整提示詞，不會呼叫 AI。

```bash
just prompts                     # 全部情境
just prompts turn reveal         # 只看「一般回合」和「第三幕揭露真相」
just prompts --party death       # 多人模式的「傷重倒下」
just prompts --genre 克蘇魯 arc   # 套用題材包，看規劃大綱
```

## 想改什麼，改哪裡

| 想改的 | 檔案 | 段落 |
|---|---|---|
| 文風、敘事人稱、選項要多不一樣 | `system.md`、`party_system.md` | 規則 |
| 傷勢給得嚴不嚴格、魯莽的選擇要多危險 | `system.md`、`party_system.md` | 「選擇要有真實的代價」那幾條 |
| 劇情的字數、選項個數、狀態名稱的長度 | `schema.md` | `StoryBeat.narration`、`StoryBeat.choices`、`ConditionChange.name`（多人在 `PartyBeat`、`CharacterUpdate`） |
| 節奏：一幕剛開始、拖太久、該收尾了 | `progress.md` | `act_just_started`、`act_too_long`、`final_act`、`overdue` |
| 太早寫出結局時怎麼要求重寫 | `turn.md` | `early_ending_retry` |
| 隱藏的真相、伏筆怎麼埋、什麼時候揭露 | `progress.md`、`plan.md` | `twist_*`、`arc` |
| 大綱怎麼規劃（四幕、結局方向） | `plan.md`、`schema.md` | `arc`、`StoryArc.*` |
| 開場、一般回合的指示 | `turn.md`、`party_turn.md` | `opening`、`action` |
| 尾聲 | `turn.md`、`schema.md` | `epilogue`、`epilogue_look_back`、`Epilogue.*` |
| 傷重死亡的場景 | `turn.md`、`party_turn.md` | `death` |
| 時間到、暫時離開時代替玩家的那句話 | `turn.md`、`party_turn.md` | `timeout_action`、`away_action` |
| 「幫我想」的題材、情境、規則 | `premise.md` | `genres`、`settings`、`rules` |
| 預設的故事開頭 | `premise.md` | `default` |
| 記憶壓縮要保留什麼 | `memory.md` | `system` |
| 遊戲狀態裡的欄位名稱、時間的寫法 | `context.md` | `status_keys`、`status_empty`、`clock` |
| 程度、時段這類遊戲詞彙用哪個字（AI 回傳與玩家看到的都是這些字） | `vocab.md` | `severity`、`kind`、`time_span`、`time_of_day`、`level`（只改冒號後面，改了 `schema.md`、`system.md` 裡提到的字也要一起改） |

單人和多人的規則是分開的兩份，改了一份通常另一份也要跟著改。

## 檔案格式

- 開頭和每段上面的 `<!-- -->` 是給你看的說明（這段什麼時候用、有哪些變數），**不會送給 AI**。
- 放好幾段的檔案，每段以 `## 名稱` 開頭。**名稱是程式找段落用的，不能改**；改的是下面的內容。
- `{名稱}` 是變數，程式會填入，例如 `{left}` 是還要鋪陳幾回合、`{twist}` 是隱藏的真相。每段可以用的變數寫在說明裡。內容裡不能出現其他的大括號。
- `status_keys` 這類「代號: 文字」的對照表，只改冒號後面。

## 改完之後

1. `just prompts` 看拼起來的樣子。
2. `just test` 確認沒有改壞，例如變數名稱打錯、段落名稱被改掉，測試會指出是哪裡。
3. 提示詞是程式啟動時讀的：網頁版執行 `just start` 重啟伺服器，終端機版重新執行。
4. `just eval` 讓 AI 用固定的情境真的寫幾回合，檢查有沒有太早寫出結局、第三幕有沒有揭露真相、有沒有替玩家做決定、魯莽的選擇有沒有代價、文風符不符合題材。會呼叫真的 AI，免費方案跑完約六、七分鐘；只想看其中幾項時用 `just eval reveal agency`。結果存在 `eval_results/`，可以跟改之前的比較。
5. 實際玩一局看 AI 的表現。

## 新增語言

每種語言一個資料夾，裡面要有**一整套同名的檔案、同名的段落**，用環境變數選擇：

```bash
STORY_LANG=en just start
```

目前只有 `zh-TW`。要完整支援另一種語言，除了這裡的提示詞，還有幾件事要一起做，見 `docs/roadmap.md` 的「多語言」。
