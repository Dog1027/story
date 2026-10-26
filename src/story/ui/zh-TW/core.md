<!--
核心給玩家看的文字：通知、錯誤、/help、/state、結局紀錄、回合變化的標籤，以及純文字版的整段輸出。
格式跟 story/prompts/ 一樣：每段以「## 名稱」開頭，名稱是程式找段落用的，不能改；{名稱} 是程式填入的變數。
-->

<!-- ---------- 列舉與標點 ---------- -->

## list_sep
<!-- 把好幾項串成一句時的分隔（例如狀態、物品、名字） -->
、

## condition
<!-- 一個狀態加上程度。變數：{name}、{severity} -->
{name}（{severity}）

## condition_change
<!-- 程度改變的狀態。變數：{name}、{old}、{new} -->
{name}（{old}→{new}）

<!-- ---------- 選項（玩家也可以直接打這些字） ---------- -->

## choice_continue
繼續

## choice_new_game
開新遊戲

## choice_confirm
確定

## choice_cancel
取消

## choice_play_again
再玩一次

## genre_auto
<!-- 題材選單的特別選項：依前提由 AI 挑一個題材包。/genre 後面打這個字也可以 -->
自動

## genre_none
<!-- 題材選單的特別選項：不套用題材包 -->
不套用

<!-- ---------- 通知 ---------- -->

## found_save
<!-- 變數：{turn}、{premise} -->
找到存檔（第 {turn} 回合）：{premise}

## resumed
<!-- 變數：{premise} -->
讀取存檔：{premise}

## answer_continue
請輸入 1（繼續）或 2（開新遊戲）。

## answer_confirm
請輸入 1（確定）或 2（取消）。

## answer_play_again
輸入 1 再玩一次。

## confirm_restart
確定要放棄目前進度、重新開始嗎？

## rerolled
換了一個開頭。

## mode_switched_timed
已切換為限時模式。

## mode_switched_normal
已切換為一般模式。

## genre_unknown
<!-- 變數：{choice}、{options} -->
沒有「{choice}」這個題材，可以選：{options}

## genre_chosen
<!-- 變數：{choice} -->
題材：{choice}

## unknown_command
<!-- 變數：{command} -->
沒有 {command} 這個指令，輸入 /help 查看說明。

## enter_action
請輸入行動，或輸入數字選擇選項。

## no_story_yet
還沒有開始故事。

## character_fallen
你的角色已經倒下了。

## already_acted
你這回合已經行動了，等其他人行動。

## team_size
<!-- 變數：{min}、{max} -->
隊伍需要 {min} 到 {max} 位不重複的玩家。

<!-- ---------- 錯誤 ---------- -->

## key_invalid
API key 無效或沒有權限。

## failed
<!-- AI 呼叫失敗。變數：{hint}（failed_turn，或空白）、{error} -->
{hint}出錯了：{error}

## failed_turn
這回合沒有推進，請重新選擇行動。

## epilogue_failed
<!-- 變數：{error} -->
尾聲生成失敗：{error}

## timeout
Gemini 太久沒有回應或連不上，請稍後再試。

## no_suggestion
AI 沒有想出開頭，請再試一次。

## no_epilogue
尾聲生成失敗。

## unparsable
<!-- AI 回傳的格式不對。變數：{reason} -->
模型輸出無法解析（{reason}），請換個行動試試。

## no_content
沒有內容

<!-- ---------- 開新故事時的進度（顯示在「故事生成中」後面） ---------- -->

## stage_genre
挑選題材

## stage_arc
規劃故事大綱

## stage_opening
寫開場

<!-- ---------- 回合間的變化 ---------- -->

## change_new
新增

## change_worse
惡化

## change_better
好轉

## change_healed
痊癒

## change_gained
獲得

## change_lost
失去

<!-- ---------- /help 與 /state ---------- -->

## help_title
說明

## help
遊戲中：輸入數字選擇選項，或直接寫下你的行動。

/state      看程式記住了什麼
/restart    重新開始
/help       顯示這份說明

開新故事時：
直接送出空白        使用預設的故事前提
/suggest           讓 AI 幫你想一個開頭
/random            從題材包的開頭靈感裡換一個（不用等 AI）
/timed on|off      開啟或關閉限時模式（情勢緊迫時要在時間內做出決定）
/genre 名稱         選擇題材（題材包），或 /genre 自動、/genre 不套用

