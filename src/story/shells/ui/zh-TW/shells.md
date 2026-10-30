<!--
外殼共用的文字：共用層（story/shells/screen/client.py）、網頁版的大廳與房間（story/shells/rooms/）、名字檢查（players.py）、
與網頁伺服器（web/server.py）。格式同 core.md。
-->

<!-- ---------- 第一次啟動時的設定（story/shells/setup.py） ---------- -->

## language_name
<!-- 選語言時顯示的這個語言的名稱 -->
繁體中文

## setup_key
需要 Gemini API key，可以到 https://aistudio.google.com/apikey 免費申請。會存在 ~/.config/story/config.toml。

## setup_key_prompt
Gemini API key（輸入時不會顯示，直接按 Enter 先跳過）：

<!-- ---------- 共用層 ---------- -->

## mode_timed
<!-- 狀態列上跟回合同一排的模式 -->
限時模式

## mode_normal
一般模式

## busy
<!-- 等 AI 時的提示。變數：{label}（玩法給的詞，例如冒險的「故事生成中」，沒有時是 busy_default）、{progress}（busy_progress，或空白） -->
{label}{progress}…

## busy_default
AI 思考中

## busy_progress
<!-- 變數：{progress}，例如「規劃故事大綱」 -->
：{progress}

## wait_epilogue
按 Enter 看尾聲

## wait_ending
按 Enter 查看結局

## story_over
故事結束

## history_trimmed
<!-- 讀檔、重新連線時，之前的劇情最前面：更早的部分已經壓縮成摘要 -->
（更早的劇情已經整理成摘要，用 /state 可以看）

## history_end
<!-- 讀檔、重新連線時，之前的劇情與目前這一段之間 -->
── 以上是之前的劇情 ──

## hint_input
<!-- 輸入框的提示 -->
↑↓ 選擇，或寫下你的行動

## hint_others_acted
<!-- 網頁版：自己還沒行動，已經有人行動了。變數：{names}、{hint}（平常的提示） -->
{names} 已行動。{hint}

## input_echo
<!-- 有輸入方式時（海龜湯），故事區顯示的自己的行動。變數：{label} 方式（提問、猜湯底）、{text} -->
{label}：{text}

## acted
<!-- 網頁版：別人剛行動（右上角短暫出現）。變數：{names} -->
{names} 已行動

## hint_waiting
<!-- 網頁版：自己行動完了。變數：{names} -->
等待 {names} 行動…

## list_sep
、

<!-- ---------- 大廳與房間（rooms/lobby.py、rooms/room.py） ---------- -->

## lobby_title
<!-- 大廳的標題（狀態列上，後面接著在大廳的人） -->
大廳

## room_create
開一個新房間

## room_entry
<!-- 大廳裡一個等人中的房間。變數：{host}、{count}、{max} -->
加入 {host} 的房間（{count}/{max} 人）

## rooms_hint
<!-- 大廳的輸入框提示 -->
加入一個房間，或開新房間（一個人玩也是）

## rooms_full
<!-- 變數：{max} -->
房間已經開滿了（最多 {max} 間），請等其他房間的遊戲結束。

## room_gone
這個房間已經關閉了。

## room_title
<!-- 房間等人畫面的標題。變數：{host} -->
{host} 的房間

## room_hint_host
等朋友加入，或直接開始遊戲

## leave_room
<!-- 等人畫面裡的選項；遊戲中也可以輸入 /leave -->
離開房間

## queued
<!-- 等 AI 時，所有房間共用的呼叫次數用完了，正在排隊 -->
排隊中（大家共用一把 API key）

<!-- ---------- 房間裡的通知 ---------- -->

## room_lost
和遊戲房間的連線中斷了。

## session_replaced
<!-- 同一個瀏覽器從別的分頁、或重新連線進來了：舊的分頁會看到這句 -->
你在別的分頁或裝置進入了遊戲，這裡已經離開。

## room_disconnected
和遊戲房間的連線中斷了，請重新整理頁面。

## lobby_waiting_host
<!-- 變數：{host} -->
等房主 {host} 開始遊戲…

## start_game
<!-- 房主在等人的畫面裡選玩法的選項。變數：{game}（玩法的 title） -->
開始{game}

## room_name_taken
這個名字已經有人在用了，請換一個名字。

## room_members_only
<!-- 變數：{players} -->
遊戲進行中，只有隊伍裡的玩家（{players}）能重新加入。

## room_full
<!-- 變數：{max} -->
房間已滿（最多 {max} 人）。

## room_back
<!-- 變數：{name} -->
{name} 回來了。

## room_left
<!-- 變數：{name} -->
{name} 離線了。

## room_error
<!-- 房間處理訊息時出了意料之外的錯誤（詳細原因寫在 server.log）：房間與連線都保留 -->
伺服器出了點問題，剛才的操作沒有完成，請再試一次。

## host_setting_up
房主正在準備這一局，請稍候。

## wait_host_story
<!-- 變數：{host} -->
等房主 {host} 準備好這一局。

## wait_host_start
<!-- 變數：{host} -->
等房主 {host} 開始遊戲。

## host_only_restart
只有房主能重新開始。

<!-- ---------- 名字 ---------- -->

## name_empty
請輸入名字。

## name_too_long
<!-- 變數：{max} -->
名字最多 {max} 個字。

## name_bad_chars
名字只能包含文字、數字、底線和連字號。

<!-- ---------- 網頁伺服器（架站的人在終端機看到的） ---------- -->

## server_full
<!-- 變數：{max} -->
目前在線人數已滿（{max} 人），請稍後再試。

## server_description
在瀏覽器裡玩 Story

## server_host_help
監聽位址；0.0.0.0 代表開放其他電腦連線（預設只有本機）

## server_no_key
網頁伺服器呼叫 AI 用架站者的 API key：請先在終端機裡執行一次 uv run story 輸入 key，或設定環境變數 GEMINI_API_KEY。

## server_open_warning
⚠ 已開放其他電腦連線。目前沒有 HTTPS，連線內容（名字、劇情）以明文傳送，名字也沒有密碼保護，只建議在信任的網路使用。

## server_started
<!-- 變數：{host}、{port} -->
伺服器已啟動：http://{host}:{port}　按 Ctrl+C 結束。
