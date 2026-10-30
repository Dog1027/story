"""Turtle soup: the AI is the judge while everyone guesses the truth. The shared flow (the team, continuing saves, collecting actions, playing again) is in story/core/team.py.

How a game goes:
1. The host draws a puzzle from the bank or has the AI write one (an AI puzzle is checked first and rewritten if it doesn't hold up; if it still fails, one is drawn from the bank)
2. Everyone sees the scenario. Each turn everyone acts at the same time: "ask" a yes/no question, "guess" the truth with their reasoning, or "give up"
3. Once everyone has acted, the judge (the AI) rules on every question and guess this turn at once, and everyone sees what each person asked or guessed and how the judge answered
4. A guess that states every key point solves it; several people who do in the same turn win together. When everyone gives up in the same turn, the truth is revealed

The input modes (ask, guess, give up) reach the shells through Reply.inputs: choices switch modes, and typed text is sent with /ask or /guess.
"""

import random
from pathlib import Path

from story.core.ai import AIFailed, GeminiClient
from story.core.reply import AWAY, Ending, InputMode, Reply, Status, Tone, join, pick_choice
from story.core.team import PLAY_AGAIN_CHOICES, ReplayFields, ScreenFields, StatusFields, TeamGame
from story.games.soup.judge import SoupJudge
from story.games.soup.models import Move, Puzzle, SoupState, word
from story.games.soup.puzzles import load_puzzles
from story.games.soup.text import UI

PUZZLE_CHOICES = [UI["from_bank"], UI["from_ai"]]
ASK, GUESS, GIVE_UP = "/ask", "/guess", "/give_up"
INPUTS = [
    InputMode(UI["ask"], ASK, UI["ask_hint"]),
    InputMode(UI["guess"], GUESS, UI["guess_hint"]),
    InputMode(UI["give_up"], GIVE_UP, needs_text=False, confirm=(UI["give_up_confirm"], UI["give_up_yes"], UI["give_up_no"])),
]


