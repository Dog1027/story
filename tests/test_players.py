"""Player names on the web: which names are allowed (the lobby keeps two people from using one name at once; see test_room.py)."""

import pytest

from story.shells.players import InvalidName, check_name


@pytest.mark.parametrize("raw, name", [("阿明", "阿明"), ("  Bob_2 ", "Bob_2"), ("小華-3", "小華-3")])
def test_valid_names(raw, name):
    assert check_name(raw) == name


@pytest.mark.parametrize("raw", ["", "   ", "../../etc/passwd", "a b", "a/b", "名" * 21])
def test_invalid_names(raw):
    with pytest.raises(InvalidName):
        check_name(raw)
