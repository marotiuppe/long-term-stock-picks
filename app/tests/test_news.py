import os, sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import server


@pytest.mark.parametrize("title", [
    "HDFC Bank shares steady ahead of results",
    "Bandhan Bank board meets on Friday",
    "Tata Motors begins mission to expand EV range",
    "Lossless compression firm lists on NSE",
    "Banking stocks in focus",
])
def test_bank_like_words_score_zero(title):
    assert server.news_tone(title) == 0


@pytest.mark.parametrize("title,tone", [
    ("SEBI imposes ban on promoter", -1),
    ("Company posts loss in Q2", -1),
    ("Stock plunges after fraud probe", -1),
    ("Brokerage upgrade lifts shares", 1),
    ("Profit surges to record high", 1),
    ("Rally continues as stock jumps", 1),
])
def test_real_signals_are_scored(title, tone):
    assert server.news_tone(title) == tone


def test_bank_headline_is_not_tagged_regulatory():
    import re
    rx = dict(server.TAGS)["regulatory"]
    assert not re.search(rx, "HDFC Bank shares steady", re.I)
    assert re.search(rx, "RBI action on lender", re.I)
