"""預覽送給 AI 的完整提示詞：用範例情境把每一種 AI 呼叫的提示詞組出來印出，不會呼叫 AI、不花錢。

改了 story/prompts/ 的檔案之後，用這個看拼起來的樣子：

    just prompts              列出所有情境
    just prompts turn         只看「一般回合」
    just prompts --party      多人模式的情境
    just prompts --genre 克蘇魯 opening   換一個題材包

範例的故事內容寫在這裡（不是提示詞，只是讓預覽看起來像真的一局）。
"""

import random
import sys
from types import SimpleNamespace

from story.core.engine import ACT_TURNS, MIN_ACT_TURNS, TARGET_TURNS, Engine
from story.core.genres import load_genres
from story.core.models import SCHEMA, Act, Character, Condition, GameState, StoryArc, Turn
from story.core.party import PartyEngine

ARC = StoryArc(
    goal="查出燈塔守夜人失蹤的原因",
    twist="守夜人沒有失蹤，他一直躲在燈塔底下的密室，守著一個不能讓任何人知道的秘密",
    clues=["燈塔的油燈每晚都有人添油", "密室入口的地板上有新鮮的泥腳印"],
    acts=[
        Act(name="暴風雨之夜", milestone="在燈塔裡找到守夜人留下的日誌"),
        Act(name="海上的燈號", milestone="解開日誌裡的燈號暗語"),
        Act(name="底下的密室", milestone="打開密室，揭露守夜人的秘密"),
        Act(name="黎明之前", milestone="決定要不要讓秘密公諸於世"),
    ],
    endings=["守住秘密，獨自離開小島", "把真相交給鎮上的人"],
)
HISTORY = [
    Turn(narration="暴風雨夜，你在燈塔的底層醒來，手裡握著一把生鏽的鑰匙。", action="往上爬，看看燈室有沒有人"),
    Turn(narration="燈室空無一人，油燈卻還亮著，桌上攤著一本被雨水打濕的日誌。", action="翻開日誌"),
]


PREMISE = "你是一名失憶的旅人，在暴風雨夜醒來，發現自己躺在一座廢棄燈塔的底層。"


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
        key_events=["發現守夜人的日誌"],
        flags=["燈塔的門被人從外面鎖上"],
        current_narration="日誌最後一頁寫著：「燈號三長一短，代表他們來了。」窗外，海上亮起了一盞燈。",
    )
    wounds = [Condition(name="右臂撕裂傷", kind="body", severity="moderate"), Condition(name="恐懼", kind="mind", severity="light")]
    if party:
        state.party = [Character(name="阿明", conditions=wounds, inventory=["油燈"]), Character(name="小華", inventory=["鑰匙"])]
    else:
        state.conditions, state.inventory = wounds, ["鑰匙", "油燈"]
    for key, value in fields.items():
        setattr(state, key, value)
    return state


def scenarios(engine: Engine, party: bool, genre: str) -> dict[str, tuple[str, str]]:
    """{代號: (說明, 提示詞)}"""
    state = lambda **fields: sample_state(party, genre, **fields)  # noqa: E731
    action = {"阿明": "照著日誌打出燈號回應", "小華": "躲在樓梯口觀察"} if party else "照著日誌打出燈號回應"
    opening = state(turn=0, minutes=None, recent=[], key_events=[], flags=[], act=0, act_turns=0)
    if party:
        dying = state(current_narration="阿明從樓梯摔了下去，重重撞在石牆上。")
        death = ("傷重倒下", engine.deaths_prompt(dying, ["阿明"]))
    else:
        death = ("傷重死亡", engine.death_prompt(state(current_narration="你從樓梯摔了下去，重重撞在石牆上。")))
    long_story = state(turn=40, recent=HISTORY * 40, key_events=[f"事件 {i}" for i in range(10)], summary="之前的摘要")
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
