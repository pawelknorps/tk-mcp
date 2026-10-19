"""Offline testy parserow HTML na zywych fixture'ach z trybunal.gov.pl."""

from __future__ import annotations

from tk_mcp.models import (
    JudgmentRef,
    absolute_url,
    parse_judgment_text,
    parse_search_fragment,
)


def test_search_count_comes_from_the_heading(fixture_html):
    """Naglowek `Wyniki dla "..." (146)` daje globalny count."""
    count, items = parse_search_fragment(fixture_html("search_k15_24.html"))
    assert count == 146
    assert items, "zapytanie K 15/24 zwraca wyniki"


def test_search_items_carry_title_and_absolute_href(fixture_html):
    _count, items = parse_search_fragment(fixture_html("search_k15_24.html"))

    # UWAGA: pierwszy wynik zapytania "K 15/24" to teczka sprawy (`/s/k-15-24`),
    # nie strona orzeczenia - strona stawia teczke wyzej niz /art/. Pelny tekst
    # bierzemy z pierwszego wyniku, ktory faktycznie jest strona `.../art/...`.
    art_items = [i for i in items if "/art/" in i["href"]]
    assert art_items, "wyniki K 15/24 zawieraja strony /art/"
    assert any("/wyroki/art/" in i["href"] or "/sprawy-w-trybunale/art/" in i["href"] for i in items)

    for item in items:
        assert item["href"].startswith("https://trybunal.gov.pl/")
        assert item["title"], "kazdy wynik ma <h2> z tytulem"
        assert item["document_id"]


def test_search_first_item_is_a_case_file_without_snippet(fixture_html):
    """Teczka sprawy nie ma snippetu - parser zwraca pusty string, nie wybucha."""
    _, items = parse_search_fragment(fixture_html("search_k15_24.html"))
    assert items[0]["href"].endswith("/s/k-15-24")
    assert items[0]["title"].startswith("K 15/24")
    assert items[0]["snippet"] == ""


def test_search_items_build_into_model(fixture_html):
    _, items = parse_search_fragment(fixture_html("search_k15_24.html"))
    ref = JudgmentRef(**items[0])
    assert ref.document_score
    assert ref.href.startswith("https://")


def test_search_no_hits_returns_zero_not_an_error(fixture_html):
    """Brak trafien: albo brak naglowka, albo licznik `(0)` - oba to count 0."""
    count, items = parse_search_fragment(fixture_html("search_no_hits.html"))
    assert count == 0
    assert items == []


def test_judgment_paragraphs_live_inside_content(fixture_html):
    parsed = parse_judgment_text(fixture_html("judgment_4844.html"))
    assert parsed["paragraphs"], "wyrok K 63/07 ma akapity w #content"
    assert parsed["title"].startswith("Wiek emerytalny kobiet i mężczyzn")
    text = "\n".join(parsed["paragraphs"])
    assert "Trybunał Konstytucyjny w składzie" in text or "Sygn. akt" in text


def test_judgment_first_paragraph_is_ruling_not_nav(fixture_html):
    """Nav/naglowek tez emituje dlugie <p> - scope do #content musi je odciac."""
    parsed = parse_judgment_text(fixture_html("judgment_4844.html"))
    first = parsed["paragraphs"][0]
    assert "Biuletyn Informacji Publicznej" not in first
    assert "Drukuj" not in first


def test_judgment_drops_boilerplate_meta_paragraphs(fixture_html):
    parsed = parse_judgment_text(fixture_html("judgment_4844.html"))
    joined = "\n".join(parsed["paragraphs"])
    assert "Krótki link do tej sygnatury" not in joined
    assert "Wyłącz linki do sygnatur" not in joined


def test_judgment_keeps_blockquote_content(fixture_html):
    """Cytowany przepis i protokolant stoja jako <blockquote> - nie gina."""
    parsed = parse_judgment_text(fixture_html("judgment_4844.html"))
    joined = "\n".join(parsed["paragraphs"])
    assert "protokolant" in joined or "art. 24 ust. 1" in joined


def test_absolute_url_normalises_relative_hrefs():
    assert absolute_url("/wyroki/art/1-x") == "https://trybunal.gov.pl/wyroki/art/1-x"
    assert absolute_url("https://trybunal.gov.pl/x") == "https://trybunal.gov.pl/x"
    assert absolute_url("wyroki/art/1-x") == "https://trybunal.gov.pl/wyroki/art/1-x"
    assert absolute_url("") == ""
