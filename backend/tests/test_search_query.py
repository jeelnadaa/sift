"""Phase 3b: query splitting and operator parsing (brief section 19 asks for these tests)."""
import pytest

from app.search.query import Filter, QueryError, parse, tokenize


def test_gmail_syntax_passes_through_untouched():
    q = 'from:kotak subject:"card blocked" -in:spam has:attachment larger:5M after:2026/10/01 (invoice OR receipt) {from:a from:b} "exact words" AROUND 3 is:unread category:promotions list:news.example'
    p = parse(q)
    assert p.gmail == q and p.filters == [] and p.any_of == []
    assert p.words == ["exact words"]


def test_sift_filters_are_split_out():
    p = parse('from:hirepro folder:"Job hunt" -tag:done priority:URGENT is:silenced has:note company:Acme account:me@gmail.com interview')
    assert p.gmail == "from:hirepro interview"
    assert p.filters == [Filter("folder", "Job hunt"), Filter("tag", "done", True), Filter("priority", "urgent"),
                         Filter("is", "silenced"), Filter("has", "note"), Filter("company", "Acme"), Filter("account", "me@gmail.com")]
    assert p.words == ["interview"]
    assert [c.kind for c in p.chips] == ["gmail", "sift", "sift", "sift", "sift", "sift", "sift", "sift", "gmail"]
    assert p.chips[1].text == 'folder:"Job hunt"' and p.chips[2].label == "Not tag: done"


def test_gmail_is_and_has_values_stay_with_gmail():
    p = parse("is:unread is:starred has:drive has:attachment is:grouped has:link")
    assert p.gmail == "is:unread is:starred has:drive has:attachment"
    assert p.filters == [Filter("is", "grouped"), Filter("has", "link")]


def test_braces_or_sift_filters():
    p = parse("{folder:Work folder:Placements} newer_than:7d")
    assert p.any_of == [[Filter("folder", "Work"), Filter("folder", "Placements")]] and p.gmail == "newer_than:7d"
    with pytest.raises(QueryError):
        parse("{folder:Work from:x}")
    with pytest.raises(QueryError):
        parse("-{folder:A folder:B}")


@pytest.mark.parametrize("bad", ["priority:loud", "OR folder:x", "x" * 1001, " ".join(["w"] * 61)])
def test_bad_queries_are_refused_with_a_message(bad):
    with pytest.raises(QueryError):
        parse(bad)


def test_tokenizer_tolerates_unclosed_quotes_and_groups():
    assert tokenize('subject:"half open') == ['subject:"half open']
    assert tokenize("(a OR b") == ["(a OR b"]
    assert parse("").gmail == "" and not parse("").has_gmail


def test_chips_round_trip_to_the_same_query():
    q = 'from:kotak -tag:done folder:"Job hunt" {tag:a tag:b} "two words"'
    p = parse(q)
    assert parse(" ".join(c.text for c in p.chips)).filters == p.filters
    assert " ".join(c.text for c in p.chips) == q
