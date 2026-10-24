<!--
對話框的文字：終端機版（story/shells/textual/dialogs.py）與網頁版（story/shells/web/static/app.js）共用同一份。
格式同 core.md。網頁版由伺服器把這份連同 web.md 一起送給瀏覽器。
-->

<!-- ---------- 按鈕 ---------- -->

## leave
離開

## ok
確定

## cancel
取消

## close
關閉

## enter
進入

## start
開始

## reroll
換一個

## suggest
幫我想

## thinking
<!-- 「幫我想」按下去之後，等 AI 時的按鈕文字 -->
構思中…

## play_again
再玩一次

## send
送出

<!-- ---------- API key ---------- -->

## key_placeholder
貼上 API key

## key_where
<!-- 申請 API key 的說明。變數：{link}（網址，網頁版會變成連結） -->
可以到 {link} 免費申請。

## key_link_text
<!-- 網頁版的連結文字 -->
Google AI Studio

## key_not_stored
<!-- 網頁版：key 不會存到伺服器 -->
key 只用於這次連線，不會存到伺服器上；下次進來要重新輸入。

## key_save
<!-- 終端機版：要不要存起來。變數：{path} -->
儲存到 {path}，下次自動使用

<!-- ---------- 名字（網頁版） ---------- -->

## name_title
你的名字

## name_hint
每個名字有自己的存檔，下次用同一個名字進來就能接著玩。

## name_placeholder
例如：阿明

<!-- ---------- 新的故事 ---------- -->

## premise_title
新的故事

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

## premise_hint
故事前提：可以直接修改，或按「換一個」「幫我想」

## premise_placeholder
例如：你是一名在末日城市送信的郵差……

## timed_option
限時模式：情勢緊迫時，要在時間內做出決定

## suggest_failed
AI 沒有想出開頭

<!-- ---------- 結局 ---------- -->

## ending_title
<!-- 變數：{title} -->
結局：{title}

## story_over
故事結束

<!-- ---------- 通知 ---------- -->

## error_title
出錯了
