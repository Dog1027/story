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
<!-- 送出 /state：背包、已確立的事實、重大事件、劇情摘要（海龜湯是湯面與問答） -->
目前資訊

## menu_restart
重新開始

## menu_rename
<!-- 忘掉這個瀏覽器記住的名字，重新進入（會離開目前的房間）；按下去先問 rename_question -->
換名字

## rename_question
確定要換名字嗎？

## rename_warning
<!-- 換名字前的確認：存檔跟著隊伍的名字，換名字等於重新開始 -->
換名字會離開目前的房間，這一局等於重新開始：存檔跟著現在的名字，換成新名字就接不回來（之後用回現在的名字才能接著玩）。

## rename_yes
換名字

## rename_no
取消

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

## lobby_counts
<!-- 大廳標題旁邊。變數：{rooms}、{max}（房間數上限）、{people}（在線人數） -->
房間 {rooms}/{max}　·　{people} 人在線

## lobby_rooms
房間

## lobby_people
在線的人

## lobby_rooms_tab
<!-- 手機上大廳的分頁。變數：{count} -->
房間（{count}）

## lobby_people_tab
<!-- 變數：{count} -->
在線（{count}）

## lobby_no_rooms
還沒有房間。開一個新房間：一個人玩，或等朋友加入。

## room_state_open
<!-- 房間卡片的狀態。變數：{count}、{max} -->
等人中 {count}/{max}

## room_state_full
<!-- 變數：{count}、{max} -->
已滿 {count}/{max}

## room_state_playing
<!-- 變數：{count}、{max}、{game}（玩法的 title） -->
遊戲中・{game}

## join
加入

## host_tag
房主

## you_tag
<!-- 接在自己的名字後面 -->
你

## where_lobby
在大廳

## where_room
<!-- 變數：{host} -->
在 {host} 的房間

## where_playing
<!-- 變數：{host} -->
在 {host} 的房間遊戲中

## room_seats
<!-- 房間標題旁邊。變數：{count}、{max} -->
{count}/{max} 人

## pick_game
<!-- 等人畫面裡，房主選玩法的選單標題 -->
選擇玩法

## seat_empty
空位

## exited_hint
已離開

## premise
<!-- 故事區最上面，故事前提的標籤 -->
故事前提

## turn
<!-- 狀態列的回合。變數：{turn} -->
第 {turn} 回

## fallen
已倒下

## seconds
<!-- 倒數的秒數。變數：{seconds} -->
{seconds} 秒