class SoupCore(TeamGame[SoupState]):
    title = UI["title"]
    busy_label = UI["busy"]
    description = UI["description"]
    state_class = SoupState
    timeout_action = away_action = AWAY  # No time limit; someone who disconnected counts as away this turn

    def __init__(
        self,
        api_key: str,
        players: list[str],
        *,
        save_path: Path,
        log_path: Path | None = None,
        judge: SoupJudge | None = None,
        client: GeminiClient | None = None,
        puzzles: list[Puzzle] | None = None,
    ):
        self.judge = judge or SoupJudge(api_key, client, log_path)
        super().__init__(players, save_path, ai=self.judge)
        self.puzzles = load_puzzles()[0] if puzzles is None else puzzles
        self.played: set[str] = set()  # Puzzles this room has played: drawing from the bank prefers unplayed ones, and the AI avoids them

    # ---------- New game: the puzzle ----------

    def _new_game(self) -> Reply:
        self._phase = "setup"
        return self._reply(choices=PUZZLE_CHOICES, notice=UI["ask_puzzle"])

    def _on_setup(self, raw: str) -> Reply:
        picked = pick_choice(raw, PUZZLE_CHOICES)
        if picked is None:
            return self._new_game()
        note, puzzle = "", None
        if picked == PUZZLE_CHOICES[1]:
            try:
                puzzle = self.judge.make_puzzle(avoid=[p.title for p in self.puzzles] + sorted(self.played))
            except AIFailed as e:  # Unreachable, out of quota…: draw from the bank instead of getting stuck
                note = UI["ai_failed"].format(error=str(e)[:200])
            else:
                note = "" if puzzle else UI["ai_unsound"]
        from_ai = puzzle is not None
        puzzle = puzzle or self._draw()
        if puzzle is None:
            return self._reply(choices=PUZZLE_CHOICES, notice=UI["no_puzzles"])
        self.played.add(puzzle.title)
        self.state, self.pending, self._phase = SoupState(puzzle=puzzle, from_ai=from_ai, players=self._players), {}, "playing"
        self._save()
        return self._reply(narration="\n\n".join(filter(None, [note, self._surface()])), **self._screen())

    def _draw(self) -> Puzzle | None:
        fresh = [p for p in self.puzzles if p.title not in self.played]
        return random.choice(fresh or self.puzzles) if self.puzzles else None

    def _surface(self) -> str:
        p = self.game.puzzle
        return UI["surface"].format(title=p.title, surface=p.surface, points=len(p.key_points))

    # ---------- A turn ----------

    def _is_action(self, raw: str) -> bool:
        return raw.split(" ", 1)[0] in (ASK, GUESS, GIVE_UP) or super()._is_action(raw)

    def _action(self, raw: str, actor: str | None) -> str | None:
        command, _, text = raw.partition(" ")
        if command in (ASK, GUESS):
            return f"{command} {' '.join(text.split())}" if text.strip() else None
        if raw == GIVE_UP:
            return GIVE_UP
        if raw.startswith("/"):
            return None
        picked = pick_choice(raw, [m.label for m in INPUTS])
        if picked == INPUTS[2].label:
            return GIVE_UP
        return None if picked else f"{ASK} {' '.join(raw.split())}"  # Picking ask or guess still needs text; typing directly is a question

    def _play_round(self, actions: dict[str, str]) -> Reply:
        moves = [self._move(name, action) for name, action in actions.items()]
        if judged := [m for m in moves if m.kind in ("ask", "guess")]:
            self.judge.judge(self.game, judged)  # On failure TeamGame takes back everyone's actions and the turn starts over
        s = self.game
        s.rounds.append(moves)
        s.turn += 1
        s.winners = [m.name for m in moves if m.kind == "guess" and m.hit == len(s.puzzle.key_points)]
        gave_up = any(m.kind == "give_up" for m in moves) and all(m.kind in ("give_up", "away") for m in moves)
        if s.winners or gave_up:
            s.game_over, self._phase = True, "ending"
        self._save()
        return self._reply(narration=self._round_text(moves, last=True), **self._screen())

    @staticmethod
    def _move(name: str, action: str) -> Move:
        if action == AWAY:
            return Move(name=name, kind="away")
        if action == GIVE_UP:
            return Move(name=name, kind="give_up")
        command, _, text = action.partition(" ")
        return Move(name=name, kind="guess" if command == GUESS else "ask", text=text)

    def _round_text(self, moves: list[Move], last: bool = False) -> str:
        """A turn's results: what each person asked or guessed and how the judge answered. Everyone sees the same thing.
        last is the turn just played, which adds the game's result (who solved it, or that everyone gave up)."""
        s = self.game
        total = len(s.puzzle.key_points)
        lines = []
        for m in moves:
            name = self._who(m.name)
            if m.kind == "ask":
                lines.append(UI["line_ask"].format(name=name, text=m.text, answer=word("soup_answer", m.answer)))
            elif m.kind == "guess":
                hits = UI["hits"].format(points=join(s.puzzle.key_points[n - 1] for n in m.points)) if m.points else ""
                lines.append(UI["line_guess"].format(name=name, text=m.text, hit=m.hit, total=total, hits=hits))
            elif m.kind == "give_up":
                lines.append(UI["line_give_up"].format(name=name))
            else:
                lines.append(UI["line_away"].format(name=name))
        if last and s.winners:
            lines.append(UI["solved"].format(names=join(self._who(n) for n in s.winners)))
        elif last and s.game_over:
            lines.append(UI["all_gave_up"])
        elif any(m.kind == "give_up" for m in moves):
            lines.append(UI["give_up_pending"])
        return "\n\n".join(lines)

    def _who(self, name: str) -> str:
        """"You" when playing alone, the name with several players."""
        return UI["you"] if len(self._players) == 1 else name

    def _on_ending(self, raw: str) -> Reply:
        s = self.game
        winners = [self._who(n) for n in s.winners]
        if not winners:
            title = UI["revealed"]
        else:
            title = UI["won" if len(winners) == 1 else "won_together"].format(names=join(winners))
        moves = [m for r in s.rounds for m in r]
        record = UI["record"].format(
            turns=s.turn,
            questions=sum(m.kind == "ask" for m in moves),
            guesses=sum(m.kind == "guess" for m in moves),
            points="\n".join(f"- {p}" for p in s.puzzle.key_points),
        )
        self._phase = "ended"
        return self._reply(choices=PLAY_AGAIN_CHOICES, ending=Ending(title=title, epilogue=s.puzzle.truth, record=record, reveal=UI["reveal"]))

    # ---------- Data for TeamGame ----------

    def _choices(self, name: str) -> list[str]:
        return [m.label for m in INPUTS]

    def _screen_for(self, actor: str | None) -> ScreenFields:
        screen = super()._screen_for(actor)
        if screen:
            screen["inputs"] = list(INPUTS) if actor else []
        return screen

    def _status(self) -> StatusFields:
        s = self.game
        total = len(s.puzzle.key_points)
        characters = []
        for name in s.players:
            best = s.best(name)
            items: list[tuple[str, Tone]] = [(UI["status_questions"].format(count=s.questions(name)), "muted")]
            items.append((UI["status_best"].format(hit=best, total=total), "good" if best else "muted"))
            characters.append(Status(items=items, name=name))
        return {"turn": s.turn + 1 if not s.game_over else s.turn, "timed": False, "characters": characters}

    def _replay(self) -> ReplayFields:
        """The scenario comes first, then each earlier turn in order; the latest turn is the current part."""
        texts = [self._surface()] + [self._round_text(r) for r in self.game.rounds]
        return {"narration": texts[-1], "resumed": True, "history": [(t, "") for t in texts[:-1]]}

    def _help(self) -> str:
        return UI["help"]

    def _memory(self) -> str:
        p = self.game.puzzle
        rounds = "\n\n".join(UI["memory_round"].format(turn=i, text=self._round_text(r)) for i, r in enumerate(self.game.rounds, 1))
        return UI["memory"].format(title=p.title, surface=p.surface, rounds=rounds or UI["memory_empty"])
