"""懂中文的換行。

Textual 底層的 Rich 只在空格處換行，是為英文設計的：
- AI 習慣在英文名字前後加空格（「看向 Bob，發現……」），空格後面整段沒有空格的中文被當成一個長單字，
  放不進這一行就整段推到下一行，前一行因此提早斷掉
- 句號、逗號可能落在行首

這裡的規則：中文字之間哪裡都能換行；英文單字與數字保持完整；標點不放在行首，開頭的引號不留在行尾。
"""

import re

from rich.cells import cell_len
from rich.text import Text
from textual.widgets import Static

NO_LINE_START = set("。，、！？：；）」』》〉】〕…—‧·.,!?:;)]}%")  # 不能出現在行首
NO_LINE_END = set("（「『《〈【〔([{")  # 不能出現在行尾
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-_.]*|\s+|.", re.S)  # 英文單字、空白，或單一字元


def wrap(text: str, width: int) -> list[str]:
    """依顯示寬度（中文字佔兩格）把文字切成多行。"""
    width = max(width, 2)
    lines: list[str] = []
    for paragraph in text.split("\n"):
        lines += _wrap_paragraph(paragraph, width)
    return lines


def _wrap_paragraph(paragraph: str, width: int) -> list[str]:
    lines: list[str] = []
    line: list[str] = []
    used = 0

    def flush(carry: list[str]) -> None:
        nonlocal line, used
        lines.append("".join(line).rstrip())
        line, used = carry, sum(cell_len(t) for t in carry)

    for token in TOKEN.findall(paragraph):
        size = cell_len(token)
        if token.isspace():
            if line and used + size <= width:  # 行首與行尾的空白直接省略
                line.append(token)
                used += size
            elif line:
                flush([])
            continue
        if used + size <= width:
            line.append(token)
            used += size
            continue
        if size > width:  # 比一整行還長的英文單字，只好拆開
            for ch in token:
                if used + cell_len(ch) > width:
                    flush([])
                line.append(ch)
                used += cell_len(ch)
            continue
        carry: list[str] = []
        if token in NO_LINE_START and len(line) > 1:
            carry = [line.pop()]  # 標點不放行首：把前一個字一起帶到下一行
        while len(line) > 1 and line[-1] in NO_LINE_END:
            carry.insert(0, line.pop())  # 開頭的引號不留在行尾
        while line and line[-1].isspace():
            line.pop()
        flush(carry)
        line.append(token)
        used += size
    lines.append("".join(line).rstrip())
    return lines


class Prose(Static):
    """用上面的規則換行的文字區塊，視窗寬度改變時會重新排版。"""

    def __init__(self, text: str = "", **kwargs):
        super().__init__("", **kwargs)
        self.text = text

    def set_text(self, text: str) -> None:
        self.text = text
        self.refresh(layout=True)

    def get_content_height(self, container, viewport, width: int) -> int:
        return len(wrap(self.text, width))

    def render(self) -> Text:
        return Text("\n".join(wrap(self.text, self.content_region.width or 80)))
