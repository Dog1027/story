<!--
核心給玩家看的文字（每種玩法都會用到的）：選項、通知、錯誤。各玩法自己的文字在 story/games/玩法/ui/。
格式跟提示詞一樣：每段以「## 名稱」開頭，名稱是程式找段落用的，不能改；{名稱} 是程式填入的變數。
-->

<!-- ---------- 列舉與標點 ---------- -->

## list_sep
<!-- 把好幾項串成一句時的分隔（例如狀態、物品、名字） -->
、

<!-- ---------- 選項（玩家也可以直接打這些字） ---------- -->

## choice_continue
繼續

## choice_new_game
開新遊戲

## choice_confirm
確定

## choice_cancel
取消

## choice_play_again
再玩一次

<!-- ---------- 通知 ---------- -->

## found_save
<!-- 變數：{turn}、{premise} -->
找到存檔（第 {turn} 回合）：{premise}

要繼續嗎？

## resumed
<!-- 變數：{premise} -->
讀取存檔：{premise}

## answer_continue
請輸入 1（繼續）或 2（開新遊戲）。

## answer_confirm
請輸入 1（確定）或 2（取消）。

## answer_play_again
輸入 1 再玩一次。

## confirm_restart
確定要放棄目前進度、重新開始嗎？

## unknown_command
<!-- 變數：{command} -->
沒有 {command} 這個指令，輸入 /help 查看說明。

## enter_action
請輸入行動，或輸入數字選擇選項。

## no_story_yet
還沒有開始故事。

## character_fallen
你的角色已經倒下了。

## already_acted
你這回合已經行動了，等其他人行動。

## team_size
<!-- 變數：{min}、{max} -->
隊伍需要 {min} 到 {max} 位不重複的玩家。

<!-- ---------- 錯誤 ---------- -->

## key_invalid
伺服器的 Gemini API key 無效或沒有權限，請通知架站的人。

## failed
<!-- AI 呼叫失敗。變數：{hint}（failed_turn、failed_ending，或空白）、{error} -->
{hint}出錯了：{error}

## failed_turn
這回合沒有推進，請重新選擇行動。

## failed_ending
<!-- 故事結束後整理結局時出錯：不會自動重試（同一個錯誤只會一直重複），由玩家決定什麼時候再試 -->
結局還沒整理好，送出任何文字可以再試一次。

## timeout
Gemini 太久沒有回應、連不上或連線中斷了，請稍後再試。

## unexpected
<!-- 程式本身出錯（不是 AI 呼叫失敗）：這回合已經還原，可以再試一次 -->
程式本身的問題（詳細原因記在伺服器的 server.log）

## unparsable
<!-- AI 回傳的格式不對。變數：{reason} -->
模型輸出無法解析（{reason}），請換個行動試試。

## no_content
沒有內容

<!-- ---------- /help 與 /state ---------- -->

## help_title
說明

## memory_title
程式記住的東西
