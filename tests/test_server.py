"""Testy serwera: powierzchnia toolow (fastmcp Client) + przeplywy offline.

Zadne z tych testow nie wychodzi do sieci - `TkClient` jest podmieniany,
a `tk_coverage` nie dotyka strony wcale.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from fastmcp import Client

from tk_mcp.client import TkClient
from tk_mcp.server import (
    INSTRUCTIONS,
    TkError,
    get_judgment_text,
    mcp,
    search_judgments,
    tk_coverage,
)

EXPECTED_TOOLS = {"search_judgments", "get_judgment_text", "tk_coverage"}


def _fn(tool):
    """fastmcp 3 owinien tool w FunctionTool - `fn` to oryginalna coroutine."""
    return getattr(tool, "fn", tool)


def _run(tool, **kwargs):
    return asyncio.run(_fn(tool)(**kwargs))


def _audit_lines(tmp_path: Path) -> list[dict]:
    return [
        json.loads(line)
        for f in tmp_path.rglob("*.jsonl")
        for line in f.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# ---------- powierzchnia toolow ----------


@pytest.mark.asyncio
async def test_tool_surface_is_exactly_the_three_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {t.name for t in tools} == EXPECTED_TOOLS


@pytest.mark.asyncio
async def test_all_tools_are_marked_read_only():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.annotations is not None, f"{tool.name} bez adnotacji"
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False


@pytest.mark.asyncio
async def test_every_tool_is_documented_in_the_instructions():
    """INSTRUCTIONS to system prompt klienta - tool poza nim jest dla LLM niewidoczny."""
    async with Client(mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert tool.name in INSTRUCTIONS, f"{tool.name} nie wystepuje w INSTRUCTIONS"


def test_instructions_cover_the_hard_rules():
    """Kontrakt strony musi byc w system promptcie, nie tylko w kodzie."""
    assert "type=7383" in INSTRUCTIONS
    assert "#content" in INSTRUCTIONS
    assert "Publiczne ogłoszenie orzeczenia" in INSTRUCTIONS
    assert "ustrojow" in INSTRUCTIONS


@pytest.mark.asyncio
async def test_coverage_tool_returns_non_empty_gaps():
    result = await _fn(tk_coverage)()
    assert result.status == "ok"
    assert result.families
    assert result.known_gaps
    assert all(g.fallback for g in result.known_gaps)


@pytest.mark.asyncio
async def test_coverage_over_the_mcp_client(tmp_path):
    async with Client(mcp) as client:
        result = await client.call_tool("tk_coverage", {})
    payload = result.structured_content or result.data
    assert payload["known_gaps"]
    assert any(entry["tool"] == "tk_coverage" for entry in _audit_lines(tmp_path))


# ---------- przeplywy narzedzi (offline, klient podmieniony) ----------


def test_search_judgments_parses_page_and_logs_audit(fixture_html, monkeypatch, tmp_path):
    async def fake_search(self, query, page=1, sort=None, filter=None):
        return fixture_html("search_k15_24.html"), (
            f"https://trybunal.gov.pl/wyszukiwarka?tx_solr%5Bq%5D={query}&type=7383"
        )

    monkeypatch.setattr(TkClient, "search", fake_search)

    result = _run(search_judgments, query="K 15/24")

    assert result["count"] == 146
    assert result["query"] == "K 15/24"
    assert result["page"] == 1
    assert result["items"], "strona wynikow nie moze byc pusta"
    assert result["items"][0]["title"]
    assert result["has_more"] is True
    assert "type=7383" in result["source_url"]

    lines = _audit_lines(tmp_path)
    assert lines and lines[-1]["tool"] == "search_judgments"
    assert lines[-1]["result_summary"]["count"] == 146
    assert lines[-1]["source_urls"]


def test_search_judgments_percent_encodes_the_query(monkeypatch):
    seen: dict = {}

    async def fake_search(self, query, page=1, sort=None, filter=None):
        seen["params"] = (query, page, sort, filter)
        return "<html></html>", "https://trybunal.gov.pl/wyszukiwarka?type=7383"

    monkeypatch.setattr(TkClient, "search", fake_search)

    result = _run(search_judgments, query="K 15/24", page=2, filter="category:Wyrok")

    assert seen["params"] == ("K 15/24", 2, None, "category:Wyrok")
    assert result["count"] == 0  # brak naglowka = brak trafien, nie blad
    assert result["items"] == []
    assert result["has_more"] is False


def test_get_judgment_text_scopes_to_content(fixture_html, monkeypatch, tmp_path):
    async def fake_get(self, path):
        return fixture_html("judgment_4844.html"), (
            "https://trybunal.gov.pl/postepowanie-i-orzeczenia/wyroki/art/4844-wiek-emerytalny-kobiet-i-mezczyzn"
        )

    monkeypatch.setattr(TkClient, "get_judgment", fake_get)

    result = _run(get_judgment_text, path="/postepowanie-i-orzeczenia/wyroki/art/4844-wiek-emerytalny-kobiet-i-mezczyzn")

    assert result["title"].startswith("Wiek emerytalny kobiet i mężczyzn")
    assert result["paragraphs"]
    assert "Trybunał Konstytucyjny w składzie" in result["text"]
    assert "Biuletyn Informacji Publicznej" not in result["paragraphs"][0]
    assert result["char_count"] == len(result["text"])
    assert result["source_url"].endswith("/art/4844-wiek-emerytalny-kobiet-i-mezczyzn")
    assert any(entry["tool"] == "get_judgment_text" for entry in _audit_lines(tmp_path))


# ---------- walidacja i kody bledow ----------


def test_missing_query_is_a_structured_error():
    with pytest.raises(TkError) as exc:
        _run(search_judgments, query="")
    assert exc.value.code == "missing_arg"
    assert str(exc.value).startswith("[missing_arg]")


def test_page_zero_is_a_structured_error():
    with pytest.raises(TkError) as exc:
        _run(search_judgments, query="K 15/24", page=0)
    assert exc.value.code == "invalid_arg"


def test_unknown_sort_and_filter_are_structured_errors():
    with pytest.raises(TkError) as exc:
        _run(search_judgments, query="x", sort="nonsense")
    assert exc.value.code == "invalid_arg"

    with pytest.raises(TkError) as exc:
        _run(search_judgments, query="x", filter="category:Publiczne ogłoszenie orzeczenia")
    assert exc.value.code == "invalid_arg"


def test_missing_path_is_a_structured_error():
    with pytest.raises(TkError) as exc:
        _run(get_judgment_text, path="")
    assert exc.value.code == "missing_arg"


def test_404_maps_to_not_found(monkeypatch):
    async def fake_get(self, path):
        request = httpx.Request("GET", "https://trybunal.gov.pl/postepowanie-i-orzeczenia/wyroki/art/nope")
        response = httpx.Response(404, request=request)
        raise httpx.HTTPStatusError("404", request=request, response=response)

    monkeypatch.setattr(TkClient, "get_judgment", fake_get)

    with pytest.raises(TkError) as exc:
        _run(get_judgment_text, path="/postepowanie-i-orzeczenia/wyroki/art/nope")
    assert exc.value.code == "not_found"


def test_network_failure_maps_to_upstream_error(monkeypatch):
    async def fake_search(self, query, page=1, sort=None, filter=None):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(TkClient, "search", fake_search)

    with pytest.raises(TkError) as exc:
        _run(search_judgments, query="K 15/24")
    assert exc.value.code == "upstream_error"
