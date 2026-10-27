"""文字檔（每一層的 prompts/語言/、ui/語言/）：格式正確、每段都讀得到、組合後沒有留下沒填的變數。"""

import re
from pathlib import Path

from conftest import ARC, HERO, beat, make_engine, solo

from story.core import prompts
from story.games.adventure.text import TEXT
from story.games.adventure.rules import ACT_TURNS
from story.games.adventure.models import GameState

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def test_every_prompt_file_loads():
    from story.games.soup.text import TEXT as SOUP

    assert TEXT.load("system").startswith("你是")
    for texts, names in ((TEXT, ("context", "turn", "progress", "plan", "premise", "memory", "schema", "eval", "vocab")), (SOUP, ("soup", "schema", "vocab"))):
        for name in names:
            parts = texts.sections(name)
            assert parts and all(body.strip() for body in parts.values()), name


def test_vocabulary_has_a_word_for_every_code():
    """vocab.md：每個代號都有這個語言的詞，同一類的詞不重複（AI 回傳詞，程式才換得回代號）。"""
    from typing import get_args

    from story.games.adventure.models import VOCAB as ADVENTURE
    from story.games.soup.models import VOCAB as SOUP

    for vocab in (ADVENTURE, SOUP):
        for category, codes in vocab.codes.items():
            found = [vocab.word(category, c) for c in get_args(codes)]
            assert len(set(found)) == len(found), category
            assert all(vocab.code(category, vocab.word(category, c)) == c for c in get_args(codes))


def test_comments_are_not_sent_to_the_ai():
    assert all("<!--" not in body for name in ("turn", "plan") for body in TEXT.sections(name).values())
    assert "<!--" not in TEXT.load("system")


def test_assembled_prompts_have_no_unfilled_variables():
    """各種情境組出來的提示詞：變數都填好了（{名稱} 沒有留在送給 AI 的文字裡）。"""
    for act, act_turns in ((0, 0), (1, ACT_TURNS), (2, 6), (3, 2)):
        engine, gemini = make_engine(beat())
        engine.act(solo(premise="x", turn=8, minutes=0, arc=ARC, act=act, act_turns=act_turns, timed_mode=True), {HERO: "往上爬"})
        assert not PLACEHOLDER.search(gemini.prompts[-1])
    engine, gemini = make_engine(beat())
    engine.start(solo(premise="燈塔"))
    assert all(not PLACEHOLDER.search(p) for p in gemini.prompts)


def test_epilogue_prompt_is_story_content_plus_its_own_instruction():
    """尾聲不是從一般回合的提示詞切開的：不會帶到「本回合」的指示（開場、焦點）。"""
    from conftest import pbeat, upd

    from story.games.adventure.models import Character

    engine, gemini = make_engine(pbeat(upd("阿明"), upd("小華")))
    state = GameState(premise="燈塔", turn=25, minutes=600, arc=ARC, act=3, current_narration="最後一段",
                      characters=[Character(name="阿明"), Character(name="小華")])
    engine.write_epilogue(state)
    prompt = gemini.prompts[-1]
    assert "# 焦點" not in prompt and "這是故事的開場" not in prompt
    assert prompt.index("# 遊戲狀態") < prompt.index("# 故事的最後一段")


def test_preview_shows_every_scenario_without_calling_the_ai(capsys):
    """just prompts：一位、兩位角色、套用題材包的每個情境都組得出來，沒有留下沒填的變數。"""
    from story.preview import main

    for args in ([], ["--players", "2"], ["--genre", "武俠"]):
        main(args)
        out = capsys.readouterr().out
        assert out.count("═" * 60) == 30 and not PLACEHOLDER.search(out), args


def test_every_ui_text_used_in_the_code_exists():
    """程式用到的介面文字都在某一層的 ui/語言/ 裡：寫錯名稱或翻譯時漏了一段，測試會指出是哪一個。"""
    src = Path(prompts.__file__).resolve().parent.parent
    texts = {key for folder in text_folders("ui") for f in (folder / "zh-TW").glob("*.md") for key in prompts.sections(f.stem, f.parent)}
    used = set()
    for path in [*src.rglob("*.py"), src / "shells/web/static/app.js", src / "shells/web/static/index.html"]:
        code = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"\b(?:UI|DIALOGS|TERMINAL)\[[\"'](\w+)[\"']\]", code))
        used |= set(re.findall(r"\bt\(\"(\w+)\"", code)) | set(re.findall(r"\bT\.(\w+)", code))
        used |= set(re.findall(r"\{\{([a-z_]+)\}\}", code)) - {"texts"}
    assert used and not used - texts, sorted(used - texts)


def test_web_page_is_filled_with_the_language_texts():
    from story.shells.web import PAGE

    assert "{{" not in PAGE and 'lang="zh-Hant"' in PAGE and "const T = {" in PAGE


def test_every_language_has_the_same_files_and_sections():
    """每種語言（每一層的 prompts/語言/、ui/語言/）都要有一整套同名的檔案與段落，變數也要一樣。"""
    folders = text_folders("prompts") + text_folders("ui")
    assert len(folders) == 6, folders  # 核心與外殼的 ui，冒險與海龜湯的 prompts、ui
    for folder in folders:
        base = folder / "zh-TW"
        for lang in (p for p in folder.iterdir() if p.is_dir() and p != base):
            assert sorted(f.name for f in lang.glob("*.md")) == sorted(f.name for f in base.glob("*.md")), lang
            for f in base.glob("*.md"):
                ours, theirs = prompts.sections(f.stem, base), prompts.sections(f.stem, lang)
                assert ours.keys() == theirs.keys(), (lang.name, f.name, ours.keys() ^ theirs.keys())
                for key in ours:
                    variables = lambda text: set(re.findall(r"\{(\w+)[:}]", text))  # noqa: E731
                    assert variables(ours[key]) == variables(theirs[key]), (lang.name, f.name, key)
    for samples in text_folders("samples"):  # 範例（just prompts、just eval）：每種語言一份，段落相同
        base = prompts.sections("zh-TW", samples).keys()
        for f in samples.glob("*.md"):
            assert prompts.sections(f.stem, samples).keys() == base, f.name


def text_folders(kind: str) -> list[Path]:
    """src/story 底下所有叫 kind（prompts、ui、samples）的文字資料夾。"""
    root = Path(prompts.__file__).resolve().parent.parent
    return sorted(p for p in root.rglob(kind) if p.is_dir() and "__pycache__" not in p.parts)


def test_text_length_counts_chinese_characters_and_english_words():
    assert prompts.text_length("你好，世界。") == 6
    assert prompts.text_length("a torn right arm") == 4
    assert prompts.clip("a badly torn right arm", 3) == "a badly torn" and prompts.clip("右臂撕裂傷", 2) == "右臂"
