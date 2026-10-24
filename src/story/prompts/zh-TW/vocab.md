<!--
遊戲詞彙：程式裡與存檔裡用語言無關的代號（冒號前面），給 AI 看、讓 AI 回傳、顯示給玩家時換成這裡的詞（冒號後面）。
AI 回傳格式裡的選項（例如程度只能是輕、中、重）就是這些詞，所以 schema.md、system.md 提到它們時要用一樣的字。
代號由程式使用，不能改，也不能少；只改冒號後面。同一段裡的詞不能重複。
-->

## severity
<!-- 狀態的程度，由輕到重 -->
light: 輕
moderate: 中
severe: 重

## kind
<!-- 狀態的類別 -->
body: 身體
mind: 精神

## time_span
<!-- 一回合經過多久（schema.md 的 StoryBeat.time_passed 說明了每個詞代表多久） -->
instant: 瞬間
moment: 片刻
while: 一陣子
hours: 數小時
night: 一夜
days: 數天

## time_of_day
<!-- 時段：開場時由 AI 挑，之後由程式依時鐘換算 -->
dawn: 清晨
morning: 上午
noon: 中午
afternoon: 下午
dusk: 傍晚
evening: 夜晚
late_night: 深夜

## level
<!-- 身體的整體狀態（由程式依傷勢總分判定），由好到壞 -->
healthy: 良好
minor: 輕傷
injured: 受傷
serious: 重傷
dying: 瀕死
dead: 死亡
