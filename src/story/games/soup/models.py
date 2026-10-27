"""海龜湯的資料結構：題目、AI 回傳的判斷與題目、程式保存的狀態（存檔）。"""

from typing import Literal

from pydantic import BaseModel, Field

from story.core.vocab import Vocab
from story.games.soup.text import TEXT

SCHEMA = TEXT.sections("schema")  # 欄位說明（prompts/語言/schema.md），跟著回傳格式送給 AI
SoupAnswer = Literal["yes", "no", "irrelevant", "partly", "not_question"]  # 裁判對提問的回答，詞在 prompts/語言/vocab.md
VOCAB = Vocab(TEXT.sections("vocab"), {"soup_answer": SoupAnswer})
word, code, words = VOCAB.word, VOCAB.code, VOCAB.words

MoveKind = Literal["ask", "guess", "give_up", "away"]  # 提問、猜湯底、放棄、暫時離開（網頁版替斷線的人送出）


class Puzzle(BaseModel):
    """一題海龜湯。key_points 是要猜中湯底必須說出的事實，全部說中才算解開。"""

    title: str
    surface: str  # 湯面：大家一開始看到的離奇情境
    truth: str  # 湯底：背後的真相，只有裁判（AI）知道
    key_points: list[str]


# ---------- AI 回傳的格式 ----------


class PointCheck(BaseModel):
    """猜湯底時，裁判對一個關鍵點的判斷：先引用猜測裡的原文，再判斷有沒有說中。"""

    point: int = Field(description=SCHEMA["PointCheck.point"])
    quote: str = Field(description=SCHEMA["PointCheck.quote"])
    stated: bool = Field(description=SCHEMA["PointCheck.stated"])


class Ruling(BaseModel):
    """裁判對一個行動的判斷。"""

    move: int = Field(description=SCHEMA["Ruling.move"])
    answer: words("soup_answer") = Field(description=SCHEMA["Ruling.answer"])
    points: list[PointCheck] = Field(description=SCHEMA["Ruling.points"])


class Judgement(BaseModel):
    rulings: list[Ruling] = Field(description=SCHEMA["Judgement.rulings"])


class PuzzleDraft(BaseModel):
    """AI 出的題目。"""

    title: str = Field(description=SCHEMA["PuzzleDraft.title"])
    surface: str = Field(description=SCHEMA["PuzzleDraft.surface"])
    truth: str = Field(description=SCHEMA["PuzzleDraft.truth"])
    key_points: list[str] = Field(description=SCHEMA["PuzzleDraft.key_points"])


class PuzzleCheck(BaseModel):
    ok: bool = Field(description=SCHEMA["PuzzleCheck.ok"])
    problem: str = Field(description=SCHEMA["PuzzleCheck.problem"])


# ---------- 程式保存的狀態 ----------


class Move(BaseModel):
    """一位玩家在一回合裡的行動，以及裁判的判斷。"""

    name: str
    kind: MoveKind
    text: str = ""
    answer: str = ""  # 提問：回答的代號（vocab.md 的 soup_answer）
    hit: int = 0  # 猜湯底：說中了幾個關鍵點


class SoupState(BaseModel):
    """一局海龜湯的狀態，存檔就是把它轉成 JSON。"""

    puzzle: Puzzle
    from_ai: bool = False  # 題目是 AI 出的（不是題庫的）
    players: list[str]
    turn: int = 0  # 已經進行了幾回合
    rounds: list[list[Move]] = Field(default_factory=list)  # 每回合每個人的行動
    winners: list[str] = Field(default_factory=list)  # 解開的人（同一回合說中全部關鍵點的人一起獲勝）
    game_over: bool = False

    @property
    def names(self) -> list[str]:
        return list(self.players)

    @property
    def premise(self) -> str:
        """找到存檔、讀取存檔時說明是哪一局（冒險是故事前提，這裡是題目名稱）。"""
        return self.puzzle.title

    def questions(self, name: str) -> int:
        return sum(1 for r in self.rounds for m in r if m.name == name and m.kind == "ask")

    def best(self, name: str) -> int:
        """這個人猜湯底時，最多說中過幾個關鍵點。"""
        return max((m.hit for r in self.rounds for m in r if m.name == name and m.kind == "guess"), default=0)
