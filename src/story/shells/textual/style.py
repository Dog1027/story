"""Textual 外殼的外觀：配色主題、狀態顏色、打字節奏。"""

THEME = "tokyo-night"  # 其他選擇：catppuccin-mocha、rose-pine、nord、dracula……

CHAR_DELAY = 0.03  # 每個字的間隔秒數
FAST_FACTOR = 0.15  # 按一次 Enter 後，間隔縮成原本的幾倍
PAUSE_AFTER = {"。": 0.25, "！": 0.25, "？": 0.25, "，": 0.1, "、": 0.08, "…": 0.15, "\n": 0.1}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

SEVERITY_COLORS = {"輕": "#e0af68", "中": "#ff9e64", "重": "#f7768e"}
LEVEL_COLORS = {"良好": "#9ece6a", "輕傷": "#e0af68", "受傷": "#ff9e64", "重傷": "#f7768e", "瀕死": "#db4b4b", "死亡": "#db4b4b"}
# 核心回報變化時給的語氣 → 顏色（Rich 樣式字串）
TONE_STYLES = {**SEVERITY_COLORS, "good": "#9ece6a", "bad": "#f7768e", "plain": "", "muted": "dim"}