限時模式的倒數由外殼負責，時間到時送出 /timeout。

## memory_title
程式記住的東西

## memory
<!-- 變數：{bags}（每個人一行，見 memory_bag、memory_named_bag）、{flags}、{events}（每個事件一行，見 memory_event）、{summary}、{turns} -->
[背包]
{bags}

[已確立的事實]
  {flags}

[重大事件]
{events}

[長期摘要]
  {summary}

[劇情紀錄] {turns} 回合原文

## memory_bag
<!-- 只有一位角色時的背包。變數：{items} -->
  {items}

## memory_named_bag
<!-- 有好幾位角色時，一個人的背包。變數：{name}、{items} -->
  {name}：{items}

## memory_event
<!-- 變數：{event} -->
  - {event}

## memory_empty_bag
空

## memory_no_flags
無

## memory_no_events
  （無）

## memory_no_summary
（尚無）

<!-- ---------- 結局紀錄 ---------- -->

## record
<!-- 變數：{turns}、{days} -->
共 {turns} 回合，歷時 {days} 天。

## record_alive
你走到了故事的盡頭。

## record_dead
你在這趟旅程中倒下了。

## record_all_alive
所有人一起走到了故事的盡頭。

## record_some_fallen
<!-- 變數：{names} -->
{names} 在這趟旅程中倒下了，其他人走到了故事的盡頭。

## record_all_fallen
隊伍全員都在這趟旅程中倒下了。

## record_events
<!-- 變數：{events}（每個事件一行，見 record_event） -->
這趟旅程中：
{events}

## record_event
<!-- 變數：{event} -->
・{event}

<!-- ---------- 純文字版的輸出 ---------- -->

## text_notice
<!-- 變數：{notice} -->
（{notice}）

## text_info
<!-- 變數：{title}、{body} -->
【{title}】
{body}

## text_suggested
想到一個開頭了，直接送出空白就用它開始，也可以自己修改後送出。

## text_new_story
<!-- 變數：{mode}（text_mode_timed 或 text_mode_normal）、{genre}、{premise} -->
新的故事（{mode}，題材：{genre}）。輸入故事前提，或直接送出空白使用：
{premise}
（/random 換一個，/suggest 讓 AI 幫你想，/timed 切換限時模式，/genre 選擇題材）

## text_mode_timed
限時模式

## text_mode_normal
一般模式

## text_genres
<!-- 變數：{genres} -->
可選的題材：{genres}

## text_ending_title
<!-- 變數：{title} -->
─── {title} ───

## text_story_over
故事結束

## text_status
<!-- 變數：{turn}、{timed}（text_status_timed 或空白）、{conditions} -->
回合 {turn}{timed}｜狀態 {conditions}

## text_status_timed
（限時模式）

## text_warning
<!-- 危險時的警告。變數：{level}、{conditions} -->
⚠ {level}　{conditions}

## text_character_line
<!-- 有好幾位角色時的一位角色。變數：{name}、{conditions} -->
{name}｜{conditions}

## text_history_trimmed
（更早的劇情已經整理成摘要，用 /state 可以看）

## text_action
<!-- 純文字版讀檔時，之前的劇情裡的一次行動。變數：{action} -->
› {action}

## text_fallen
已倒下

## text_changes
<!-- 一組變化。變數：{label}、{items} -->
{label} {items}

## text_changes_sep
<!-- 幾組變化之間的分隔 -->
　

## text_named_changes
<!-- 有好幾位角色時，一位角色的變化。變數：{name}、{changes} -->
{name}　{changes}

## text_send_for_epilogue
（故事結束了。送出任何文字查看尾聲。）

## text_actor
<!-- 變數：{name} -->
輪到 {name} 行動：

## text_time_limit
<!-- 變數：{seconds} -->
（限時 {seconds} 秒）

<!-- ---------- 題材包的格式問題（寫題材包的人看的） ---------- -->

## genre_no_file
找不到 GENRE.md

## genre_no_header
GENRE.md 開頭要有 --- 包起來的設定欄位

## genre_no_description
缺少 description（AI 靠它判斷故事適不適合這個題材）

## genre_long_description
<!-- 變數：{max} -->
description 超過 {max} 字

## genre_no_guide
GENRE.md 沒有寫作指引

## genre_long_guide
<!-- 變數：{max}、{length} -->
寫作指引超過 {max} 字（目前 {length} 字）

