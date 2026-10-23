<!--
記憶壓縮：劇情紀錄太長時，把最舊的部分併入長期摘要。
-->

## system
<!-- 壓縮記憶時給 AI 的規則（system prompt） -->
你負責壓縮文字冒險遊戲的劇情紀錄。用繁體中文純文字（不要用 Markdown 或 LaTeX），保留人物、地點、承諾、恩怨、伏筆等之後可能用到的資訊，捨棄修辭。

## summary
<!-- 變數：{summary} 是目前的摘要（還沒有摘要時是 summary_none） -->
# 目前的摘要
{summary}

## turns
<!-- 要併入的劇情原文。變數：{entries}（每回合是 context.md 的 history_entry） -->
# 新增的劇情紀錄
{entries}

## old_facts
<!-- 太多時要併入的舊事件與事實。變數：{items}（每項一行） -->
# 要併入的舊事件與事實
{items}

## compact
把以上內容併入摘要，輸出更新後的完整摘要（500 字以內），只輸出摘要本身。

## summary_none
（尚無）
