"""TeamGame: the flow every game shares. A toy game built only on the base class is the executable spec of what a game provides."""

from pydantic import BaseModel

from story.core.team import TeamGame


class ToyState(BaseModel):
    players: list[str]
    turn: int = 0
    game_over: bool = False

    @property
    def names(self) -> list[str]:
        return list(self.players)

    @property
    def premise(self) -> str:
        return "toy"


class ToyGame(TeamGame[ToyState]):
    """The smallest game: start with one choice, then every round just records everyone's actions."""

    title, busy_label, description = "Toy", "thinking", "a toy"
    state_class = ToyState
    timeout_action, away_action = "(time)", "(away)"

    def __init__(self, players, save_path):
        super().__init__(players, save_path)
        self.rounds: list[dict[str, str]] = []

    def _new_game(self):
        self._phase = "setup"
        return self._reply(choices=["go"])

    def _on_setup(self, raw):
        self.state, self._phase = ToyState(players=self.players), "playing"
        self._save()
        return self._reply(**self._screen())

    def _play_round(self, actions):
        self.rounds.append(actions)
        self.game.turn += 1
        self._save()
        return self._reply(narration=f"round {self.game.turn}", **self._screen())

    def _action(self, raw, actor):
        return None if raw.startswith("/") else raw

    def _status(self):
        return {"turn": self.game.turn, "timed": False, "characters": []}


def test_a_game_only_supplies_its_hooks_and_the_base_class_runs_the_team(isolated):
    game = ToyGame(["A", "B"], isolated / "toy.json")
    start = game.start()
    assert start.phase == "setup" and start.form is None and start.choices == ["go"]
    assert game.send("1").phase == "playing"
    game.send_as("B", "y")
    assert game.waiting() == ["A"] and game.rounds == []  # Waits for everyone
    reply = game.send_as("A", "x")
    assert game.rounds == [{"A": "x", "B": "y"}] and reply.narration == "round 1"  # Actions in team order, not the order sent
    assert game.waiting() == ["A", "B"]
