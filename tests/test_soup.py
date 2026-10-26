"""海龜湯：出題、每回合大家同時提問或猜湯底、說中所有關鍵點才算解開（同一回合可以一起獲勝）、放棄、讀檔，
以及裁判（真的 SoupJudge 配假的 Gemini）、題庫。不會呼叫真的 AI。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from story.core import prompts
from story.core.soup import SoupCore
from story.core.soup.judge import SoupJudge
from conftest import AI_PUZZLE, PUZZLE, FakeJudge

from story.core.soup.models import Judgement, Move, PuzzleCheck, PuzzleDraft, Ruling, SoupState
from story.core.soup.puzzles import BUILTIN_DIR, load_puzzles

def soup(isolated, players=("阿明",), judge=None, puzzles=(PUZZLE,)) -> SoupCore:
    return SoupCore("test", list(players), save_path=isolated / "soup.json", judge=judge or FakeJudge(), puzzles=list(puzzles))


def started(isolated, **kw) -> tuple[SoupCore, object]:
    core = soup(isolated, **kw)
    assert core.start().phase == "ask_puzzle"
    return core, core.send("1")  # 從題庫抽一題


def test_one_player_asks_then_solves_it(isolated):
    core, reply = started(isolated)
    assert reply.phase == "playing" and "【空號】" in reply.narration and "他每晚撥同一個空號。" in reply.narration
    assert reply.choices == ["提問", "猜湯底", "放棄"] and [m.command for m in reply.inputs] == ["/ask", "/guess", "/give_up"]
    assert reply.characters[0].conditions == [("問 0", "muted"), ("說中 0/3", "muted")] and reply.turn == 1

    reply = core.send("/ask 他死了嗎")
    assert reply.narration == "你 問：他死了嗎\n→ 是" and reply.phase == "playing"  # 一個人玩寫「你」
    reply = core.send("/guess 跟母親有關")
    assert "說中 1/3 個關鍵點" in reply.narration and reply.characters[0].conditions[1] == ("說中 1/3", "good")
    reply = core.send("/guess 全部說出來")
    assert reply.phase == "ending" and "說中了所有關鍵點" in reply.narration
    ended = core.send("")
    assert ended.phase == "ended" and ended.ending.title == "你 解開了謎題" and ended.ending.epilogue == "那是母親錄的語音。"
    assert ended.ending.reveal == "按 Enter 看湯底"
    assert "共 3 回合，問了 1 個問題，猜了 2 次" in ended.ending.record and "- 母親過世了" in ended.ending.record
    assert core.send("1").phase == "ask_puzzle"  # 再玩一次


def test_typing_without_choosing_is_a_question_and_choices_switch_the_way(isolated):
    core, _ = started(isolated)
    assert core.action_for("他死了嗎") == "/ask 他死了嗎"
    assert core.action_for("2") is None and core.send("2").notice  # 選了「猜湯底」還要寫內容
    assert core.action_for("3") == "/give_up"
    assert core.send("/guess   ").notice  # 沒寫內容


def test_everyone_acts_at_once_and_sees_everything(isolated):
    judge = FakeJudge()
    core, _ = started(isolated, players=("阿明", "小華"), judge=judge)
    mine = core.send_as("阿明", "/ask 有人死了嗎")
    assert mine.narration == "" and mine.inputs == [] and core.waiting() == ["小華"]  # 行動完：沒有選項，等其他人
    assert core.view("小華").inputs and core.view("小華").choices == ["提問", "猜湯底", "放棄"]
    reply = core.send_as("小華", "/guess 跟電話有關")
    assert judge.rounds == [[("阿明", "ask", "有人死了嗎"), ("小華", "guess", "跟電話有關")]]  # 一次判斷整回合
    assert reply.narration == "阿明 問：有人死了嗎\n→ 是\n\n小華 猜：跟電話有關\n→ 說中 1/3 個關鍵點"
    assert [s.name for s in reply.characters] == ["阿明", "小華"]


def test_players_who_solve_it_in_the_same_round_win_together(isolated):
    core, _ = started(isolated, players=("阿明", "小華", "大雄"))
    core.send_as("阿明", "/guess 全部")
    core.send_as("小華", "/guess 全部都知道")
    reply = core.send_as("大雄", "/guess 只說中一點")
    assert reply.phase == "ending" and "阿明、小華 說中了所有關鍵點" in reply.narration
    assert core.send("").ending.title == "阿明、小華 同時解開了謎題"


def test_the_truth_is_revealed_only_when_everyone_gives_up_in_the_same_round(isolated):
    core, _ = started(isolated, players=("阿明", "小華"))
    core.send_as("阿明", "3")
    reply = core.send_as("小華", "/ask 是晚上嗎")
    assert reply.phase == "playing" and "阿明 選擇放棄" in reply.narration and "所有人都選放棄" in reply.narration
    core.send_as("阿明", "/give_up")
    reply = core.send_as("小華", "/give_up")
    assert reply.phase == "ending" and "公布湯底" in reply.narration
    assert core.send("").ending.title == "沒有人解開：湯底揭曉"


def test_a_failed_ruling_takes_back_the_whole_round(isolated):
    judge = FakeJudge()
    core, _ = started(isolated, players=("阿明", "小華"), judge=judge)
    judge.fail_with = RuntimeError("裁判當機")
    core.send_as("阿明", "/ask 一")
    reply = core.send_as("小華", "/ask 二")
    assert reply.error == "api" and core.waiting() == ["阿明", "小華"]  # 大家重新行動
    judge.fail_with = None
    core.send_as("阿明", "/ask 一")
    assert core.send_as("小華", "/ask 二").narration


def test_ai_puzzles_and_falling_back_to_the_bank(isolated):
    judge = FakeJudge(puzzle=AI_PUZZLE)
    core = soup(isolated, judge=judge)
    core.start()
    reply = core.send("2")
    assert "【AI 的題目】" in reply.narration and judge.avoided == ["空號"]  # 不要跟題庫的題目重複

    for made, note in ((None, "不夠合理"), (RuntimeError("額度用完"), "額度用完")):
        (isolated / "soup.json").unlink()  # 上一局的存檔：不然會先問要不要繼續
        core = soup(isolated, judge=FakeJudge(puzzle=made))
        core.start()
        reply = core.send("2")
        assert reply.phase == "playing" and note in reply.narration and "【空號】" in reply.narration


def test_continuing_a_saved_soup_shows_the_scenario_and_earlier_rounds(isolated):
    core, _ = started(isolated)
    core.send("/ask 他死了嗎")
    again = soup(isolated)
    found = again.start()
    assert found.phase == "ask_continue" and "空號" in found.notice
    reply = again.send("1")
    assert reply.resumed and "【空號】" in reply.narration and reply.history == [("你 問：他死了嗎\n→ 是", "")]
    assert "第 1 回" in again.send("/state").info[1]


def test_reply_inputs_survive_the_trip_to_the_browser(isolated):
    from story.core import Reply

    _, reply = started(isolated)
    assert Reply.from_dict(reply.to_dict()).inputs == reply.inputs


# ---------- 裁判：真的 SoupJudge，假的 Gemini ----------


class FakeClient:
    """假的 Gemini：依 response_schema 依序回傳排好的結果。"""

    def __init__(self, *results):
        self.results, self.prompts = list(results), []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        self.prompts.append(contents)
        return SimpleNamespace(parsed=self.results.pop(0))


def test_judge_counts_only_real_key_points(isolated):
    client = FakeClient(Judgement(rulings=[Ruling(move=1, answer="是也不是", matched=[]), Ruling(move=2, answer="無關", matched=[1, 1, 3, 9])]))
    judge = SoupJudge(client=client, log_path=isolated / "log.jsonl")
    state = SoupState(puzzle=PUZZLE, players=["阿明", "小華"])
    moves = [Move(name="阿明", kind="ask", text="是電話嗎"), Move(name="小華", kind="guess", text="母親")]
    judge.judge(state, moves)
    assert moves[0].answer == "partly" and moves[1].hit == 2  # 重複的、不存在的編號都不算
    assert "那是母親錄的語音。" in client.prompts[0] and "1. 阿明 提問：是電話嗎" in client.prompts[0]


def test_judge_missing_a_move_is_a_failure(isolated):
    judge = SoupJudge(client=FakeClient(Judgement(rulings=[])), log_path=isolated / "log.jsonl")
    with pytest.raises(RuntimeError):
        judge.judge(SoupState(puzzle=PUZZLE, players=["阿明"]), [Move(name="阿明", kind="ask", text="?")])


def test_ai_puzzles_are_checked_and_rewritten_once(isolated):
    draft = PuzzleDraft(title="題", surface="湯面", truth="湯底", key_points=["一", "二"])
    client = FakeClient(draft, PuzzleCheck(ok=False, problem="湯底太牽強"), draft, PuzzleCheck(ok=True, problem=""))
    puzzle = SoupJudge(client=client, log_path=isolated / "log.jsonl").make_puzzle(avoid=["空號"])
    assert puzzle.title == "題" and "湯底太牽強" in client.prompts[2] and "- 空號" in client.prompts[0]
    client = FakeClient(draft, PuzzleCheck(ok=False, problem="x"), draft, PuzzleCheck(ok=False, problem="y"))
    assert SoupJudge(client=client, log_path=isolated / "log.jsonl").make_puzzle(avoid=[]) is None


# ---------- 題庫 ----------


def test_every_language_has_the_same_puzzles():
    root = BUILTIN_DIR.parent
    base = sorted(p.name for p in (root / "zh-TW").glob("*.md"))
    assert len(base) >= 8
    for lang in (p for p in root.iterdir() if p.is_dir()):
        assert sorted(p.name for p in lang.glob("*.md")) == base, lang.name
        puzzles, problems = load_puzzles([lang])
        assert len(puzzles) == len(base) and not problems, (lang.name, problems)
        for f in lang.glob("*.md"):  # 關鍵點的個數也要一樣
            assert len(prompts.items(prompts.sections(f.stem, lang)["key_points"])) == len(
                prompts.items(prompts.sections(f.stem, root / "zh-TW")["key_points"])
            ), (lang.name, f.name)


def test_broken_puzzles_are_skipped_with_a_reason(tmp_path):
    (tmp_path / "ok.md").write_text("## title\n好\n## surface\n面\n## truth\n底\n## key_points\n- 一\n- 二\n", encoding="utf-8")
    (tmp_path / "bad.md").write_text("## title\n壞\n## surface\n面\n", encoding="utf-8")
    (tmp_path / "few.md").write_text("## title\n少\n## surface\n面\n## truth\n底\n## key_points\n- 一\n", encoding="utf-8")
    puzzles, problems = load_puzzles([tmp_path])
    assert [p.title for p in puzzles] == ["好"] and len(problems) == 2
    assert any("truth" in p for p in problems) and any("2-4" in p for p in problems)


def test_personal_puzzles_override_builtin_ones_with_the_same_title(tmp_path):
    (tmp_path / "mine.md").write_text("## title\n空號\n## surface\n我的版本\n## truth\n底\n## key_points\n- 一\n- 二\n", encoding="utf-8")
    puzzles, _ = load_puzzles([BUILTIN_DIR, tmp_path])
    assert next(p for p in puzzles if p.title == "空號").surface == "我的版本"
    assert Path(BUILTIN_DIR).name == "zh-TW"
