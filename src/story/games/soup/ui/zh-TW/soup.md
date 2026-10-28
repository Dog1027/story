<!--
海龜湯給玩家看的文字：出題、湯面、每回合的結果、狀態列、結局、題庫的格式問題。
格式跟提示詞一樣：每段以「## 名稱」開頭，名稱是程式找段落用的，不能改；{名稱} 是程式填入的變數。
-->

<!-- ---------- 海龜湯 ---------- -->

## title
<!-- 玩法的名稱：房主選玩法的選項（shells 的 start_game）、大廳的房間卡片 -->
海龜湯

## soup_busy
<!-- 等裁判（AI）判斷這一回合時的提示 -->
裁判思考中

## description
<!-- 玩法的介紹：房主選玩法時，名稱下面的一句話 -->
AI 當裁判，大家問是非題、猜出離奇情境背後的真相。

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
題庫裡沒有題目，AI 也沒能出題。請稍後再試，或在 ~/.config/story/puzzles/ 加入題目。

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

## soup_give_up_confirm
<!-- 按「放棄」之後的確認框：問句與兩個按鈕 -->
確定要放棄嗎？同一回合所有人都放棄，就會公布湯底。

## soup_give_up_yes
放棄

## soup_give_up_no
繼續猜

## soup_line_ask
<!-- 一回合的結果裡的一個提問。變數：{name}、{text}、{answer} -->
{name} 問：{text}
→ {answer}

## soup_line_guess
<!-- 一次猜湯底。變數：{name}、{text}、{hit} 說中幾個、{total} 關鍵點總數、{hits}（soup_hits，一個都沒說中時空白） -->
{name} 猜：{text}
→ 說中 {hit}/{total} 個關鍵點{hits}

## soup_hits
<!-- 說中了哪幾個關鍵點（只列說中的，讓玩家知道還差什麼）。變數：{points} 關鍵點，用 list_sep 串起來 -->
：{points}

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
