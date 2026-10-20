"""網頁版的玩家：名字檢查與同名鎖定。"""

import pytest

from story.shells.players import InvalidName, Player, check_name


@pytest.mark.parametrize("raw, name", [("阿明", "阿明"), ("  Bob_2 ", "Bob_2"), ("小華-3", "小華-3")])
def test_valid_names(raw, name):
    assert check_name(raw) == name


@pytest.mark.parametrize("raw", ["", "   ", "../../etc/passwd", "a b", "a/b", "名" * 21])
def test_invalid_names(raw):
    with pytest.raises(InvalidName):
        check_name(raw)


def test_player_paths_are_inside_saves():
    p = Player("阿明")
    assert str(p.save_path) == "saves/阿明.json" and str(p.log_path) == "saves/阿明.log.jsonl"


def test_same_name_can_only_be_used_once():
    first, second = Player("阿明"), Player("阿明")
    assert first.acquire()
    assert not second.acquire()
    first.release()
    assert second.acquire()
    second.release()


def test_stale_lock_from_dead_process_is_taken_over(isolated):
    (isolated / "saves").mkdir()
    (isolated / "saves" / "小華.lock").write_text("999999999")
    assert Player("小華").acquire()
