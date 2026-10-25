"""just eval：用假的 Gemini 跑一遍，確認情境組得起來、檢查與報告正常（真的評估要呼叫 API，不在測試裡）。"""

import json

import pytest
from conftest import FakeGemini, beat, cond

from story import evals


class JudgingGemini(FakeGemini):
    """會回答評審的假 Gemini：一律判定通過。"""

    def generate_content(self, model, contents, config):
        if getattr(config, "response_schema", None) is evals.Verdict:
            return type("Response", (), {"parsed": evals.Verdict(reason="沒問題", passed=True)})()
        return super().generate_content(model, contents, config)


def run(monkeypatch, capsys, args, *beats):
    monkeypatch.setattr(evals.settings, "api_key", lambda: "key")
    monkeypatch.setattr(evals, "RPM", 60_000)  # 測試不用等
    monkeypatch.setattr(evals, "new_client", lambda key: JudgingGemini(beats))
    evals.main(args)
    return capsys.readouterr().out


def test_agency_scenario_runs_checks_and_saves_results(monkeypatch, capsys, isolated):
    out = run(monkeypatch, capsys, ["agency", "--runs", "1"], beat(narration="燈" * 200, choices=["等", "走"]))
    assert "✓ 沒有替玩家做決定  1/1" in out and "通過 4/4 項檢查" in out
    record = json.loads(next((isolated / "eval_results").glob("*.jsonl")).read_text(encoding="utf-8"))
    assert record["scenario"] == "agency" and record["narration"] == "燈" * 200
    assert not (isolated / "story_log.jsonl").exists() and not (isolated / "save.json").exists()


def test_failed_checks_show_the_reason(monkeypatch, capsys):
    out = run(monkeypatch, capsys, ["reckless", "--runs", "1"], beat(narration="短", choices=["等"]))
    assert "✗ 魯莽的行動受了傷（傷勢總分至少加 2）  0/1" in out and "傷勢總分 2 → 2" in out
    assert "✗ 劇情 150-300 字  0/1" in out


def test_dying_scenario_passes_when_the_wound_is_fatal(monkeypatch, capsys):
    out = run(monkeypatch, capsys, ["dying", "--runs", "1"],
              beat(narration="刀落下。", conditions_changed=[cond("胸口刀傷", "重")]), beat(narration="你倒下了。"))
    assert "✓ 瀕死還冒險就喪命  1/1" in out


def test_every_genre_pack_has_a_tone_scenario():
    found = evals.scenarios(evals.load_genres()[0])
    assert {"opening", "early", "reveal", "agency", "reckless", "dying", "judge", "武俠"} <= set(found)


def test_unknown_scenario_lists_the_choices(monkeypatch, capsys):
    with pytest.raises(SystemExit, match="可以用：opening"):
        run(monkeypatch, capsys, ["nope"])


def test_throttle_waits_out_the_rate_limit_and_retries(monkeypatch):
    from google.genai import errors

    slept = []
    monkeypatch.setattr(evals.time, "sleep", slept.append)
    calls = []

    def send():
        calls.append(1)
        if len(calls) == 1:
            raise errors.ClientError(429, {"error": {"message": "Please retry in 12.5s."}})
        return "ok"

    assert evals.Throttle(60_000).call(send) == "ok" and len(calls) == 2 and 12.5 in slept


def test_judge_calibration_expects_bad_samples_to_fail(monkeypatch, capsys):
    """一律判通過的評審：沒問題的範例過關，故意寫壞的範例全部被抓出來。"""
    out = run(monkeypatch, capsys, ["judge", "--runs", "1"])
    assert "✓ 沒問題的劇情判通過（不替玩家做決定）  1/1" in out
    assert "✗ 識破替玩家做決定  0/1" in out and "✗ 識破文風不符題材  0/1" in out
