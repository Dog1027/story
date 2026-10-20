"""存讀檔、回合變化、結局紀錄，以及舊存檔的相容性。"""

from story.core.models import Condition, GameState
from story.core.records import change_groups, ending_record, load, save, snapshot


def test_save_and_load_roundtrip(isolated):
    state = GameState(premise="x", turn=3, inventory=["油燈"], conditions=[Condition(name="擦傷", severity="輕")])
    save(state, isolated / "s.json")
    assert load(isolated / "s.json") == state


def test_load_missing_file_returns_none(isolated):
    assert load(isolated / "nope.json") is None


def test_old_save_formats_still_load():
    old = '{"premise": "舊存檔", "turn": 39, "hp": 40, "max_hp": 100, "conditions": ["驚魂未定"]}'
    state = GameState.model_validate_json(old)
    assert state.turn == 39
    assert state.conditions == [Condition(name="驚魂未定", kind="身體", severity="輕")]
    assert state.minutes is None and state.arc is None  # 之後由 AI 補上


def test_change_groups_use_tones_not_colors():
    before = snapshot(GameState(premise="x", inventory=["美工刀", "鑰匙"], conditions=[
        Condition(name="左肘擦傷", severity="輕"), Condition(name="驚魂未定", kind="精神", severity="中"),
        Condition(name="右腿扭傷", severity="中"),
    ]))
    after = GameState(premise="x", inventory=["鑰匙", "油燈"], conditions=[
        Condition(name="驚魂未定", kind="精神", severity="輕"), Condition(name="右腿扭傷", severity="重"),
        Condition(name="右臂撕裂傷", severity="重"),
    ])
    assert change_groups(before, after) == [
        ("新增", [("右臂撕裂傷（重）", "重")]),
        ("惡化", [("右腿扭傷（中→重）", "bad")]),
        ("好轉", [("驚魂未定（中→輕）", "good")]),
        ("痊癒", [("左肘擦傷", "good")]),
        ("獲得", [("油燈", "plain")]),
        ("失去", [("美工刀", "muted")]),
    ]


def test_no_changes_gives_empty_list():
    state = GameState(premise="x", inventory=["鑰匙"])
    assert change_groups(snapshot(state), state) == []


def test_ending_record_reveals_days_and_recent_events():
    state = GameState(premise="x", turn=12, minutes=3 * 24 * 60 + 60, key_events=[f"事件{i}" for i in range(8)])
    record = ending_record(state)
    assert "共 12 回合，歷時 4 天" in record
    assert "你走到了故事的盡頭" in record
    assert "事件7" in record and "事件2" not in record  # 只列最近 5 件


def test_ending_record_mentions_death():
    state = GameState(premise="x", conditions=[Condition(name="失血", severity="重"), Condition(name="骨折", severity="重")])
    assert "你在這趟旅程中倒下了" in ending_record(state)
