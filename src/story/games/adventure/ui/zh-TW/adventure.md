<!--
冒險給玩家看的文字：通知、/help、/state、結局紀錄、回合變化的標籤、題材包的格式問題。
格式跟提示詞一樣：每段以「## 名稱」開頭，名稱是程式找段落用的，不能改；{名稱} 是程式填入的變數。
-->

## title
<!-- 玩法的名稱：房主選玩法的選項（shells 的 start_game）、大廳的房間卡片 -->
冒險

## description
<!-- 玩法的介紹：房主選玩法時，名稱下面的一句話 -->
AI 即時寫故事，每個選擇都會影響走向；可以選題材、限時模式。

<!-- ---------- 列舉與標點 ---------- -->

## condition
<!-- 一個狀態加上程度。變數：{name}、{severity} -->
{name}（{severity}）

## condition_change
<!-- 程度改變的狀態。變數：{name}、{old}、{new} -->
{name}（{old}→{new}）

<!-- ---------- 選項（玩家也可以直接打這些字） ---------- -->

## genre_auto
<!-- 題材選單的特別選項：依前提由 AI 挑一個題材包。/genre 後面打這個字也可以 -->
自動

## genre_none
<!-- 題材選單的特別選項：不套用題材包 -->
不套用

<!-- ---------- 新故事對話框的題材選單 ---------- -->

## genre_option
<!-- 題材選單裡的一項。變數：{name} -->
題材：{name}

## genre_auto_option
題材：自動（依故事前提挑選）

## genre_none_option
題材：不套用

## genre_auto_hint
依故事前提自動挑一個題材包，都不適合就不套用。

## genre_none_hint
不套用題材，照一般的方式寫。

<!-- ---------- 通知 ---------- -->

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

<!-- ---------- 錯誤 ---------- -->

## epilogue_failed
<!-- 變數：{error} -->
尾聲生成失敗：{error}

## no_suggestion
AI 沒有想出開頭，請再試一次。

## no_epilogue
尾聲生成失敗。

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
