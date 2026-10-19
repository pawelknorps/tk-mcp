"""Smoke testy online - hit live trybunal.gov.pl.

Uruchamia sie jawnie (nie wchodza w domyslny `pytest`):
    pytest -m smoke -v

Te testy moga byc flaky jezeli:
- strona zmieni HTML -> parsery w `models.py` wymagaja update
- strona jest down / pod load
- brak sieci

W razie failure - PIERWSZE: odswiez fixture'y i uruchom testy offline; jesli
offline tez padaja, strona zmienila kontrakt i trzeba poprawic sciezki w `models.py`.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.smoke


@pytest.mark.asyncio
async def test_smoke_search_signature_returns_results():
    """search_judgments("K 15/24") zwraca trafienia z tytulami."""
    from tk_mcp.server import search_judgments

    result = await search_judgments(query="K 15/24")

    if result["count"] == 0:
        pytest.skip(f"strona nie zwrocila wynikow dla K 15/24 (HTML moze sie zmienic): {result['source_url']}")

    assert result["count"] > 0
    assert result["items"], "count > 0, wiec strona wynikow nie moze byc pusta"
    for item in result["items"]:
        assert item["title"] or item["href"]


@pytest.mark.asyncio
async def test_smoke_common_word_has_a_large_corpus():
    """search_judgments("konstytucja") trafia w tysiace dokumentow (strona: ~8700)."""
    from tk_mcp.server import search_judgments

    result = await search_judgments(query="konstytucja")

    if result["count"] == 0:
        pytest.skip(f"strona nie zwrocila licznika dla 'konstytucja': {result['source_url']}")

    assert result["count"] > 1000
    assert result["items"]


@pytest.mark.asyncio
async def test_smoke_get_judgment_text_returns_ruling_text():
    """Pelny tekst orzeczenia z pierwszego wyniku, ktory jest strona .../art/..."""
    from tk_mcp.server import get_judgment_text, search_judgments

    listing = await search_judgments(query="K 15/24")
    art = next((i for i in listing["items"] if "/art/" in i["href"]), None)
    if art is None:
        pytest.skip("w pierwszych wynikach brak strony .../art/ (strona zmienila uklad wynikow)")

    doc = await get_judgment_text(path=art["href"])

    assert doc["paragraphs"], "parser #content nie zwrocil akapitow"
    assert doc["text"].strip()
    assert doc["char_count"] == len(doc["text"])
