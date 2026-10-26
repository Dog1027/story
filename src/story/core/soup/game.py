"""海龜湯：AI 當裁判，大家一起猜湯底。共用的流程（隊伍、存檔接續、收集行動、再玩一次）在 team.py。

一局的流程：
1. 房主選從題庫抽一題，或請 AI 出一題（AI 出的題目會先檢查，不合理就重出，還是不行就改從題庫抽）
2. 大家看到湯面。每回合每個人同時行動：「提問」問一個是非題，或「猜湯底」說出推理，或「放棄」
3. 大家都行動後，裁判（AI）一次判斷這一回合所有的提問與猜測，大家都看得到每個人問了什麼、猜了什麼、裁判怎麼回答
4. 猜湯底說中所有關鍵點就解開了；同一回合有好幾個人說中，就一起獲勝。所有人同一回合都選放棄時公布湯底

輸入的方式（提問、猜湯底、放棄）用 Reply.inputs 告訴外殼：選項是切換方式，打的字用 /ask、/guess 送出。
"""

import random
from pathlib import Path

from story.core.ai import LOG_PATH
from story.core.models import word
from story.core.prompting import AWAY_ACTION, TIMEOUT_ACTION
from story.core.records import SAVE_PATH
from story.core.reply import UI, Ending, InputMode, Reply, Status, join, pick_choice
from story.core.soup.judge import SoupJudge
from story.core.soup.models import Move, Puzzle, SoupState
from story.core.soup.puzzles import load_puzzles
from story.core.team import FAILURES, PLAY_AGAIN_CHOICES, TeamGame

PUZZLE_CHOICES = [UI["soup_from_bank"], UI["soup_from_ai"]]
ASK, GUESS, GIVE_UP = "/ask", "/guess", "/give_up"
INPUTS = [
    InputMode(UI["soup_ask"], ASK, UI["soup_ask_hint"]),
    InputMode(UI["soup_guess"], GUESS, UI["soup_guess_hint"]),
    InputMode(UI["soup_give_up"], GIVE_UP, needs_text=False),
]


