"""隊伍遊戲的共用流程：冒險（session.py 的 StoryCore）與海龜湯（soup/ 的 SoupCore）都是它的子類別。

一局遊戲是一支一到 MAX_PLAYERS 人的隊伍。每位玩家的行動用 send_as(名字, 文字) 送，誰先送誰先記，
還在場上的人都行動了，才交給子類別推進一回合（_play_round）；只有一位玩家時，send(文字) 就是他的行動。
不屬於某位玩家的輸入（時間到、對話框的回答、/state）用 send()。view(名字) 取得某位玩家眼中的畫面。

這裡管：玩家名單、找到存檔時問要不要繼續、收集每個人的行動（推進失敗時全部撤回）、確認重新開始、再玩一次、
view()、waiting()、失敗時的回覆、組回覆。子類別管：開新局要問什麼（setup_phase）、一回合怎麼推進、
結局、狀態列、純文字版的樣子，以及存檔的格式（state_class）。存檔要有 names、premise、turn、game_over。
"""

from dataclasses import replace
from pathlib import Path

from google.genai import errors
from pydantic import BaseModel

from story.core.ai import is_key_error
from story.core.prompting import AWAY_ACTION, TIMEOUT_ACTION
from story.core.records import load, save
from story.core.reply import MAX_PLAYERS, UI, Phase, Reply, pick_choice

CONTINUE_CHOICES = [UI["choice_continue"], UI["choice_new_game"]]
CONFIRM_CHOICES = [UI["choice_confirm"], UI["choice_cancel"]]
PLAY_AGAIN_CHOICES = [UI["choice_play_again"]]
FAILURES = (errors.APIError, RuntimeError)  # 呼叫 AI 失敗：留在原本的階段，讓玩家重試


