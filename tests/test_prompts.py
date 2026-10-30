"""Text files (each layer's prompts/<lang>/ and ui/<lang>/): correct format, every section readable, no unfilled variables after combining."""

import re
from pathlib import Path

from conftest import ARC, HERO, beat, make_engine, solo

from story.core import prompts
from story.games.adventure.models import GameState
from story.games.adventure.rules import ACT_TURNS
from story.games.adventure.text import TEXT

PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def test_every_prompt_file_loads():
    from story.games.soup.text import TEXT as SOUP

    assert TEXT.load("system").startswith("你是")
    for texts, names in ((TEXT, ("context", "turn", "progress", "plan", "premise", "memory", "schema", "eval", "vocab")), (SOUP, ("soup", "schema", "vocab"))):
        for name in names:
            parts = texts.sections(name)
            assert parts and all(body.strip() for body in parts.values()), name


def test_vocabulary_has_a_word_for_every_code():
    """vocab.md: every code has a word in this language, with no repeats within a category (the AI returns words, so the program must be able to map them back to codes)."""
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
    """Prompts built for various scenarios: every variable is filled in (no {name} left in text sent to the AI)."""
    for act, act_turns in ((0, 0), (1, ACT_TURNS), (2, 6), (3, 2)):
        engine, gemini = make_engine(beat())
        engine.play_turn(solo(premise="x", turn=8, minutes=0, arc=ARC, act=act, act_turns=act_turns, timed_mode=True), {HERO: "往上爬"})
        assert not PLACEHOLDER.search(gemini.prompts[-1])
    engine, gemini = make_engine(beat())
    engine.start(solo(premise="燈塔"))
    assert all(not PLACEHOLDER.search(p) for p in gemini.prompts)


def test_epilogue_prompt_is_story_content_plus_its_own_instruction():
    """The epilogue isn't cut from a normal turn's prompt: it carries none of the "this turn" instructions (opening, focus)."""
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
    """just prompts: every scenario builds with one character, two characters, and a genre pack, with no unfilled variables."""
    from story.games.adventure.preview import main

    for args in ([], ["--players", "2"], ["--genre", "武俠"]):
        main(args)
        out = capsys.readouterr().out
        assert out.count("═" * 60) == 30 and not PLACEHOLDER.search(out), args


def test_every_ui_text_used_in_the_code_exists():
    """Every interface text the code uses exists in some layer's ui/<lang>/: a misspelled name or a section missed in translation is pointed out."""
    src = Path(prompts.__file__).resolve().parent.parent
    texts = {key for folder in text_folders("ui") for f in (folder / "zh-TW").glob("*.md") for key in prompts.sections(f.stem, f.parent)}
    used = set()
    for path in [*src.rglob("*.py"), src / "shells/web/static/app.js", src / "shells/web/static/index.html"]:
        code = path.read_text(encoding="utf-8")
        used |= set(re.findall(r"\b(?:UI|DIALOGS)\[[\"'](\w+)[\"']\]", code))
        used |= set(re.findall(r"\bt\(\"(\w+)\"", code)) | set(re.findall(r"\bT\.(\w+)", code))
        used |= set(re.findall(r"\{\{([a-z_]+)\}\}", code)) - {"texts"}
    assert used and not used - texts, sorted(used - texts)


def test_web_page_is_filled_with_the_language_texts():
    from story.shells.web.server import PAGE

    assert "{{" not in PAGE and 'lang="zh-Hant"' in PAGE and "const T = {" in PAGE


def test_every_language_has_the_same_files_and_sections():
    """Every language (each layer's prompts/<lang>/, ui/<lang>/) has a full set of files and sections with the same names and the same variables."""
    folders = text_folders("prompts") + text_folders("ui")
    assert len(folders) == 6, folders  # The core's and shells' ui, the adventure's and turtle soup's prompts and ui
    for folder in folders:
        base = folder / "zh-TW"
        for lang in (p for p in folder.iterdir() if p.is_dir() and p != base):
            assert sorted(f.name for f in lang.glob("*.md")) == sorted(f.name for f in base.glob("*.md")), lang
            for f in base.glob("*.md"):
                ours, theirs = prompts.sections(f.stem, base), prompts.sections(f.stem, lang)
                assert ours.keys() == theirs.keys(), (lang.name, f.name, ours.keys() ^ theirs.keys())
                for key in ours:
                    def variables(text: str) -> set[str]:
                        return set(re.findall(r"\{(\w+)[:}]", text))

                    assert variables(ours[key]) == variables(theirs[key]), (lang.name, f.name, key)
    for samples in text_folders("samples"):  # Samples (just prompts, just eval): one per language, with the same sections
        base = prompts.sections("zh-TW", samples).keys()
        for f in samples.glob("*.md"):
            assert prompts.sections(f.stem, samples).keys() == base, f.name


def text_folders(kind: str) -> list[Path]:
    """Every text folder named kind (prompts, ui, samples) under src/story."""
    root = Path(prompts.__file__).resolve().parent.parent
    return sorted(p for p in root.rglob(kind) if p.is_dir() and "__pycache__" not in p.parts)


def test_text_length_counts_chinese_characters_and_english_words():
    assert prompts.text_length("你好，世界。") == 6
    assert prompts.text_length("a torn right arm") == 4
    assert prompts.clip("a badly torn right arm", 3) == "a badly torn" and prompts.clip("右臂撕裂傷", 2) == "右臂"
