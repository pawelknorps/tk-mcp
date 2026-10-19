"""Offline unit testy budowy URL-i i walidacji argumentow.

To jedyne miejsce, gdzie `type=7383`, klucze `tx_solr[...]` i lista faset moga sie
cicho zepsuc - dlatego testujemy je bez sieci.
"""

from __future__ import annotations

import pytest

from tk_mcp.client import build_search_params, judgment_path
from tk_mcp.models import ALLOWED_FILTERS, ALLOWED_SORTS, SEARCH_TYPE
from tk_mcp.server import (
    TkError,
    _require_path,
    _require_query,
    _validate_choice,
    _validate_page,
)

# ---------- budowa parametrow wyszukiwarki ----------


def test_type_is_always_present_and_mandatory():
    """Bez `type=7383` strona zwraca sam szkielet - dlatego jest na stale."""
    params = build_search_params("K 15/24")
    assert params["type"] == SEARCH_TYPE == "7383"
    assert params["tx_solr[q]"] == "K 15/24"


def test_page_one_is_not_emitted_but_later_pages_are():
    assert "tx_solr[page]" not in build_search_params("x", page=1)
    assert build_search_params("x", page=3)["tx_solr[page]"] == 3


def test_sort_and_filter_use_solr_keys():
    params = build_search_params("x", sort="publicationDate+desc", filter="category:Wyrok")
    assert params["tx_solr[sort]"] == "publicationDate+desc"
    assert params["tx_solr[filter][0]"] == "category:Wyrok"


def test_optional_params_are_omitted_when_none():
    params = build_search_params("x")
    assert "tx_solr[sort]" not in params
    assert "tx_solr[filter][0]" not in params


# ---------- sciezka orzeczenia ----------


def test_judgment_path_adds_a_leading_slash():
    assert judgment_path("postepowanie-i-orzeczenia/wyroki/art/1-x") == (
        "/postepowanie-i-orzeczenia/wyroki/art/1-x"
    )
    assert judgment_path("  /s/k-15-24  ") == "/s/k-15-24"


def test_judgment_path_keeps_absolute_urls():
    url = "https://trybunal.gov.pl/postepowanie-i-orzeczenia/wyroki/art/1-x"
    assert judgment_path(url) == url


# ---------- walidacja argumentow ----------


def test_page_must_be_at_least_one():
    assert _validate_page(1) == 1
    with pytest.raises(TkError) as exc:
        _validate_page(0)
    assert exc.value.code == "invalid_arg"


def test_empty_query_falls_back_to_match_all_and_path_is_required():
    # Pusta fraza = przegladanie po samej fasce -> Solr match-all `*:*`.
    assert _require_query("   ") == "*:*"
    assert _require_query("K 15/24") == "K 15/24"

    with pytest.raises(TkError) as exc:
        _require_path("")
    assert exc.value.code == "missing_arg"


def test_sort_and_filter_values_are_closed_lists():
    assert _validate_choice(ALLOWED_SORTS[0], ALLOWED_SORTS, "sort") == ALLOWED_SORTS[0]
    assert _validate_choice(None, ALLOWED_SORTS, "sort") is None

    with pytest.raises(TkError) as exc:
        _validate_choice("publicationDate+sideways", ALLOWED_SORTS, "sort")
    assert exc.value.code == "invalid_arg"

    with pytest.raises(TkError) as exc:
        _validate_choice("category:NieMaTakiej", ALLOWED_FILTERS, "filter")
    assert exc.value.code == "invalid_arg"


def test_real_filter_values_pass():
    for value in ("signature:K", "category:Wyrok", "category:Postanowienie", "modificationDate:all"):
        assert _validate_choice(value, ALLOWED_FILTERS, "filter") == value


def test_announcements_facet_is_not_offered():
    """`category:Publiczne ogłoszenie orzeczenia` to faseta ogloszen - dla sygnatur zwraca 0."""
    assert "category:Publiczne ogłoszenie orzeczenia" not in ALLOWED_FILTERS