class TeamGame:
    setup_phase: Phase  # 開新局時等玩家回答的階段（冒險是 ask_premise，海龜湯是 ask_puzzle）
    state_class: type[BaseModel]  # 存檔的格式

    def __init__(self, players: list[str], save_path: Path):
        names = [n.strip() for n in players if n.strip()]
        if not 1 <= len(names) <= MAX_PLAYERS or len(set(names)) != len(names):
            raise ValueError(UI["team_size"].format(min=1, max=MAX_PLAYERS))
        self._players = names
        self.save_path = save_path
        self.state = None  # 這一局的狀態（state_class）；還沒開始時是 None
        self._phase: Phase = self.setup_phase
        self.pending: dict[str, str] = {}  # 這一回合已經送出的行動
        self._as: str | None = None  # send_as() 指定的玩家

    # ---------- 對外介面 ----------

    @property
    def players(self) -> list[str]:
        """隊伍裡的玩家名字（唯讀），依建立時的順序。"""
        return list(self._players)

    @property
    def phase(self) -> Phase:
        """目前的遊戲階段（唯讀），和最近一次回覆的 reply.phase 相同。網頁版的房間用它決定輸入要交給誰。"""
        return self._phase

    @property
    def progress(self) -> str:
        """send() 執行中時，目前在做什麼（例如「規劃故事大綱」）；外殼可以在另一個執行緒讀取。"""
        return ""

    @property
    def draft(self) -> str:
        """send() 執行中時，AI 正在寫的劇情（串流中目前收到的部分）；外殼可以在另一個執行緒讀取。"""
        return ""

    def set_api_key(self, api_key: str) -> None:
        raise NotImplementedError

    def start(self) -> Reply:
        """第一個回覆：同一組玩家有沒結束的存檔就問要不要繼續，否則開新局。"""
        state = load(self.save_path, self.state_class)
        if state and not state.game_over and sorted(state.names) == sorted(self._players):  # 順序不同也是同一組人
            self.state, self._phase = state, "ask_continue"
            self._loaded()
            return self._reply(choices=CONTINUE_CHOICES, notice=UI["found_save"].format(turn=state.turn, premise=state.premise))
        return self._new_game()

    def action_for(self, text: str) -> str | None:
        """這句輸入在遊戲中代表的行動（例如「2」→ 第二個選項），讓外殼可以在等待回覆前先顯示。
        不是行動（指令、空白、不在遊戲中）時回傳 None。"""
        raw = text.strip()
        if self._phase != "playing" or not raw:
            return None
        if raw == "/timeout":
            return TIMEOUT_ACTION
        if raw == "/away":
            return AWAY_ACTION
        return self._action(raw, self._actor())

    def send(self, text: str) -> Reply:
        """送出一句輸入，拿回覆。可能會呼叫 AI，所以會花幾秒。"""
        raw = text.strip()
        if raw == "/help":
            return self._reply(info=(UI["help_title"], self._help()), **self._screen())
        if raw == "/state":
            if self.state is None:
                return self._reply(notice=UI["no_story_yet"], **self._screen())
            return self._reply(info=(UI["memory_title"], self._memory()), **self._screen())
        handler = {
            "ask_continue": self._on_ask_continue,
            self.setup_phase: self._on_setup,
            "playing": self._on_playing,
            "confirm_restart": self._on_confirm_restart,
            "ending": self._on_ending,
            "ended": self._on_ended,
        }[self._phase]
        return handler(raw)

    def send_as(self, name: str, text: str) -> Reply:
        """以某位玩家的身分送出輸入，不用照隊伍順序。遊戲中以外的階段（前提、確認……）等同 send()。"""
        if self._phase == "playing" and self._is_action(text.strip()):  # 行動才要檢查
            if name not in self._active():
                return self._reply(notice=UI["character_fallen"], **self._screen())
            if name in self.pending:
                return self._reply(notice=UI["already_acted"], **self._screen())
        self._as = name
        try:
            return self.send(text)
        finally:
            self._as = None

    def view(self, name: str, reply: Reply | None = None) -> Reply:
        """某位玩家眼中的畫面：actor 與 choices 換成這位玩家的（已經行動或出局的人沒有選項）。
        給了 reply 就沿用它的其他欄位，否則是目前這一回合的畫面（重新連線時用）。"""
        if reply is None:
            reply = self._reply(**self._screen())
            if self._phase == "playing":
                reply = replace(reply, **self._replay())
        if self._phase != "playing":
            mine = replace(reply, actor="", choices=[] if reply.actor else reply.choices)
        else:
            mine = replace(reply, **self._screen_for(name if name in self.waiting() else None))
        mine.text = self._render(mine)
        return mine

    def waiting(self) -> list[str]:
        """這回合還沒行動的玩家名字，依隊伍順序。"""
        if self.state is None or self._phase != "playing":
            return []
        return [n for n in self._active() if n not in self.pending]

    # ---------- 各階段 ----------

    def _on_ask_continue(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONTINUE_CHOICES)
        if answer == CONTINUE_CHOICES[0] or raw == "/continue":
            return self._resume()
        if answer == CONTINUE_CHOICES[1] or raw in ("/new", "/restart"):
            return self._new_game()
        return self._reply(choices=CONTINUE_CHOICES, notice=UI["answer_continue"])

    def _on_playing(self, raw: str) -> Reply:
        if raw == "/restart":
            self._phase = "confirm_restart"
            return self._reply(choices=CONFIRM_CHOICES, notice=UI["confirm_restart"])
        action = self.action_for(raw)
        if action is None:
            notice = UI["unknown_command"].format(command=raw) if raw else UI["enter_action"]
            return self._reply(notice=notice, **self._screen())
        return self._take_action(action, timeout=raw == "/timeout")

    def _take_action(self, action: str, timeout: bool) -> Reply:
        """記下這位玩家的行動；所有人都行動後才推進一回合。時間到時，還沒行動的人都算遲疑。"""
        if timeout:
            for name in self.waiting():
                self.pending[name] = action
        else:
            actor = self._actor()
            if actor is None:
                raise ValueError("好幾位玩家時，行動要用 send_as(名字, 文字) 送，才知道是誰的行動")
            self.pending[actor] = action
            if self.waiting():
                return self._reply(**self._screen())  # 還在等其他人：畫面上誰還沒行動由外殼用 waiting() 顯示
        actions = {n: self.pending[n] for n in self._players if n in self.pending}
        try:
            reply = self._play_round(actions)
        except FAILURES as e:
            self.state = load(self.save_path, self.state_class) or self.state  # 可能已經改了一半，從存檔還原
            # 撤回這回合所有的行動，大家重新選擇。只撤回最後一個人不夠：時間到或替離線的人自動填入的行動失敗時，
            # 會變成每個人都「已行動」卻沒有人能重送，整局卡住
            self.pending = {}
            return self._failed(e, lambda **kw: self._reply(**self._screen(), **kw), hint=UI["failed_turn"])
        self.pending = {}
        return reply

    def _on_confirm_restart(self, raw: str) -> Reply:
        answer = pick_choice(raw, CONFIRM_CHOICES)
        if answer == CONFIRM_CHOICES[0]:
            return self._new_game()
        if answer == CONFIRM_CHOICES[1]:
            self._phase = "playing"
            return self._reply(**self._screen())
        return self._reply(choices=CONFIRM_CHOICES, notice=UI["answer_confirm"])

    def _on_ended(self, raw: str) -> Reply:
        if pick_choice(raw, PLAY_AGAIN_CHOICES) or raw in ("/new", "/restart"):
            return self._new_game()
        return self._reply(choices=PLAY_AGAIN_CHOICES, notice=UI["answer_play_again"])

    # ---------- 共用 ----------

    def _resume(self) -> Reply:
        self._phase = "playing"
        self.pending = {}
        return self._reply(notice=UI["resumed"].format(premise=self.state.premise), **self._replay(), **self._screen())

    def _actor(self) -> str | None:
        """這句輸入是誰的：send_as() 指定的玩家；只有一位玩家時就是他。已經行動或出局了就沒有。"""
        if self.state is None:
            return None
        name = self._as if self._as is not None else (self._players[0] if len(self._players) == 1 else None)
        return name if name in self.waiting() else None

    def _screen(self) -> dict:
        """遊戲中畫面的固定部分：送出輸入的那位玩家（只有一位時就是他）的選項，以及限時。"""
        return self._screen_for(self._actor() if self._phase == "playing" else None)

    def _screen_for(self, actor: str | None) -> dict:
        """某位玩家（還沒行動時）的選項與限時；actor 是 None 時沒有選項。"""
        if self.state is None or self._phase not in ("playing", "ending"):
            return {}
        return {"actor": actor or "", "choices": self._choices(actor) if actor else [], "time_limit": self._time_limit()}

    def _failed(self, e: Exception, retry_screen, hint: str = "") -> Reply:
        """AI 呼叫失敗：留在原本的階段，讓外殼決定要不要換 key 後重送。"""
        if is_key_error(e):
            return retry_screen(error="api_key", notice=UI["key_invalid"])
        return retry_screen(error="api", notice=UI["failed"].format(hint=hint, error=str(e)[:300]))

    def _reply(self, **fields) -> Reply:
        in_game = self.state is not None and self._phase != self.setup_phase  # 有一局在進行（等開新局時還沒有）
        reply = Reply(phase=self._phase, **(self._status() if in_game else {"timed": self._next_timed()}), **fields)
        reply.text = self._render(reply)
        return reply

    def _save(self) -> None:
        save(self.state, self.save_path)

    # ---------- 子類別提供 ----------

    def _new_game(self) -> Reply:
        """開新局（沒有存檔、選了開新遊戲、確認重新開始、再玩一次）：回覆 setup_phase 的畫面。"""
        raise NotImplementedError

    def _on_setup(self, raw: str) -> Reply:
        """setup_phase 時的輸入。"""
        raise NotImplementedError

    def _play_round(self, actions: dict[str, str]) -> Reply:
        """大家都行動了：推進一回合並存檔。失敗時丟出 FAILURES 裡的錯誤，這裡會還原並撤回所有行動。"""
        raise NotImplementedError

    def _on_ending(self, raw: str) -> Reply:
        """剛結束後的下一次輸入：整理結局，回覆 ended。"""
        raise NotImplementedError

    def _active(self) -> list[str]:
        """這一局還在場上、每回合要行動的玩家（冒險裡倒下的角色不算）。"""
        return list(self._players)

    def _is_action(self, raw: str) -> bool:
        """這句輸入是不是遊戲中的行動（要檢查有沒有已經行動）。"""
        return not raw.startswith("/") or raw == "/away"

    def _action(self, raw: str, actor: str | None) -> str | None:
        """遊戲中的輸入代表的行動；不是行動時 None。/timeout、/away 已經處理過了。"""
        raise NotImplementedError

    def _choices(self, name: str) -> list[str]:
        """這位玩家這回合的選項。"""
        return []

    def _time_limit(self) -> int:
        return 0

    def _status(self) -> dict:
        """一局進行中時，回覆裡的 turn、timed、characters。"""
        raise NotImplementedError

    def _next_timed(self) -> bool:
        """還沒開始時，開新局會用的模式。"""
        return False

    def _replay(self) -> dict:
        """讀檔、重新連線時要重新顯示的內容：narration、resumed、history……"""
        raise NotImplementedError

    def _loaded(self) -> None:
        """找到可以接續的存檔時（self.state 已經換成存檔）。"""

    def _help(self) -> str:
        return UI["help"]

    def _memory(self) -> str:
        """/state 顯示的內容。"""
        raise NotImplementedError

    def _render(self, reply: Reply) -> str:
        """純文字版的整段回覆（Reply.text）。"""
        raise NotImplementedError