## genre_long_extra
<!-- 變數：{file}、{max} -->
{file} 超過 {max} 字

<!-- ---------- 海龜湯 ---------- -->

## soup_ask_puzzle
<!-- 開新局時問房主怎麼出題（兩個選項是 soup_from_bank、soup_from_ai） -->
海龜湯：要怎麼出題？

## soup_from_bank
從題庫抽一題

## soup_from_ai
請 AI 出一題

## soup_ai_failed
<!-- AI 出題時出錯，改從題庫抽。變數：{error} -->
AI 出題失敗（{error}），改從題庫抽一題。

## soup_ai_unsound
AI 出的題目檢查後不夠合理，改從題庫抽一題。

## soup_no_puzzles
題庫裡沒有題目，AI 也沒能出題。請稍後再試，或在 story/puzzles/ 加入題目。

## soup_stage_make
AI 出題中

## soup_stage_check
檢查題目

## soup_no_ruling
裁判這回合沒能給出完整的判斷

## soup_surface
<!-- 湯面，開局時與讀檔時顯示。變數：{title}、{surface}、{points} 關鍵點的個數 -->
【{title}】

{surface}

每回合選「提問」問一個是非題，或「猜湯底」說出你的推理。說中全部 {points} 個關鍵點就解開了。

## soup_ask
提問

## soup_ask_hint
寫一個可以用「是／不是」回答的問題

## soup_guess
猜湯底

## soup_guess_hint
寫下你猜的湯底：發生了什麼事、為什麼

## soup_give_up
放棄

## soup_line_ask
<!-- 一回合的結果裡的一個提問。變數：{name}、{text}、{answer} -->
{name} 問：{text}
→ {answer}

## soup_line_guess
<!-- 一次猜湯底。變數：{name}、{text}、{hit} 說中幾個、{total} 關鍵點總數 -->
{name} 猜：{text}
→ 說中 {hit}/{total} 個關鍵點

## soup_line_give_up
<!-- 變數：{name} -->
{name} 選擇放棄

## soup_line_away
<!-- 變數：{name} -->
{name} 這回合沒有行動

## soup_give_up_pending
（同一回合所有人都選放棄，才會公布湯底）

## soup_solved
<!-- 變數：{names} -->
{names} 說中了所有關鍵點！

## soup_all_gave_up
大家都放棄了，公布湯底。

## soup_you
<!-- 一個人玩時，結果裡的名字 -->
你

## soup_won
<!-- 結局的標題。變數：{names} -->
{names} 解開了謎題

## soup_won_together
<!-- 同一回合好幾個人一起解開。變數：{names} -->
{names} 同時解開了謎題

## soup_revealed
沒有人解開：湯底揭曉

## soup_reveal
<!-- 結局：顯示湯底前，請玩家按 Enter -->
按 Enter 看湯底

## soup_record
<!-- 結局的紀錄。變數：{turns}、{questions}、{guesses}、{points} 關鍵點（一行一個） -->
共 {turns} 回合，問了 {questions} 個問題，猜了 {guesses} 次。

關鍵點：
{points}

## soup_status_questions
<!-- 狀態列：問了幾題。變數：{count} -->
問 {count}

## soup_status_best
<!-- 狀態列：猜湯底時最多說中幾個關鍵點。變數：{hit}、{total} -->
說中 {hit}/{total}

## soup_memory
<!-- /state：湯面與之前的問答。變數：{title}、{surface}、{rounds} -->
【{title}】
{surface}

{rounds}

## soup_memory_round
<!-- 變數：{turn}、{text} -->
第 {turn} 回
{text}

## soup_memory_empty
（還沒有人提問）

## soup_help
海龜湯：裁判知道湯底（真相），你們只知道湯面。每回合大家同時行動：
- 提問：問一個是非題，裁判回答「是」「不是」「無關」「是也不是」
- 猜湯底：說出你的推理，裁判會告訴大家說中了幾個關鍵點
- 放棄：同一回合所有人都放棄時公布湯底
說中所有關鍵點就解開了；同一回合好幾個人說中就一起獲勝。

## puzzle_missing
<!-- 題庫的題目格式不對。變數：{sections} -->
缺少段落：{sections}

## puzzle_points
<!-- 變數：{min}、{max} -->
關鍵點要有 {min}-{max} 個
