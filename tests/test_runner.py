"""CoreRunner: runs a room's core in a background thread and tells everyone how it's going. The room-level flow is in test_room.py."""

from types import SimpleNamespace

from story.core import Reply
from story.shells.rooms.runner import CoreRunner
from story.shells.text import UI


def make_runner():
    sent: list[dict] = []

    async def broadcast(message):
        sent.append(message)

    return CoreRunner(broadcast), sent


async def test_without_a_core_there_is_nothing_to_report():
    runner, _ = make_runner()
    assert runner.progress() == "" and runner.label() == ""


async def test_a_quiet_call_broadcasts_nothing():
    runner, sent = make_runner()
    assert (await runner.call(lambda: Reply(phase="playing"))).phase == "playing" and sent == []


async def test_queuing_for_the_call_limit_is_the_progress():
    runner, _ = make_runner()
    runner.attach(SimpleNamespace(progress="寫開場", draft="", busy_label="L", watch=lambda cb: None))
    runner.set_queued(True)
    assert runner.progress() == UI["queued"] and runner.label() == "L"
    runner.set_queued(False)
    assert runner.progress() == "寫開場"


async def test_news_after_the_call_ended_is_dropped():
    runner, sent = make_runner()
    runner.attach(SimpleNamespace(progress="寫開場", draft="一半", busy_label="L", watch=lambda cb: None))
    await runner._report()  # Not busy: nobody is looking at the waiting screen
    assert sent == []
