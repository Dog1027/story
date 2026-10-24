"""預覽送給 AI 的完整提示詞：用範例情境把每一種 AI 呼叫的提示詞組出來印出，不會呼叫 AI、不花錢。

改了 story/prompts/ 的檔案之後，用這個看拼起來的樣子：

    just prompts              列出所有情境
    just prompts turn         只看「一般回合」
    just prompts --party      多人模式的情境
    just prompts --genre 克蘇魯 opening   換一個題材包

範例的故事內容在 story/samples/語言.md（不是提示詞，只是讓預覽看起來像真的一局）。
"""

import random
import sys
from pathlib import Path
from types import SimpleNamespace

from story.core import prompts
from story.core.engine import ACT_TURNS, MIN_ACT_TURNS, TARGET_TURNS, Engine
from story.core.genres import load_genres
from story.core.models import SCHEMA, Act, Character, Condition, GameState, StoryArc, Turn
from story.core.party import PartyEngine

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SAMPLE = prompts.sections(prompts.LANGUAGE, SAMPLES_DIR)  # 這個語言的範例故事（story/samples/語言.md）


def items(name: str) -> list[list[str]]:
    """範例裡一行一項的段落；每一項用 | 分成幾個欄位。"""
    return [[field.strip() for field in item.split("|")] for item in prompts.items(SAMPLE[name])]


def listed(name: str) -> list[str]:
    return [item[0] for item in items(name)]


def conditions(name: str) -> list[Condition]:
    return [Condition(name=n, kind=kind, severity=severity) for n, kind, severity in items(name)]


ARC = StoryArc(
    goal=SAMPLE["goal"],
    twist=SAMPLE["twist"],
    clues=listed("clues"),
    acts=[Act(name=name, milestone=milestone) for name, milestone in items("acts")],
    endings=listed("endings"),
)
HISTORY = [Turn(narration=narration, action=action) for narration, action in items("history")]
PREMISE = SAMPLE["premise"]


def sample_state(party: bool, genre: str, **fields) -> GameState:
    state = GameState(
        premise=PREMISE,
        genre=genre,
        turn=8,
        minutes=22 * 60,
        arc=ARC,
        act=1,
        act_turns=3,
        recent=list(HISTORY),
        key_events=listed("key_events"),
        flags=listed("flags"),
        current_narration=SAMPLE["narration"],
    )
    wounds = conditions("wounds")
    if party:
        players = items("players")
        state.party = [Character(name=name, inventory=[item]) for name, item in players]
        state.party[0].conditions = wounds
    else:
        state.conditions, state.inventory = wounds, listed("inventory")
    for key, value in fields.items():
        setattr(state, key, value)
    return state


def scenarios(engine: Engine, party: bool, genre: str) -> dict[str, tuple[str, str]]:
    """{代號: (說明, 提示詞)}"""
    state = lambda **fields: sample_state(party, genre, **fields)  # noqa: E731
    action = dict(items("party_actions")) if party else SAMPLE["action"]
    opening = state(turn=0, minutes=None, recent=[], key_events=[], flags=[], act=0, act_turns=0)
    if party:
        dying = state(current_narration=SAMPLE["party_fall"])
        death = ("傷重倒下", engine.deaths_prompt(dying, [dying.party[0].name]))
    else:
        death = ("傷重死亡", engine.death_prompt(state(current_narration=SAMPLE["fall"])))
    events = [f"{SAMPLE['event']} {i}" for i in range(10)]
    long_story = state(turn=40, recent=HISTORY * 40, key_events=events, summary=SAMPLE["summary"])
    return {
        "system": ("寫作與遊戲規則（system prompt，每次寫劇情都會送出）", engine.system_prompt),
        "schema": ("回傳格式的欄位說明（跟著回傳格式送出）", "\n".join(f"{key}：{text}" for key, text in SCHEMA.items())),
        "genre": ("題材選「自動」時，挑題材", engine.genre_prompt(opening)),
        "arc": ("規劃隱藏的大綱", engine.arc_prompt(opening)),
        "opening": ("開場", engine.turn_prompt(opening, None)),
        "turn": ("一般回合（第二幕）", engine.turn_prompt(state(), action)),
        "early": (f"一幕剛開始（還沒演滿 {MIN_ACT_TURNS} 回合）", engine.turn_prompt(state(act_turns=0), action)),
        "dragging": (f"這一幕拖太久（超過 {ACT_TURNS} 回合）", engine.turn_prompt(state(act_turns=ACT_TURNS), action)),
        "reveal": ("第三幕：揭露隱藏的真相", engine.turn_prompt(state(act=2, turn=16), action)),
        "final": (f"最後一幕，超過預定的 {TARGET_TURNS} 回合", engine.turn_prompt(state(act=3, turn=TARGET_TURNS), action)),
        "timed": ("限時模式", engine.turn_prompt(state(timed_mode=True), action)),
        "death": death,
        "epilogue": ("尾聲", engine.epilogue_prompt(state(act=3, turn=26))),
        "premise": ("幫我想", engine.premise_prompt(genre=genre)),
        "compaction": ("記憶壓縮（劇情紀錄太長時）", engine.compaction_prompt(long_story)),
    }


def main(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    party = "--party" in args
    genres = load_genres()[0]
    genre = ""  # 預設不套用題材，畫面比較短；要看題材包的指引時加 --genre
    if "--genre" in args:
        genre = args[args.index("--genre") + 1]
        if genre not in genres:
            sys.exit(f"沒有「{genre}」這個題材包。可以用：{'、'.join(genres)}")
    names = [a for a in args if not a.startswith("--") and a != genre]
    random.seed(0)  # 隨機抽的轉折靈感、幫我想的題材每次都一樣，方便比較改之前與之後
    engine = (PartyEngine if party else Engine)(client=SimpleNamespace(), genres=genres)
    found = scenarios(engine, party, genre)
    unknown = [n for n in names if n not in found]
    if unknown:
        sys.exit(f"沒有這個情境：{'、'.join(unknown)}。可以用：{'、'.join(found)}")
    mode = "多人模式" if party else "單人模式"
    for name in names or found:
        title, text = found[name]
        print(f"\n{'═' * 60}\n{name}：{title}（{mode}，題材：{genre or '不套用'}）\n{'═' * 60}\n{text}")


if __name__ == "__main__":
    main()
