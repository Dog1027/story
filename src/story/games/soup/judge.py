"""海龜湯的裁判：請 AI 判斷每一回合的提問與猜測、出題、檢查題目。提示詞在 prompts/語言/soup.md。

AI 只提議：回答與說中了哪幾個關鍵點由 AI 判斷，算不算解開由程式依關鍵點決定（game.py）。
"""

from pathlib import Path

from difflib import SequenceMatcher

from google.genai import types

from story.core.ai import LOG_PATH, MODEL, AICaller
from story.games.soup.models import Judgement, Move, Puzzle, PuzzleCheck, PuzzleDraft, SoupState, code, word
from story.games.soup.puzzles import MAX_POINTS, MIN_POINTS
from story.games.soup.text import TEXT, UI

SOUP = TEXT.sections("soup")
MAKE_ATTEMPTS = 2  # AI 出的題目檢查沒通過時，最多出幾次
WRITER_MODEL = "gemini-3.5-flash"  # 出題用比較強的模型：一局只出一次題，flash-lite 寫的湯底常常前後矛盾


def points_text(puzzle: Puzzle) -> str:
    return "\n".join(SOUP["point"].format(n=i, text=p) for i, p in enumerate(puzzle.key_points, 1))


def past_text(state: SoupState) -> str:
    """之前的問答，給裁判保持一致。"""
    total = len(state.puzzle.key_points)
    lines = []
    for move in (m for r in state.rounds for m in r):
        if move.kind == "ask":
            lines.append(SOUP["past_ask"].format(name=move.name, text=move.text, answer=word("soup_answer", move.answer)))
        elif move.kind == "guess":
            lines.append(SOUP["past_guess"].format(name=move.name, text=move.text, hit=move.hit, total=total))
    return "\n".join(lines) or SOUP["history_empty"]


def quoted(quote: str, guess: str) -> bool:
    """裁判引用的原文真的出自這個猜測（容許標點、空白不同，或少數幾個字的出入）。沒有引用到原文的關鍵點不算說中。"""
    squash = lambda text: "".join(ch for ch in text if ch.isalnum()).lower()  # noqa: E731
    quote, guess = squash(quote), squash(guess)
    if not quote:
        return False
    match = SequenceMatcher(None, quote, guess).find_longest_match(0, len(quote), 0, len(guess))
    return match.size >= max(2, len(quote) * 0.6)


class SoupJudge(AICaller):
    def __init__(self, api_key: str | None = None, client=None, log_path: Path = LOG_PATH):
        super().__init__(api_key, client, log_path)
        self.stage = ""  # 出題時目前在做什麼，外殼顯示在等待畫面上

    def judge(self, state: SoupState, moves: list[Move]) -> None:
        """判斷這一回合的提問與猜測，把回答與說中的關鍵點數寫進 moves。"""
        listed = "\n".join(
            SOUP["move_ask" if m.kind == "ask" else "move_guess"].format(n=i, name=m.name, text=m.text) for i, m in enumerate(moves, 1)
        )
        prompt = SOUP["judge"].format(
            surface=state.puzzle.surface, truth=state.puzzle.truth, points=points_text(state.puzzle), history=past_text(state), moves=listed
        )
        response = self.generate(
            "judge",
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SOUP["system"],
                response_mime_type="application/json",
                response_schema=Judgement,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),  # 逐點對照湯底，想清楚比較不會鬆緊不一
            ),
        )
        if not isinstance(response.parsed, Judgement):
            raise RuntimeError(UI["soup_no_ruling"])
        rulings = {r.move: r for r in response.parsed.rulings}
        total = len(state.puzzle.key_points)
        for i, move in enumerate(moves, 1):
            ruling = rulings.get(i)
            if ruling is None:
                raise RuntimeError(UI["soup_no_ruling"])  # 漏掉了某個人：這回合重來，不要亂猜一個回答
            if move.kind == "ask":
                move.answer = code("soup_answer", ruling.answer)
            else:
                move.hit = len({c.point for c in ruling.points if 1 <= c.point <= total and c.stated and quoted(c.quote, move.text)})
        self.write_log({"turn": state.turn + 1, "soup": [m.model_dump() for m in moves]})

    def make_puzzle(self, avoid: list[str]) -> Puzzle | None:
        """請 AI 出一題，再請它檢查合不合理；檢查沒通過就帶著問題重出，都不行時回傳 None。"""
        prompt = SOUP["make"].format(avoid="\n".join(f"- {t}" for t in avoid) or "-")
        try:
            for _ in range(MAKE_ATTEMPTS):
                self.stage = UI["soup_stage_make"]
                draft = self._draft(prompt)
                if draft is None:
                    self.write_log({"puzzle": None, "problem": "unparsable"})
                    continue
                self.stage = UI["soup_stage_check"]
                problem = self._problem(draft)
                self.write_log({"puzzle": draft.title, "problem": problem})  # 出題的每次嘗試都記下來，方便調整檢查的標準
                if not problem:
                    return draft
                prompt += "\n\n" + SOUP["retry"].format(problem=problem)
            return None
        finally:
            self.stage = ""

    def _draft(self, prompt: str) -> Puzzle | None:
        response = self.generate(
            "puzzle",
            model=WRITER_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SOUP["make_system"],
                response_mime_type="application/json",
                response_schema=PuzzleDraft,
                thinking_config=types.ThinkingConfig(thinking_level="low"),  # medium 常常超過請求的時限
            ),
        )
        draft = response.parsed
        if not isinstance(draft, PuzzleDraft):
            return None
        points = [p.strip() for p in draft.key_points if p.strip()][:MAX_POINTS]
        if len(points) < MIN_POINTS or not all(x.strip() for x in (draft.title, draft.surface, draft.truth)):
            return None
        return Puzzle(title=draft.title.strip(), surface=draft.surface.strip(), truth=draft.truth.strip(), key_points=points)

    def _problem(self, puzzle: Puzzle) -> str:
        """檢查題目：合理時回傳空字串，否則是問題所在。"""
        response = self.generate(
            "puzzle_check",
            model=MODEL,
            contents=SOUP["check"].format(surface=puzzle.surface, truth=puzzle.truth, points=points_text(puzzle)),
            config=types.GenerateContentConfig(
                system_instruction=SOUP["make_system"],
                response_mime_type="application/json",
                response_schema=PuzzleCheck,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),  # 要仔細找矛盾
            ),
        )
        check = response.parsed
        if not isinstance(check, PuzzleCheck):
            return UI["soup_no_ruling"]
        return "" if check.ok else (check.problem.strip() or "?")
