<!--
網頁版（story/shells/web/static/）自己的文字：頁面、選單、說明。對話框的文字在 dialogs.md。格式同 core.md。
伺服器把這份連同 dialogs.md 放進頁面，app.js 用 T.名稱 取用；index.html 裡的 {{名稱}} 由伺服器換成這裡的文字。
-->

## html_lang
<!-- <html lang="…"> -->
zh-Hant

## title
<!-- 瀏覽器分頁的標題 -->
Story

## menu
<!-- 右上角 ⋯ 按鈕的無障礙名稱 -->
選單

## menu_state
程式記住的東西

## menu_restart
重新開始

## menu_help
說明

## menu_theme
外觀

## theme_system
系統

## theme_light
淺色

## theme_dark
深色

## connecting
連線中…

## disconnected
連線中斷了，請重新整理頁面。

## server_lost
和伺服器的連線中斷了，請重新整理頁面。

## exited
已經離開了。重新整理頁面就能再進來。

## exited_hint
已離開

## premise
<!-- 故事區最上面，故事前提的標籤 -->
故事前提

## lobby
<!-- 狀態列上大廳名單前面的標籤 -->
大廳

## turn
<!-- 狀態列的回合。變數：{turn} -->
第 {turn} 回

## fallen
已倒下

## seconds
<!-- 倒數的秒數。變數：{seconds} -->
{seconds} 秒

## help
選項：點一下，或在輸入框用 ↑↓ 選擇後按 Enter，也可以輸入數字。
自由行動：直接在輸入框寫下你想做的事。
文字顯示中：點故事區或按 Enter 加速，再按一次全部顯示。
文字顯示中也可以往上捲回去看，捲回最底就繼續跟著新文字。

右上角的 ⋯ 選單：
程式記住的東西：背包、已確立的事實、重大事件、劇情摘要
重新開始：放棄目前進度，開一個新故事
外觀：跟隨系統、淺色或深色

限時模式（開新故事時選擇）：情勢緊迫時會出現倒數，時間到就當作你遲疑了。單人時開著對話框倒數會暫停。
