<!--
「故事進度」區塊：隱藏的大綱與提醒，只給 AI 看。程式依照大綱與回合數，決定這回合要附上哪幾句。
-->

## header
<!-- 變數：{lines} 是下面各項，每項一行 -->
# 故事進度（玩家看不到）
{lines}

## goal
<!-- 變數：{goal} -->
目標：{goal}

## act
<!-- 大綱的一幕。變數：{number}、{name}、{milestone}、{mark}（act_current、act_done 或空白） -->
第{number}幕「{name}」：{milestone} {mark}

## act_current
→ 目前

## act_done
✓ 已完成

## endings
<!-- 變數：{endings}（用 endings_sep 隔開） -->
可能的結局：{endings}

## endings_sep
<!-- 幾種可能的結局之間的分隔 -->
；

## act_just_started
<!-- 這一幕還沒演滿最少回合數。變數：{left} 是還要鋪陳幾回合 -->
節奏提醒：這一幕剛開始，至少還要鋪陳 {left} 回合；這回合不要達成里程碑，milestone_reached 設為 false。

## ending_locked
<!-- 還不能結束故事。變數：{min_ending_turn} -->
結局限制：故事最早要到第 {min_ending_turn} 回合、進入最後一幕之後才能結束；在那之前 game_over 一律設為 false，也不要寫出結局。

## overdue
<!-- 超過預定長度。變數：{target_turns} -->
收尾提醒：故事已經超過預定的 {target_turns} 回合。這一兩回合內就要寫出高潮與結局，達成時設 game_over 為 true。不要再開啟新的支線或危機。

## final_act
收尾提醒：已進入最後一幕。朝高潮與結局推進，不要再開啟新的支線；最後的里程碑達成時寫出結局並設 game_over 為 true。

## act_too_long
節奏提醒：這一幕已經拖太久了。本回合就要出現轉折，明顯朝目前的里程碑推進。

## twist_hidden
<!-- 第一、二幕：隱藏的真相。變數：{twist} -->
隱藏的真相（第三幕才揭露，在那之前不要說破，也不要暗示得太明顯）：{twist}

## twist_clues
<!-- 第一、二幕：要埋的伏筆。變數：{clues}（每個伏筆一行） -->
伏筆（前兩幕找合適的時機自然帶到，一次一個，不要解釋它的意義）：
{clues}

## twist_reveal
<!-- 第三幕：要揭露真相。變數：{twist} -->
本幕要揭露隱藏的真相：{twist}

## twist_reveal_clues
<!-- 第三幕：接在 twist_reveal 下一行。變數：{clues} -->
揭露時呼應之前埋下的伏筆：
{clues}

## twist_known
<!-- 第四幕：真相已經揭露。變數：{twist} -->
已揭露的真相：{twist}
