<!--
每次寫劇情時，送給 AI 的故事內容（指示以外的部分），依這個順序排：
前提、模式、題材指引、摘要（很少變）→ 劇情紀錄（只往後追加）→ 重大事件、故事進度、遊戲狀態（隨劇情改變）。
不常變的放前面，Gemini 的自動快取（只認開頭完全相同的部分）才能命中得越多。之後接上 turn.md 的指示。
-->

## premise
<!-- 變數：{premise} -->
# 故事前提
{premise}

## mode
<!-- 變數：{mode} 是 turn.md 的 mode_timed 或 mode_normal -->
# 模式
{mode}

## genre_guide
<!-- 選定的題材包，整局固定。變數：{name}、{guide} -->
# 題材：{name}（寫作指引）
{guide}

## summary
<!-- 長期摘要（劇情紀錄太長時，最舊的部分會壓縮到這裡）。變數：{summary} -->
# 先前劇情摘要
{summary}

## history
<!-- 劇情原文。變數：{entries} 是每一回合的 history_entry，空一行隔開 -->
# 劇情紀錄（由舊到新）
{entries}

## history_entry
<!-- 一回合：那時的劇情與玩家看完後做的事。變數：{narration}、{label}（turn_label）、{action} -->
[敘述] {narration}
[{label}] {action}

## history_last
<!-- 最後一回合的行動就是本回合的行動，在指示裡另外列出，這裡只放劇情。變數：{narration} -->
[敘述] {narration}

## turn_label
行動

## key_events
<!-- 變數：{events}（每個事件一行） -->
# 重大事件
{events}

## status
<!-- 遊戲狀態：程式記住的事實，JSON 格式。變數：{json} -->
# 遊戲狀態
{json}

## overall
<!-- 遊戲狀態裡的「整體」：讓 AI 知道離死亡還有多遠。變數：{level}、{score}、{death} -->
{level}（身體傷勢 {score}/{death}，達 {death} 即死亡；輕=1 中=2 重=4）

## status_keys
<!-- 遊戲狀態 JSON 的欄位名稱，一行一個「代號: 給 AI 看的名稱」。代號由程式使用，不能改；只改冒號後面 -->
turn: 回合
time: 時間
body: 身體狀況
mind: 精神狀況
overall: 整體
inventory: 背包
facts: 已確立的事實
characters: 角色
name: 名字
state: 狀態

## status_empty
<!-- 遊戲狀態裡沒有東西時顯示的字，格式同上 -->
time_unknown: 尚未確定
body: 良好
mind: 平穩
inventory: （空）
facts: （無）
dead: 已死亡

## condition
<!-- 遊戲狀態裡的一個狀態。變數：{name}、{severity}（輕、中、重） -->
{name}（{severity}）

## clock
<!-- 遊戲內的時間，只給 AI 看。變數：{day}、{period}（清晨、傍晚……）、{hour}、{minute}（數字，:02d 代表補成兩位數） -->
第 {day} 天 {period}（{hour:02d}:{minute:02d}）
