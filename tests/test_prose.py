"""Textual 外殼的中文換行。"""

from rich.cells import cell_len

from story.shells.textual.prose import wrap


def test_spaces_around_english_names_do_not_break_lines_early():
    text = "阿明轉頭看向 Bob，發現他的手臂正在流血，鮮血順著指尖一滴一滴落在冰冷的石地上。"
    assert wrap(text, 40) == [
        "阿明轉頭看向 Bob，發現他的手臂正在流血，",
        "鮮血順著指尖一滴一滴落在冰冷的石地上。",
    ]


def test_english_words_are_not_split():
    lines = wrap("一二三四五六七八九十一二三四五六七八 Alexander 走了進來。", 40)
    assert any("Alexander" in line for line in lines)


def test_punctuation_never_starts_a_line():
    text = "一二三四五六七八九十一二三四五六七八九十。接著是下一句話，一直寫下去，看看會不會出問題。"
    for line in wrap(text, 40)[1:]:
        assert line[0] not in "。，、！？：；」"


def test_opening_quote_never_ends_a_line():
    text = "一二三四五六七八九十一二三四五六七八九「快走！」"
    for line in wrap(text, 40)[:-1]:
        assert not line.endswith("「")


def test_lines_fit_the_width_and_keep_paragraphs():
    text = "第一段，很長很長很長很長很長很長很長很長很長很長很長。\n\n第二段。"
    lines = wrap(text, 20)
    assert all(cell_len(line) <= 20 for line in lines)
    assert "" in lines and lines[-1] == "第二段。"


def test_word_longer_than_line_is_split():
    assert all(cell_len(line) <= 10 for line in wrap("Supercalifragilistic", 10))
