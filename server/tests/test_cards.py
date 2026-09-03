import pytest

from cardbox.cards import InvalidBlackCard, is_question, normalize_text, parse_black_card


def test_single_blank_pick_1():
    assert parse_black_card("_ is the leading cause of divorce.") == 1


def test_multi_blank_pick_counts_blanks():
    assert parse_black_card("I got _ and then I got _.") == 2
    assert parse_black_card("_, _, and _ walk into a bar.") == 3


def test_question_zero_blanks_pick_1():
    assert parse_black_card("What's my secret power?") == 1


def test_blankless_non_question_rejected():
    with pytest.raises(InvalidBlackCard):
        parse_black_card("This has no blank and no question mark.")


def test_is_question():
    assert is_question("What's my secret power?") is True
    assert is_question("_ is the leading cause of divorce.") is False


def test_normalize_text_case_and_whitespace():
    assert normalize_text("  Bees.  ") == normalize_text("bees.")
    assert normalize_text("A   thing") == normalize_text("a thing")
