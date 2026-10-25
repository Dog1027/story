<!--
AI 回傳格式的欄位說明：跟著回傳格式一起送給 AI，告訴它每個欄位要填什麼。
劇情的字數、選項的個數、狀態名稱的長度這類規定，就是改這裡。
段落名稱是「格式.欄位」，對應 story/core/models.py 的欄位，名稱不能改；欄位的型別與可填的值（例如程度只能是輕、中、重）由程式決定。
-->

<!-- ---------- ConditionChange：AI 回報的一個狀態（傷勢或情緒） ---------- -->

## ConditionChange.name
狀態名稱，2-8 字，例如「右腿骨折」「中毒」「恐懼」

## ConditionChange.kind
身體＝受傷、疲勞、中毒、疾病；精神＝恐懼、驚慌、絕望、憤怒

## ConditionChange.severity
輕＝不影響行動；中＝明顯妨礙行動；重＝危及性命

<!-- ---------- CharacterUpdate：一位角色這回合的變化 ---------- -->

## CharacterUpdate.name
角色名字，必須是「隊伍」裡的名字

## CharacterUpdate.choices
給這位角色的 2-4 個行動選項，每個一句話；角色已死亡時留空

## CharacterUpdate.conditions_changed
這位角色新出現的狀態，或程度改變的既有狀態

## CharacterUpdate.conditions_removed
這位角色痊癒或消失的既有狀態名稱

## CharacterUpdate.items_gained
這位角色本回合獲得的物品名稱

## CharacterUpdate.items_lost
這位角色本回合失去或用掉的物品名稱

<!-- ---------- StoryBeat：每回合的回傳 ---------- -->

## StoryBeat.game_over
寫劇情之前先決定：故事是否在本回合自然走到結局

## StoryBeat.narration
本回合的劇情敘述，包含每位角色行動的結果，150-300 字（角色多時可以到 400 字）；只有一位角色時用第二人稱「你」，好幾位時用名字

## StoryBeat.character_updates
隊伍中每位角色各一筆，順序和「隊伍」相同

## StoryBeat.time_passed
本回合經過的時間：瞬間＝打鬥閃避；片刻＝對話、搜索；一陣子＝趕路，約一小時；一夜＝睡覺

## StoryBeat.start_time_of_day
現在的時段；只在開場或時間「尚未確定」時採用

## StoryBeat.time_limit
限時模式下緊迫時的反應秒數，否則為 0

## StoryBeat.milestone_reached
本回合是否達成了「故事進度」中目前這一幕的里程碑

## StoryBeat.flags_set
新確立的長期事實，例如「與守門人結仇」；通常為空

## StoryBeat.key_event
改變故事走向的大事，一句話；大多數回合為空字串

<!-- ---------- Act：大綱的一幕 ---------- -->

## Act.name
這一幕的名稱，4-8 字

## Act.milestone
這一幕結束前必須發生的關鍵事件，一句話，要具體可判斷

<!-- ---------- StoryArc：隱藏的故事大綱 ---------- -->

## StoryArc.goal
主角在這個故事裡的核心目標或要解開的謎團，一句話

## StoryArc.twist
隱藏的真相：玩家一開始不知道、第三幕才揭露，會顛覆玩家對處境的理解。出人意料但合理，不能決定玩家角色的生死，一句話

## StoryArc.clues
2-3 個伏筆：第一、二幕可以自然出現在環境、NPC、物品或文件上的細節，當下看似無關，事後回想都指向真相，各一句話

## StoryArc.acts
剛好四幕：起（建立處境）、承（深入與阻礙）、轉（揭露隱藏的真相，里程碑就是揭露它）、合（高潮與結局）

## StoryArc.endings
2-3 種可能的結局方向，依玩家的抉擇而定，各一句話

<!-- ---------- GenrePick：題材選「自動」時，AI 挑的題材 ---------- -->

## GenrePick.genre
照抄「題材目錄」裡最適合這個故事前提的題材名稱；都不適合就留空

<!-- ---------- Epilogue：故事結束後的尾聲 ---------- -->

## Epilogue.title
結局名稱，4-10 字，像小說的章名，例如「燈塔守望者」「未寄出的信」

## Epilogue.text
尾聲，150-250 字：回顧主角這趟旅程的關鍵抉擇，交代結局帶來的餘韻，可以提到其他角色之後的命運
