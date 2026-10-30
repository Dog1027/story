"""Vocab: codes in the program, words for people and the AI. The real vocab.md files are checked in test_prompts.py."""

from typing import Literal, get_args

import pytest

from story.core.vocab import Vocab


def test_words_follow_the_code_order():
    vocab = Vocab({"severity": "severe: bad\nlight: mild"}, {"severity": Literal["light", "severe"]})
    assert get_args(vocab.words("severity")) == ("mild", "bad")


def test_a_code_without_a_word_is_caught_at_load():
    with pytest.raises(ValueError, match="severe"):
        Vocab({"severity": "light: mild"}, {"severity": Literal["light", "severe"]})
