"""遊戲指令。"""

# 指令名稱 -> (快捷鍵, 說明)
COMMANDS = {
    "/state": ("ctrl+t", "看程式記住了什麼"),
    "/restart": ("ctrl+r", "重新開始"),
    "/theme": ("f2", "選擇配色主題"),
    "/help": ("f1", "顯示指令列表"),
    "/quit": ("ctrl+q", "存檔並離開"),
}


def help_text() -> str:
    lines = [f"{name:<9} {key:<7} {desc}" for name, (key, desc) in COMMANDS.items()]
    return "\n".join(
        [
            "指令      快捷鍵",
            *lines,
            "",
            "輸入 / 或按 Ctrl+P 開啟指令選單",
            "↑↓ 或數字選擇選項，也可以直接打字自由行動",
            "文字顯示中按 Enter 加速，再按一次全部顯示",
            "",
            "限時模式（開新遊戲時選擇）：情勢緊迫時會出現倒數，",
            "時間到就當作你遲疑了。開著對話框或選單時倒數會暫停。",
        ]
    )
