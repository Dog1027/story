"""Reply: what the core sends the shells. It crosses rooms as JSON, so it must come back the same."""

import json

from story.core.reply import Reply, SetupForm, pick_choice


def test_pick_choice_takes_a_number_or_the_option_itself():
    options = ["往上爬", "躲起來"]
    assert pick_choice("2", options) == "躲起來" and pick_choice("往上爬", options) == "往上爬"
    assert pick_choice("0", options) is None and pick_choice("9", options) is None and pick_choice("跳", options) is None


def test_a_setup_form_survives_json():
    reply = Reply(phase="setup", form=SetupForm(default="d", genre="g", genres=[("g", "G", "desc")], suggestion="s"))
    back = Reply.from_dict(json.loads(json.dumps(reply.to_dict())))
    assert isinstance(back.form, SetupForm)
    assert (back.form.default, back.form.genre, back.form.suggestion) == ("d", "g", "s")
    assert [list(g) for g in back.form.genres] == [["g", "G", "desc"]]  # JSON has no tuples


def test_a_reply_without_a_form_stays_without_one():
    assert Reply.from_dict(json.loads(json.dumps(Reply(phase="setup", choices=["a", "b"]).to_dict()))).form is None
