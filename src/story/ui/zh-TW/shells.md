<!--
外殼共用的文字：共用層（story/shells/client.py）、線上多人的房間（room.py）、名字檢查（players.py）、
網頁伺服器（web/__init__.py）與純文字版（plain.py）。格式同 core.md。
-->

<!-- ---------- 第一次啟動時的設定（story/setup.py） ---------- -->

## language_name
<!-- 選語言時顯示的這個語言的名稱 -->
繁體中文

## setup_key
需要 Gemini API key，可以到 https://aistudio.google.com/apikey 免費申請。會存在 ~/.config/story/config.toml。

## setup_key_prompt
Gemini API key（輸入時不會顯示，直接按 Enter 先跳過）：

## setup_theme
選擇終端機版的配色主題（之後可以在遊戲裡按 F2 換）：

## setup_theme_prompt
<!-- 變數：{default} 是直接按 Enter 時用的主題 -->
輸入編號（直接按 Enter 用 {default}）：

<!-- ---------- 共用層 ---------- -->

## mode_timed
<!-- 狀態列上跟回合同一排的模式 -->
限時模式

## mode_normal
一般模式


## ask_missing_key
找不到 Gemini API key。

## ask_new_key
API key 無效或沒有權限，請重新輸入。

## name_in_use
這個名字正在遊戲中，請換一個名字，或等對方離開。

## busy
<!-- 等 AI 時的提示。變數：{progress}（busy_progress，或空白） -->
故事生成中{progress}…

## busy_progress
<!-- 變數：{progress}，例如「規劃故事大綱」 -->
：{progress}

## ask_continue
<!-- 找到存檔時的確認框。變數：{notice}（core.md 的 found_save） -->
{notice}

要繼續嗎？

## wait_epilogue
按 Enter 看尾聲

## wait_ending
按 Enter 查看結局

## story_over
故事結束

## hint_input
<!-- 輸入框的提示 -->
↑↓ 選擇，或寫下你的行動

## hint_waiting
<!-- 線上多人：自己行動完了。變數：{names} -->
等待 {names} 行動…

## list_sep
、

<!-- ---------- 線上多人 ---------- -->

## room_name_hint
大家在同一局裡，每個名字就是一位角色。中途斷線可以用同一個名字回來。

## room_lost
和遊戲房間的連線中斷了。

## room_disconnected
和遊戲房間的連線中斷了，請重新整理頁面。

## acted
<!-- 有人行動了。變數：{names} -->
{names} 已行動

## host_mark
<!-- 大廳裡房主的名字。變數：{name} -->
{name}（房主）

## lobby_start
選「開始遊戲」，大家就會一起進入故事

## lobby_waiting_players
<!-- 變數：{min} -->
等其他玩家加入（至少 {min} 人）…

## lobby_waiting_host
<!-- 變數：{host} -->
等房主 {host} 開始遊戲…

## start_game
<!-- 房主在大廳裡的選項 -->
開始遊戲

## room_name_taken
這個名字已經在房間裡了，請換一個名字。

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

## host_setting_up
房主正在設定故事，請稍候。

## wait_host_story
<!-- 變數：{host} -->
等房主 {host} 設定好故事。

## wait_host_start
<!-- 變數：{host} -->
等房主 {host} 開始遊戲。

## need_players
<!-- 變數：{min} -->
至少要 {min} 位玩家才能開始。

## host_only_restart
只有房主能重新開始。

## server_key_invalid
伺服器的 Gemini API key 無效或沒有權限，請通知架站的人。

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

## server_party_help
線上多人：所有連進來的人一起玩同一局，使用伺服器的 API key

## server_no_key
網頁伺服器呼叫 AI 用架站者的 API key：請先在終端機裡執行一次 uv run story-web 輸入 key，或設定環境變數 GEMINI_API_KEY。

## server_open_warning
⚠ 已開放其他電腦連線。目前沒有 HTTPS，連線內容（名字、劇情）以明文傳送，名字也沒有密碼保護，只建議在信任的網路使用。

## server_mode_party
線上多人（大家一起玩同一局）

## server_mode_solo
單人（每個人各自玩）

## server_started
<!-- 變數：{host}、{port}、{mode} -->
伺服器已啟動：http://{host}:{port}　模式：{mode}　按 Ctrl+C 結束。

<!-- ---------- 純文字版 ---------- -->

## plain_ask_key
Gemini API key（輸入時不會顯示）：

## plain_bye
已存檔，下次見。
