"""The shared part of just eval: one attempt of a scenario. The whole flow and the report are covered in test_evals.py."""

from story.core.evals import Check, Scenario, Trial, attempt


def test_checks_are_recorded_as_booleans(isolated):
    run = attempt(Scenario("d", lambda t: t.check("a", 1)), client=None, log_path=isolated / "l.jsonl")
    assert run.checks == [Check("a", True, "")] and run.error == ""


def test_a_failing_run_keeps_its_checks_and_a_short_error(isolated):
    def run(t):
        t.check("before", True)
        raise RuntimeError("x" * 500)

    result = attempt(Scenario("d", run), client=None, log_path=isolated / "l.jsonl")
    assert [c.name for c in result.checks] == ["before"] and len(result.error) == 200


def test_a_scenario_can_bring_its_own_trial(isolated):
    class MyTrial(Trial):
        pass

    seen = []
    attempt(Scenario("d", lambda t: seen.append(type(t)), trial=MyTrial), client=None, log_path=isolated / "l.jsonl")
    assert seen == [MyTrial]
