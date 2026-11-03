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

## menu_size
<!-- 選單裡的閱讀設定：故事文字的大小 -->
字級

## size_small
小

## size_medium
中

## size_large
大

## menu_speed
<!-- 選單裡的閱讀設定：故事打字的速度；「立即」是不打字，整段直接出現 -->
打字

## speed_normal
正常

## speed_fast
快

## speed_instant
立即

## connecting
連線中…

## bag
<!-- 頂端的背包按鈕：按了在狀態列下方展開帶著的東西 -->
背包

## server_lost
<!-- 斷線時頁面頂端的橫條 -->
和伺服器的連線中斷了。

## reload
<!-- 斷線橫條上的按鈕：重新載入頁面 -->
重新整理

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

## new_content
<!-- 往上捲回去讀時有新內容：浮在選項上方的按鈕，按了回到最底 -->
↓ 新內容

## your_turn_title
<!-- 分頁不在前面時輪到你（選項出來、要按繼續、要回答對話框）：瀏覽器分頁的標題。變數：{title}（title） -->
（輪到你）{title}

## typing_hint
<!-- 故事打字中，輸入列的提示（電腦） -->
按 Enter 或點一下故事可以加快

## typing_hint_touch
<!-- 故事打字中，輸入列的提示（手機） -->
點一下故事可以加快
