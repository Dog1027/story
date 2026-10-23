"""提示詞檔案（story/prompts/）：格式正確、每段都讀得到、組合後沒有留下沒填的變數。"""

import re

from conftest import ARC, beat, make_engine

from story.core import prompts
from story.core.engine import ACT_TURNS
from story.core.models import GameState

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def test_every_prompt_file_loads():
    for name in ("system", "party_system"):
        assert prompts.load(name).startswith("你是")
    for name in ("context", "turn", "party_turn", "progress", "plan", "premise", "memory", "schema"):
        parts = prompts.sections(name)
        assert parts and all(body.strip() for body in parts.values()), name


def test_comments_are_not_sent_to_the_ai():
    assert all("<!--" not in body for name in ("turn", "plan") for body in prompts.sections(name).values())
    assert "<!--" not in prompts.load("system")


def test_assembled_prompts_have_no_unfilled_variables():
    """各種情境組出來的提示詞：變數都填好了（{名稱} 沒有留在送給 AI 的文字裡）。"""
    for act, act_turns in ((0, 0), (1, ACT_TURNS), (2, 6), (3, 2)):
        engine, gemini = make_engine(beat())
        engine.act(GameState(premise="x", turn=8, minutes=0, arc=ARC, act=act, act_turns=act_turns, timed_mode=True), "往上爬")
        assert not PLACEHOLDER.search(gemini.prompts[-1])
    engine, gemini = make_engine(beat())
    engine.start(GameState(premise="燈塔"))
    assert all(not PLACEHOLDER.search(p) for p in gemini.prompts)


def test_epilogue_prompt_is_story_content_plus_its_own_instruction():
    """尾聲不是從一般回合的提示詞切開的：不會帶到「本回合」的指示（開場、多人的焦點）。"""
    from conftest import pbeat, upd

    from story.core.models import Character
    from story.core.party import PartyEngine

    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華")), engine_class=PartyEngine)
    state = GameState(premise="燈塔", turn=25, minutes=600, arc=ARC, act=3, current_narration="最後一段",
                      party=[Character(name="阿明"), Character(name="小華")])
    engine.write_epilogue(state)
    prompt = gemini.prompts[-1]
    assert "# 焦點" not in prompt and "這是故事的開場" not in prompt
    assert prompt.index("# 隊伍") < prompt.index("# 故事的最後一段")


def test_preview_shows_every_scenario_without_calling_the_ai(capsys):
    """just prompts：單人、多人、套用題材包的每個情境都組得出來，沒有留下沒填的變數。"""
    from story.preview import main

    for args in ([], ["--party"], ["--genre", "武俠"]):
        main(args)
        out = capsys.readouterr().out
        assert out.count("═" * 60) == 30 and not PLACEHOLDER.search(out), args
