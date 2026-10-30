"""Genre packs: reading and checking the format, personal packs overriding built-in ones, the AI picking by premise, where they go in prompts, "suggest one" and the /genre command."""

from conftest import HERO, FakeEngine, beat, make_engine, solo

from story.games import AdventureCore
from story.games.adventure.game import GENRE_AUTO, GENRE_NONE
from story.games.adventure.genres import BUILTIN_DIR, MAX_GUIDE, load_genres
from story.games.adventure.records import DEFAULT_PREMISE


def write_genre(root, folder, name="武俠", description="江湖恩怨", guide="用古白話。", premises="", names="", twists=""):
    path = root / folder
    path.mkdir(parents=True)
    (path / "GENRE.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n\n{guide}\n", encoding="utf-8")
    if premises:
        (path / "premises.md").write_text(premises, encoding="utf-8")
    if names:
        (path / "names.md").write_text(names, encoding="utf-8")
    if twists:
        (path / "twists.md").write_text(twists, encoding="utf-8")
    return path


def pack(**fields):
    from story.games.adventure.genres import Genre

    base = dict(name="武俠", description="江湖恩怨", guide="用古白話，人物用名號稱呼。", premises=["你是鏢師。"], names="人名：沈青衣", twists=["師父才是元兇"])
    return {"武俠": Genre(**{**base, **fields})}


# ---------- Reading and checking ----------


def test_builtin_genres_are_all_valid():
    """Every built-in genre pack must pass the checks: this catches a format mistake when a built-in pack is edited."""
    genres, problems = load_genres([BUILTIN_DIR])
    assert problems == [] and len(genres) >= 3


def test_genre_folder_is_parsed(tmp_path):
    write_genre(tmp_path, "wuxia", premises="- 你是鏢師。\n- 你是捕快。\n", names="人名：沈青衣", twists="- 師父才是元兇\n\n* 秘笈是假的\n")
    genres, problems = load_genres([tmp_path])
    genre = genres["武俠"]
    assert problems == []
    assert genre.description == "江湖恩怨" and genre.guide == "用古白話。"
    assert genre.premises == ["你是鏢師。", "你是捕快。"] and genre.names == "人名：沈青衣"
    assert genre.twists == ["師父才是元兇", "秘笈是假的"]


def test_broken_genres_are_skipped_with_a_reason(tmp_path):
    (tmp_path / "沒有檔案").mkdir()
    write_genre(tmp_path, "沒有描述", name="甲", description="")
    write_genre(tmp_path, "太長", name="乙", guide="字" * (MAX_GUIDE + 1))
    bad = tmp_path / "沒有設定欄位"
    bad.mkdir()
    (bad / "GENRE.md").write_text("只有內文", encoding="utf-8")
    genres, problems = load_genres([tmp_path])
    assert genres == {}
    assert len(problems) == 4
    assert any("description" in p for p in problems) and any("超過" in p for p in problems)


def test_personal_genre_overrides_builtin_with_same_name(tmp_path):
    write_genre(tmp_path / "builtin", "武俠", guide="內建的指引")
    write_genre(tmp_path / "personal", "我的武俠", guide="自己改的指引")
    genres, _ = load_genres([tmp_path / "builtin", tmp_path / "personal"])
    assert genres["武俠"].guide == "自己改的指引"


# ---------- engine: how a genre gets into the prompts ----------


def test_chosen_genre_guide_sits_in_the_stable_part_of_the_prompt():
    """The guidance is fixed for the whole game and placed before the story log, so caching isn't affected; naming material is only given at the opening."""
    engine, gemini = make_engine(beat(), beat(), genres=pack())
    state = solo(premise="鏢局", genre="武俠")
    engine.start(state)
    arc_prompt, opening = gemini.prompts[0], gemini.prompts[1]
    assert "用古白話" in arc_prompt and "題材目錄" not in arc_prompt  # A genre is already chosen: the outline follows it, with no need to pick
    assert "# 轉折靈感" in arc_prompt and "師父才是元兇" in arc_prompt
    assert "命名素材" in opening and "沈青衣" in opening
    engine.act(state, {HERO: "上路"})
    prompt = gemini.prompts[-1]
    assert prompt.index("# 題材：武俠") < prompt.index("# 劇情紀錄")
    assert "命名素材" not in prompt


