"""Textual 外殼的外觀：配色主題、狀態顏色、打字節奏。"""

from textual.color import Color
from textual.theme import Theme

THEME = "tokyo-night"  # 預設主題；遊戲中可以用 /theme（F2）換，終端機版會記住

CHAR_DELAY = 0.05  # 每個字的間隔秒數，大約一秒 20 個字（跟網頁版一樣）
FAST_FACTOR = 0.15  # 按一次 Enter 後，間隔縮成原本的幾倍
PAUSE_AFTER = {"。": 0.25, "！": 0.25, "？": 0.25, "，": 0.1, "、": 0.08, "…": 0.15, "\n": 0.1}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"



def palette(theme: Theme) -> dict[str, str]:
    """狀態、傷勢、倒數用的顏色，從主題的成功／警告／錯誤色算出來，換主題時跟著變。
    鍵是程度（輕、中、重）、整體狀態（良好……死亡）、核心回報變化的語氣（good、bad……），值是 Rich 樣式字串。"""
    ok = Color.parse(theme.success or "#9ece6a")
    warn = Color.parse(theme.warning or "#e0af68")
    bad = Color.parse(theme.error or "#f7768e")
    mid = warn.blend(bad, 0.4)  # 介於警告與錯誤之間：中度
    worst = bad.darken(0.1)
    # 轉成 Rich 認得的顏色名稱（ansi 主題的顏色是 ansi_red 這種名稱，Rich 不認得，要換成 color(1)）
    ok, warn, mid, bad, worst = (c.rich_color.name for c in (ok, warn, mid, bad, worst))
    return {
        "輕": warn, "中": mid, "重": bad,
        "良好": ok, "輕傷": warn, "受傷": mid, "重傷": bad, "瀕死": worst, "死亡": worst,
        "good": ok, "bad": bad, "plain": "", "muted": "dim",
    }
