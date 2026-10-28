"""just eval: run once with a fake Gemini to check the scenarios build and the checks and report work (real evals call the API and aren't in the tests)."""

import json

import pytest
from conftest import FakeGemini, beat, cond

from story import evals
from story.games.adventure import evals as adventure


class JudgingGemini(FakeGemini):
    """A fake Gemini that answers the judge: always a pass."""

    def generate_content(self, model, contents, config):
        if getattr(config, "response_schema", None) is adventure.Verdict:
            return type("Response", (), {"parsed": adventure.Verdict(reason="沒問題", passed=True)})()
        return super().generate_content(model, contents, config)


def run(monkeypatch, capsys, args, *beats):
    monkeypatch.setattr(evals.settings, "api_key", lambda: "key")
    monkeypatch.setattr(evals, "RPM", 60_000)  # Tests don't wait
    monkeypatch.setattr(evals, "new_client", lambda key: JudgingGemini(beats))
    evals.main(args)
    return capsys.readouterr().out


def test_agency_scenario_runs_checks_and_saves_results(monkeypatch, capsys, isolated):
    out = run(monkeypatch, capsys, ["agency", "--runs", "1"], beat(narration="燈" * 200, choices=["等", "走"]))
    assert "✓ doesn't decide for the player  1/1" in out and "Passed 4/4 checks" in out
    record = json.loads(next((isolated / "eval_results").glob("*.jsonl")).read_text(encoding="utf-8"))
    assert record["scenario"] == "agency" and record["output"]["narration"] == "燈" * 200
    assert not (isolated / "story_log.jsonl").exists() and not (isolated / "save.json").exists()


def test_failed_checks_show_the_reason(monkeypatch, capsys):
    out = run(monkeypatch, capsys, ["reckless", "--runs", "1"], beat(narration="短", choices=["等"]))
    assert "✗ a reckless action caused wounds (wound total up by at least 2)  0/1" in out and "wound total 2 → 2" in out
    assert "✗ narration length 150-300  0/1" in out


def test_dying_scenario_passes_when_the_wound_is_fatal(monkeypatch, capsys):
    out = run(monkeypatch, capsys, ["dying", "--runs", "1"],
              beat(narration="刀落下。", conditions_changed=[cond("胸口刀傷", "重")]), beat(narration="你倒下了。"))
    assert "✓ taking risks while dying is fatal  1/1" in out


def test_every_genre_pack_has_a_tone_scenario():
    found = adventure.scenarios()
    assert {"opening", "early", "reveal", "agency", "reckless", "dying", "judge", "武俠"} <= set(found)


def test_unknown_scenario_lists_the_choices(monkeypatch, capsys):
    with pytest.raises(SystemExit, match="Available: opening"):
        run(monkeypatch, capsys, ["nope"])
