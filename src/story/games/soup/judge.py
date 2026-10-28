"""The turtle soup judge: has the AI rule on each turn's questions and guesses, write puzzles, and check them. The prompts are in prompts/<lang>/soup.md.

The AI only proposes: it judges the answers and which key points were hit; whether that solves the puzzle is decided by the program from the key points (game.py).
"""

from pathlib import Path

from difflib import SequenceMatcher

from google.genai import types

from story.core.ai import MODEL, AICaller
from story.games.soup.models import Judgement, Move, Puzzle, PuzzleCheck, PuzzleDraft, SoupState, code, word
from story.games.soup.puzzles import MAX_POINTS, MIN_POINTS
from story.games.soup.text import TEXT, UI

SOUP = TEXT.sections("soup")
MAKE_ATTEMPTS = 2  # How many times to write a puzzle when the AI's puzzle fails the check
WRITER_MODEL = "gemini-3.5-flash"  # A stronger model writes puzzles: it's only once a game, and flash-lite's truths often contradict themselves


def points_text(puzzle: Puzzle) -> str:
    return "\n".join(SOUP["point"].format(n=i, text=p) for i, p in enumerate(puzzle.key_points, 1))


def past_text(state: SoupState) -> str:
    """Earlier questions and answers, so the judge stays consistent."""
    total = len(state.puzzle.key_points)
    lines = []
    for move in (m for r in state.rounds for m in r):
        if move.kind == "ask":
            lines.append(SOUP["past_ask"].format(name=move.name, text=move.text, answer=word("soup_answer", move.answer)))
        elif move.kind == "guess":
            lines.append(SOUP["past_guess"].format(name=move.name, text=move.text, hit=move.hit, total=total))
    return "\n".join(lines) or SOUP["history_empty"]


def quoted(quote: str, guess: str) -> bool:
    """Whether the text the judge quotes really comes from this guess (allowing different punctuation, spacing, or a few characters off). A key point without a real quote doesn't count."""
    squash = lambda text: "".join(ch for ch in text if ch.isalnum()).lower()  # noqa: E731
    quote, guess = squash(quote), squash(guess)
    if not quote:
        return False
    match = SequenceMatcher(None, quote, guess).find_longest_match(0, len(quote), 0, len(guess))
    return match.size >= max(2, len(quote) * 0.6)


class SoupJudge(AICaller):
    def __init__(self, api_key: str | None = None, client=None, log_path: Path | None = None):
        super().__init__(api_key, client, log_path)
        self.stage = ""  # What's happening while writing a puzzle, shown on the waiting screen

    def judge(self, state: SoupState, moves: list[Move]) -> None:
        """Rule on this turn's questions and guesses, writing the answers and key points hit into moves."""
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
                thinking_config=types.ThinkingConfig(thinking_level="medium"),  # Comparing point by point with the truth; thinking it through keeps rulings consistent
            ),
        )
        if not isinstance(response.parsed, Judgement):
            raise RuntimeError(UI["soup_no_ruling"])
        rulings = {r.move: r for r in response.parsed.rulings}
        total = len(state.puzzle.key_points)
        for i, move in enumerate(moves, 1):
            ruling = rulings.get(i)
            if ruling is None:
                raise RuntimeError(UI["soup_no_ruling"])  # Someone was left out: redo the turn rather than guess an answer
            if move.kind == "ask":
                move.answer = code("soup_answer", ruling.answer)
            else:
                move.hit = len({c.point for c in ruling.points if 1 <= c.point <= total and c.stated and quoted(c.quote, move.text)})
        self.write_log({"turn": state.turn + 1, "soup": [m.model_dump() for m in moves]})

    def make_puzzle(self, avoid: list[str]) -> Puzzle | None:
        """Have the AI write a puzzle, then check whether it holds up; if not, rewrite it with the problem attached. Returns None if every attempt fails."""
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
                self.write_log({"puzzle": draft.title, "problem": problem})  # Log every attempt, to help tune the check
                if not problem:
                    return draft
                prompt += "\n\n" + SOUP["retry"].format(problem=problem)
            return None
        finally:
            self.stage = ""

    def _draft(self, prompt: str) -> Puzzle | None:
        response = self.generate(
            "puzzle",
            hedge_after=None,  # Slow by nature, and the writer model allows only a few calls a minute: never send twice
            model=WRITER_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=SOUP["make_system"],
                response_mime_type="application/json",
                response_schema=PuzzleDraft,
                thinking_config=types.ThinkingConfig(thinking_level="low"),  # medium often runs past the request timeout
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
        """Check a puzzle: an empty string if it holds up, otherwise what's wrong."""
        response = self.generate(
            "puzzle_check",
            hedge_after=None,  # Slow by nature (it thinks the puzzle through): never send twice
            model=MODEL,
            contents=SOUP["check"].format(surface=puzzle.surface, truth=puzzle.truth, points=points_text(puzzle)),
            config=types.GenerateContentConfig(
                system_instruction=SOUP["make_system"],
                response_mime_type="application/json",
                response_schema=PuzzleCheck,
                thinking_config=types.ThinkingConfig(thinking_level="medium"),  # Look carefully for contradictions
            ),
        )
        check = response.parsed
        if not isinstance(check, PuzzleCheck):
            return UI["soup_no_ruling"]
        return "" if check.ok else (check.problem.strip() or "?")