class SoupCore(TeamGame):
    setup_phase = "ask_puzzle"
    state_class = SoupState

    def __init__(
        self,
        api_key: str,
        players: list[str],
        *,
        save_path: Path = SAVE_PATH,
        log_path: Path = LOG_PATH,
        judge: SoupJudge | None = None,
        client=None,
        puzzles: list[Puzzle] | None = None,
    ):
        super().__init__(players, save_path)
        self.judge = judge or SoupJudge(api_key, client, log_path)
        self.puzzles = load_puzzles()[0] if puzzles is None else puzzles
        self.state: SoupState | None = None
        self.played: set[str] = set()  # 這個房間玩過的題目：從題庫抽時先抽沒玩過的，AI 出題時避開

    def set_api_key(self, api_key: str) -> None:
        self.judge.set_api_key(api_key)

    @property
    def progress(self) -> str:
        return self.judge.stage

    # ---------- 開新局：出題 ----------

    def _new_game(self) -> Reply:
        self._phase = "ask_puzzle"
        return self._reply(choices=PUZZLE_CHOICES, notice=UI["soup_ask_puzzle"])

    def _on_setup(self, raw: str) -> Reply:
        picked = pick_choice(raw, PUZZLE_CHOICES)
        if picked is None:
            return self._new_game()
        note, puzzle = "", None
        if picked == PUZZLE_CHOICES[1]:
            try:
                puzzle = self.judge.make_puzzle(avoid=[p.title for p in self.puzzles] + sorted(self.played))
            except FAILURES as e:  # 連不上、額度用完……：改從題庫抽，不要卡在出題
                note = UI["soup_ai_failed"].format(error=str(e)[:200])
            else:
                note = "" if puzzle else UI["soup_ai_unsound"]
        from_ai = puzzle is not None
        puzzle = puzzle or self._draw()
        if puzzle is None:
            return self._reply(choices=PUZZLE_CHOICES, notice=UI["soup_no_puzzles"])
        self.played.add(puzzle.title)
        self.state, self.pending, self._phase = SoupState(puzzle=puzzle, from_ai=from_ai, players=self._players), {}, "playing"
        self._save()
        return self._reply(narration="\n\n".join(filter(None, [note, self._surface()])), **self._screen())

    def _draw(self) -> Puzzle | None:
        fresh = [p for p in self.puzzles if p.title not in self.played]
        return random.choice(fresh or self.puzzles) if self.puzzles else None

    def _surface(self) -> str:
        p = self.state.puzzle
        return UI["soup_surface"].format(title=p.title, surface=p.surface, points=len(p.key_points))

    # ---------- 一回合 ----------

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
        return None if picked else f"{ASK} {' '.join(raw.split())}"  # 選了提問、猜湯底還要寫內容；直接打字就是提問

    def _play_round(self, actions: dict[str, str]) -> Reply:
        moves = [self._move(name, action) for name, action in actions.items()]
        if judged := [m for m in moves if m.kind in ("ask", "guess")]:
            self.judge.judge(self.state, judged)  # 失敗時 TeamGame 會撤回大家的行動，這回合重來
        s = self.state
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
        if action in (TIMEOUT_ACTION, AWAY_ACTION):
            return Move(name=name, kind="away")
        if action == GIVE_UP:
            return Move(name=name, kind="give_up")
        command, _, text = action.partition(" ")
        return Move(name=name, kind="guess" if command == GUESS else "ask", text=text)

    def _round_text(self, moves: list[Move], last: bool = False) -> str:
        """一回合的結果：每個人問了什麼、猜了什麼、裁判怎麼回答。大家看到的都一樣。
        last 是剛進行完的這一回合，要加上這一局的結果（誰解開了、大家都放棄了）。"""
        s = self.state
        total = len(s.puzzle.key_points)
        lines = []
        for m in moves:
            name = self._who(m.name)
            if m.kind == "ask":
                lines.append(UI["soup_line_ask"].format(name=name, text=m.text, answer=word("soup_answer", m.answer)))
            elif m.kind == "guess":
                lines.append(UI["soup_line_guess"].format(name=name, text=m.text, hit=m.hit, total=total))
            elif m.kind == "give_up":
                lines.append(UI["soup_line_give_up"].format(name=name))
            else:
                lines.append(UI["soup_line_away"].format(name=name))
        if last and s.winners:
            lines.append(UI["soup_solved"].format(names=join(self._who(n) for n in s.winners)))
        elif last and s.game_over:
            lines.append(UI["soup_all_gave_up"])
        elif any(m.kind == "give_up" for m in moves) and not (last and s.game_over):
            lines.append(UI["soup_give_up_pending"])
        return "\n\n".join(lines)

    def _who(self, name: str) -> str:
        """一個人玩時寫「你」，好幾個人時寫名字。"""
        return UI["soup_you"] if len(self._players) == 1 else name

    def _on_ending(self, raw: str) -> Reply:
        s = self.state
        winners = [self._who(n) for n in s.winners]
        if not winners:
            title = UI["soup_revealed"]
        else:
            title = UI["soup_won" if len(winners) == 1 else "soup_won_together"].format(names=join(winners))
        moves = [m for r in s.rounds for m in r]
        record = UI["soup_record"].format(
            turns=s.turn,
            questions=sum(m.kind == "ask" for m in moves),
            guesses=sum(m.kind == "guess" for m in moves),
            points="\n".join(f"- {p}" for p in s.puzzle.key_points),
        )
        self._phase = "ended"
        return self._reply(choices=PLAY_AGAIN_CHOICES, ending=Ending(title=title, epilogue=s.puzzle.truth, record=record, reveal=UI["soup_reveal"]))

    # ---------- 給 TeamGame 的資料 ----------

    def _choices(self, name: str) -> list[str]:
        return [m.label for m in INPUTS]

    def _screen_for(self, actor: str | None) -> dict:
        screen = super()._screen_for(actor)
        if screen:
            screen["inputs"] = list(INPUTS) if actor else []
        return screen

    def _status(self) -> dict:
        s = self.state
        total = len(s.puzzle.key_points)
        characters = []
        for name in s.players:
            best = s.best(name)
            items = [(UI["soup_status_questions"].format(count=s.questions(name)), "muted")]
            items.append((UI["soup_status_best"].format(hit=best, total=total), "good" if best else "muted"))
            characters.append(Status(conditions=items, name=name))
        return {"turn": s.turn + 1 if not s.game_over else s.turn, "timed": False, "characters": characters}

    def _replay(self) -> dict:
        return {"narration": self._surface(), "resumed": True, "history": [(self._round_text(r), "") for r in self.state.rounds]}

    def _help(self) -> str:
        return UI["soup_help"]

    def _memory(self) -> str:
        p = self.state.puzzle
        rounds = "\n\n".join(UI["soup_memory_round"].format(turn=i, text=self._round_text(r)) for i, r in enumerate(self.state.rounds, 1))
        return UI["soup_memory"].format(title=p.title, surface=p.surface, rounds=rounds or UI["soup_memory_empty"])

    def _render(self, reply: Reply) -> str:
        parts = []
        if reply.notice:
            parts.append(UI["text_notice"].format(notice=reply.notice))
        if reply.info:
            parts.append(UI["text_info"].format(title=reply.info[0], body=reply.info[1]))
        parts += [narration for narration, _ in reply.history]
        if reply.narration:
            parts.append(reply.narration)
        if reply.ending:
            parts += [UI["text_ending_title"].format(title=reply.ending.title), reply.ending.epilogue, reply.ending.record]
        if reply.choices:
            parts.append("\n".join(f"{i}. {c}" for i, c in enumerate(reply.choices, 1)))
        return "\n\n".join(parts)
