"""遊戲詞彙：程式與存檔用代號；給 AI 看、AI 回傳、顯示給玩家時，換成這個語言的詞。

每種玩法有自己的詞彙（prompts/語言/vocab.md），用 Vocab 讀：一段是一個類別，一行「代號: 詞」。
"""

from typing import Literal, get_args

from story.core import prompts


class Vocab:
    def __init__(self, sections: dict[str, str], codes: dict):
        """sections 是 vocab.md 的每一段，codes 是 {類別: 代號的 Literal}。少了哪個代號的詞就報錯。"""
        self.codes = codes
        self.table = {category: prompts.table(body) for category, body in sections.items()}  # {類別: {代號: 詞}}
        for category, options in codes.items():
            if missing := set(get_args(options)) - set(self.table.get(category, {})):
                raise ValueError(f"vocab.md 的「{category}」少了：{'、'.join(sorted(missing))}")

    def word(self, category: str, code: str) -> str:
        """代號 → 這個語言的詞，例如 word("severity", "severe") 是「重」。"""
        return self.table[category][code]

    def code(self, category: str, text: str) -> str:
        """這個語言的詞 → 代號（AI 回傳的是詞）。"""
        return next(c for c, w in self.table[category].items() if w == text)

    def words(self, category: str):
        """AI 回傳格式用的選項：這個類別所有的詞，依代號的順序。"""
        return Literal[tuple(self.word(category, c) for c in get_args(self.codes[category]))]
