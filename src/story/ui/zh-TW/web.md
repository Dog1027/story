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

## menu_rename
<!-- 忘掉這個瀏覽器記住的名字，重新進入（會離開目前的房間） -->
換名字

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
<!-- 變數：{count}、{max}、{game}（玩法：game_story、game_soup） -->
遊戲中・{game}

## game_story
<!-- 玩法的名稱（房間卡片上） -->
冒險

## game_soup
海龜湯

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

## help
選項：點一下，或在輸入框用 ↑↓ 選擇後按 Enter，也可以輸入數字。
自由行動：直接在輸入框寫下你想做的事。
文字顯示中：點故事區或按 Enter 加速，再按一次全部顯示。
文字顯示中也可以往上捲回去看，捲回最底就繼續跟著新文字。

右上角的 ⋯ 選單：
程式記住的東西：背包、已確立的事實、重大事件、劇情摘要
重新開始：放棄目前進度，開一個新故事
外觀：跟隨系統、淺色或深色

限時模式（開新故事時選擇）：情勢緊迫時會出現倒數，時間到就當作你遲疑了。房間裡的人共用一個倒數，大家都看完劇情才開始。
