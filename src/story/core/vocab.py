"""Game vocabulary: code and saves use codes; text shown to the AI, returned by the AI, or shown to players uses this language's words.

Each game has its own vocabulary (prompts/<lang>/vocab.md), read with Vocab: each section is a category, one "code: word" per line.
"""

from typing import Literal, get_args

from story.core import prompts


class Vocab:
    def __init__(self, sections: dict[str, str], codes: dict):
        """sections are the sections of vocab.md; codes is {category: Literal of codes}. Raises if any code has no word."""
        self.codes = codes
        self.table = {category: prompts.table(body) for category, body in sections.items()}  # {category: {code: word}}
        for category, options in codes.items():
            if missing := set(get_args(options)) - set(self.table.get(category, {})):
                raise ValueError(f"vocab.md category {category!r} is missing: {', '.join(sorted(missing))}")

    def word(self, category: str, code: str) -> str:
        """Code → this language's word, e.g. word("severity", "severe") is "severe" in English."""
        return self.table[category][code]

    def code(self, category: str, text: str) -> str:
        """This language's word → code (the AI returns words). The result is always one of the category's codes (checked in __init__),
        so callers cast it to that category's Literal."""
        return next(c for c, w in self.table[category].items() if w == text)

    def words(self, category: str):
        """Options for the AI's response format: every word in this category, in code order."""
        return Literal[tuple(self.word(category, c) for c in get_args(self.codes[category]))]
