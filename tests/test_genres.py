"""題材包：讀取與檢查格式、個人的覆蓋內建的、AI 依前提挑選、提示詞裡的位置、「幫我想」與 /genre 指令。"""

from conftest import ARC, HERO, FakeEngine, beat, make_engine, solo

from story.core import GENRE_AUTO, GENRE_NONE, StoryCore
from story.core.genres import BUILTIN_DIR, MAX_GUIDE, load_genres
from story.core.models import Turn
from story.core.records import DEFAULT_PREMISE


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
    from story.core.genres import Genre

    base = dict(name="武俠", description="江湖恩怨", guide="用古白話，人物用名號稱呼。", premises=["你是鏢師。"], names="人名：沈青衣", twists=["師父才是元兇"])
    return {"武俠": Genre(**{**base, **fields})}


# ---------- 讀取與檢查 ----------


def test_builtin_genres_are_all_valid():
    """內建的題材包都要通過檢查：改了內建題材包卻寫錯格式時，這裡會提醒。"""
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


# ---------- engine：題材怎麼進到提示詞 ----------


def test_chosen_genre_guide_sits_in_the_stable_part_of_the_prompt():
    """指引整局固定，放在劇情紀錄前面不影響快取；命名素材只在開場給。"""
    engine, gemini = make_engine(beat(), beat(), genres=pack())
    state = solo(premise="鏢局", genre="武俠")
    engine.start(state)
    arc_prompt, opening = gemini.prompts[0], gemini.prompts[1]
    assert "用古白話" in arc_prompt and "題材目錄" not in arc_prompt  # 已經指定題材：大綱照題材規劃，不用再挑
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
    assert "用古白話" in arc_prompt and "師父才是元兇" in arc_prompt  # 先挑好，大綱就能用上指引與轉折靈感
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


# ---------- 核心：/genre 指令 ----------


class GenreEngine(FakeEngine):
    genres = pack()


def test_genre_command_and_new_story_fields(isolated):
    core = StoryCore("test", [HERO], engine=GenreEngine(), save_path=isolated / "save.json")
    reply = core.start()
    assert reply.genre == GENRE_AUTO and reply.genres == [("武俠", "江湖恩怨")]
    assert "沒有「太空」這個題材" in core.send("/genre 太空").notice
    assert core.send("/genre 武俠").genre == "武俠"
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
    assert core.state.genre_pending  # 規劃大綱時由 AI 挑


# ---------- 隨機前提 ----------


def two_packs():
    from story.core.genres import Genre

    return {
        "武俠": Genre(name="武俠", description="江湖", guide="古白話。", premises=["你是鏢師。", "你是捕快。"]),
        "克蘇魯": Genre(name="克蘇魯", description="恐怖", guide="暗示。", premises=["你收到舅舅的包裹。"]),
    }


class PackEngine(FakeEngine):
    genres = two_packs()


def test_first_new_story_draws_a_premise_from_the_packs(isolated):
    core = StoryCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    reply = core.start()
    assert reply.premise_default in ("你是鏢師。", "你是捕快。", "你收到舅舅的包裹。", DEFAULT_PREMISE)
    core.send("")  # 留白：用抽到的那個開始
    assert core.state.premise == reply.premise_default


def test_random_draws_a_different_premise_and_genre_change_redraws(isolated):
    core = StoryCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    reply = core.send("/genre 武俠")
    assert reply.premise_default in ("你是鏢師。", "你是捕快。")  # 換題材：抽到的開頭跟著換
    other = core.send("/random").premise_default
    assert other in ("你是鏢師。", "你是捕快。") and other != reply.premise_default  # 換一個：不會抽到同一個
    assert core.send("/genre 克蘇魯").premise_default == "你收到舅舅的包裹。"


def test_play_again_keeps_the_last_premise_unless_rerolled(isolated):
    core = StoryCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    core.send("自己寫的前提")
    core.send("/restart")
    reply = core.send("1")
    assert reply.premise_default == "自己寫的前提"  # 再玩一次：延續上一局的前提
    assert core.send("/genre 武俠").premise_default == "自己寫的前提"  # 換題材也不換掉
    assert core.send("/random").premise_default in ("你是鏢師。", "你是捕快。")


def test_ai_suggestion_wins_over_drawn_premise(isolated):
    core = StoryCore("test", [HERO], engine=PackEngine(), save_path=isolated / "save.json")
    core.start()
    assert core.send("/suggest").premise_default == "你是月球礦坑的夜班工程師。"


def test_every_language_has_valid_genre_packs():
    """每種語言的內建題材包（story/genres/語言/）都通過檢查。英文用詞數算長度，同樣的上限也放得下。"""
    for folder in BUILTIN_DIR.parent.iterdir():
        genres, problems = load_genres([folder])
        assert genres and not problems, (folder.name, problems)
