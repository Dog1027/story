"""遊戲指令。"""

from story.core import ui_text

UI = ui_text("terminal")  # story/ui/語言/terminal.md

# 指令名稱 -> (快捷鍵, 說明)
COMMANDS = {
    "/state": ("ctrl+t", UI["command_state"]),
    "/restart": ("ctrl+r", UI["command_restart"]),
    "/theme": ("f2", UI["command_theme"]),
    "/help": ("f1", UI["command_help"]),
    "/quit": ("ctrl+q", UI["command_quit"]),
}


def help_text() -> str:
    lines = [f"{name:<9} {key:<7} {desc}" for name, (key, desc) in COMMANDS.items()]
    return "\n".join([UI["help_header"], *lines, "", UI["help"]])
