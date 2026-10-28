"""Saving and loading, changes between turns, the ending record."""

from conftest import hero, solo

from story.core.saves import load, save
from story.games.adventure.models import Condition, GameState
from story.games.adventure.records import change_groups, ending_record, snapshot


def test_save_and_load_roundtrip(isolated):
    state = solo(turn=3, inventory=["油燈"], conditions=[Condition(name="擦傷", severity="light")])
    save(state, isolated / "s.json")
    assert load(isolated / "s.json", GameState) == state


def test_load_missing_file_returns_none(isolated):
    assert load(isolated / "nope.json", GameState) is None


def test_change_groups_use_tones_not_colors():
    before = snapshot(hero(solo(inventory=["美工刀", "鑰匙"], conditions=[
        Condition(name="左肘擦傷", severity="light"), Condition(name="驚魂未定", kind="mind", severity="moderate"),
        Condition(name="右腿扭傷", severity="moderate"),
    ])))
    after = hero(solo(inventory=["鑰匙", "油燈"], conditions=[
        Condition(name="驚魂未定", kind="mind", severity="light"), Condition(name="右腿扭傷", severity="severe"),
        Condition(name="右臂撕裂傷", severity="severe"),
    ]))
    assert change_groups(before, after) == [
        ("新增", [("右臂撕裂傷（重）", "severe")]),
        ("惡化", [("右腿扭傷（中→重）", "bad")]),
        ("好轉", [("驚魂未定（中→輕）", "good")]),
        ("痊癒", [("左肘擦傷", "good")]),
        ("獲得", [("油燈", "plain")]),
        ("失去", [("美工刀", "muted")]),
    ]


def test_no_changes_gives_empty_list():
    state = solo(inventory=["鑰匙"])
    assert change_groups(snapshot(hero(state)), hero(state)) == []


def test_ending_record_reveals_days_and_recent_events():
    state = solo(turn=12, minutes=3 * 24 * 60 + 60, key_events=[f"事件{i}" for i in range(8)])
    record = ending_record(state)
    assert "共 12 回合，歷時 4 天" in record
    assert "你走到了故事的盡頭" in record
    assert "事件7" in record and "事件2" not in record  # Only the latest 5


def test_ending_record_mentions_death():
    state = solo(conditions=[Condition(name="失血", severity="severe"), Condition(name="骨折", severity="severe")])
    hero(state).alive = False
    assert "你在這趟旅程中倒下了" in ending_record(state)