def test_auto_genre_is_picked_before_planning_the_arc():
    engine, gemini = make_engine(beat(), genre="武俠", genres=pack())
    state = solo(premise="鏢局", genre_pending=True)
    engine.start(state)
    pick, arc_prompt, opening = gemini.prompts
    assert "# 題材目錄\n- 武俠：江湖恩怨" in pick
    assert state.genre == "武俠" and not state.genre_pending
    assert "用古白話" in arc_prompt and "師父才是元兇" in arc_prompt  # Picked first, so the outline can use the guidance and twist ideas
    assert "用古白話" in opening


def test_auto_genre_not_in_catalog_means_no_genre():
    engine, gemini = make_engine(beat(), genre="太空歌劇", genres=pack())
    state = solo(premise="太空站", genre_pending=True)
    engine.start(state)
    assert state.genre == "" and not state.genre_pending
    assert "# 題材：" not in gemini.prompts[1] and "# 轉折靈感" not in gemini.prompts[1]


def test_suggest_premise_uses_the_genre_pack():
    engine, gemini = make_engine(genres=pack())
    engine.suggest_premise(genre="武俠")
    prompt = gemini.prompts[-1]
    assert "題材：武俠" in prompt and "題材說明：江湖恩怨" in prompt and "你是鏢師。" in prompt


# ---------- Core: the /genre command ----------


class GenreEngine(FakeEngine):
    genres = pack()


def test_genre_command_and_new_story_fields(isolated):
    core = AdventureCore("test", [HERO], engine=GenreEngine(), save_path=isolated / "save.json")
    reply = core.start()
    assert reply.form.genre == GENRE_AUTO and [v for v, _, _ in reply.form.genres] == [GENRE_AUTO, GENRE_NONE, "武俠"]
    assert reply.form.genres[2] == ("武俠", "題材：武俠", "江湖恩怨")  # The genre menu: value, text shown, description
    assert "沒有「太空」這個題材" in core.send("/genre 太空").notice
    assert core.send("/genre 武俠").form.genre == "武俠"
    core.send("鏢局的故事")
    assert core.state.genre == "武俠" and not core.state.genre_pending

    core.send("/restart")
    core.send("1")
    core.send(f"/genre {GENRE_NONE}")
    core.send("另一個故事")
    assert core.state.genre == "" and not core.state.genre_pending

    core.send("/restart")
    core.send("1")
    core.send(f"/genre {GENRE_AUTO}")
    core.send("第三個故事")
    assert core.state.genre_pending  # The AI picks one when planning the outline


# ---------- Random premises ----------


def two_packs():
    from story.games.adventure.genres import Genre

    return {
        "武俠": Genre(name="武俠", description="江湖", guide="古白話。", premises=["你是鏢師。", "你是捕快。"]),
        "克蘇魯": Genre(name="克蘇魯", description="恐怖", guide="暗示。", premises=["你收到舅舅的包裹。"]),
    }


class PackEngine(FakeEngine):
    genres = two_packs()


def test_first_new_story_draws_a_premise_from_the_packs(isolated):
    core = AdventureCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    reply = core.start()
    assert reply.form.default in ("你是鏢師。", "你是捕快。", "你收到舅舅的包裹。", DEFAULT_PREMISE)
    core.send("")  # Blank: start with the drawn one
    assert core.state.premise == reply.form.default


def test_random_draws_a_different_premise_and_genre_change_redraws(isolated):
    core = AdventureCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    reply = core.send("/genre 武俠")
    assert reply.form.default in ("你是鏢師。", "你是捕快。")  # Changing the genre: the drawn opening changes with it
    other = core.send("/random").form.default
    assert other in ("你是鏢師。", "你是捕快。") and other != reply.form.default  # Another one: never draws the same one
    assert core.send("/genre 克蘇魯").form.default == "你收到舅舅的包裹。"


def test_play_again_keeps_the_last_premise_unless_rerolled(isolated):
    core = AdventureCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    core.send("自己寫的前提")
    core.send("/restart")
    reply = core.send("1")
    assert reply.form.default == "自己寫的前提"  # Play again: keeps the last game's premise
    assert core.send("/genre 武俠").form.default == "自己寫的前提"  # Changing the genre doesn't replace it either
    assert core.send("/random").form.default in ("你是鏢師。", "你是捕快。")


def test_ai_suggestion_wins_over_drawn_premise(isolated):
    core = AdventureCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    assert core.send("/suggest").form.default == "你是月球礦坑的夜班工程師。"


def test_every_language_has_valid_genre_packs():
    """Every language's built-in genre packs (story/genres/<lang>/) pass the checks. English counts length in words, so the same limits fit too."""
    for folder in BUILTIN_DIR.parent.iterdir():
        genres, problems = load_genres([folder])
        assert genres and not problems, (folder.name, problems)
