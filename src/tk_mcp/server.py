"""FastMCP server - 3 super-tools dla orzecznictwa Trybunalu Konstytucyjnego.

Uruchamianie:
    python -m tk_mcp.server

Lub jako entry point po pip install:
    tk-mcp
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import audit
from .client import TkClient
from .coverage import Coverage, build_coverage
from .models import (
    ALLOWED_FILTERS,
    ALLOWED_SORTS,
    JudgmentRef,
    JudgmentSearchResult,
    JudgmentText,
    parse_judgment_text,
    parse_search_fragment,
)

# ---------------------------------------------------------------------------
# Instructions (procedural orchestration) - wstrzykiwane do system promptu
# klienta MCP. LLM widzi to PRZED pierwszym tool call.
# ---------------------------------------------------------------------------

INSTRUCTIONS = """\
Ten serwer MCP udostepnia orzecznictwo Trybunalu Konstytucyjnego z oficjalnej strony trybunal.gov.pl (HTML, bez auth): wyszukiwarke orzeczen (wyroki i postanowienia) oraz pelny tekst orzeczenia. To strona HTML, nie API - konektor parsuje odpowiedzi.

## Kolejnosc wywolan

### 1. `search_judgments` - wyszukiwarka (Solr)
1. `GET /wyszukiwarka?tx_solr[q]=<fraza>&type=7383`. Fraza w cudzyslowie; `type=7383` jest OBLIGATORYJNY - bez niego strona zwraca sam szkielet, bez wynikow.
2. Zwraca: `count` (globalna liczba trafien z naglowka `Wyniki dla "..." (N)`), `items` (jedna strona, ~10 wynikow: `href`, `title`, `snippet`, `document_id`, `document_score`) oraz `has_more`.
3. Paginacja: `page` (1-based, `tx_solr[page]`). `count` jest globalny miedzy stronami.
4. Sortowanie: `sort` = `publicationDate+desc` albo `publicationDate+asc`.
5. Fasety (`filter`): `signature:K|Kp|Kpt|P|Pp|SK|U`, `category:Wyrok`, `category:Postanowienie`, `modificationDate:today|lastWeek|lastMonth|lastYear|all`.

### 2. `get_judgment_text` - pelny tekst orzeczenia
`GET /postepowanie-i-orzeczenia/wyroki/art/<id>-<slug>`. `path` przyjmuje pelny URL, sciezke absolutna albo wzgledna. Parser scope'uje sie do kontenera `#content` (nav/naglowek emituja wlasne dlugie `<p>`) i zwraca akapity oraz `text`. Bez PDF, bez JS.

### 3. `tk_coverage` - granice konektora
Wywolaj PRZED powiedzeniem uzytkownikowi, ze czegos "nie ma" w orzecznictwie TK, i zawsze gdy szukanie zwraca pustke. To moze byc luka konektora, a nie brak w orzecznictwie. Kazda luka ma `fallback`.

## Twarde ograniczenia

- **`type=7383` jest obowiazkowy** - bez tego parametru zamiast wynikow dostaniesz sam szkielet strony.
- **Brak trafien = count 0, nie blad** - gdy nie ma naglowka z licznikiem albo licznik mowi 0, tool zwraca `count=0` i puste `items`. To nie jest awaria.
- **ZLY FACET** - `category:Publiczne ogłoszenie orzeczenia` to faseta *ogloszen* (komunikatow); dla realnych sygnatur zwraca 0. NIE uzywaj jej do szukania orzeczen. Do orzeczen sluzy `category:Wyrok` / `category:Postanowienie`.
- **Wyniki sa mieszane** - fragment Solr zawiera teczki sprawy (`/s/...`), komunikaty i wiadomosci (`/wiadomosci/...`) obok wyrokow (`/wyroki/art/...`). Filtruj po `href`, zanim uznasz wynik za orzeczenie.
- **Snippet to nie tresc** - `search_judgments` daje link + tytul + snippet; pelny tekst (sklad orzekajacy, uzasadnienie) dopiero przez `get_judgment_text`. Bez enumeracji masowej: `sitemap.xml` zwraca HTTP 500, wiec przechodz strona po stronie.
- **Kontekst ustrojowy 2024-2026** - orzeczenia TK z tego okresu sa czescia sporu ustrojowego o sklad i waznosc orzeczen. Konektor zwraca tresc verbatim i NIE rozstrzyga o waznosci, prawomocnosci ani o prawidlowosci powolania skladu. Sprawdz sklad orzekajacy i podstawe prawna w zrodlach urzedowych (trybunal.gov.pl, Monitor Polski, ipo.trybunal.gov.pl).
- **Kategorie to nie taksonomia prawna** - `category:Wyrok`/`Postanowienie` to redakcyjne kategorie strony, nie formalna klasyfikacja ustawowa.
- **Orzeczenia TK to nie zrodlo prawa powszechnego** - wyrok TK wiaze w sprawie (art. 190 Konstytucji), ale konektor nie tworzy ani nie zmienia przepisow. Do tekstu obowiazujacego idz do konektora `isap` / eli.gov.pl.
- **Bez modyfikacji tresci urzedowej** - tytuly, sygnatury i tekst orzeczen zwracamy verbatim.
- **Audit log JSONL** - kazdy tool call zapisuje audit do `~/.matematic/audit/tk-mcp.jsonl` (bez pelnych tresci orzeczen).

## Iteracja po bledach

Tool zwraca structured error z prefixem `[code]`:
- `missing_arg` - brakujacy wymagany parametr (pusta `query` / pusty `path`).
- `invalid_arg` - parametr poza zakresem (np `page < 1`, nieznana wartosc `sort` albo `filter`).
- `not_found` - strona orzeczenia nie istnieje (HTTP 404). Sprobuj innego `path`.
- `upstream_error` - blad trybunal.gov.pl (HTTP, timeout, zly HTML). Retry raz przed surface do uzytkownika.

## Styl odpowiedzi

- Cytuj orzeczenie po sygnaturze i tytule, z URL-em: `Wyrok TK, sygn. K 63/07, "Wiek emerytalny kobiet i mezczyzn"` + `source_url`.
- Sygnature i tytul podawaj verbatim z odpowiedzi - nie tlumacz i nie wymyslaj.
- Mow "wyrok" albo "postanowienie" zgodnie z trescia, nie z sama kategoria strony.
- NIE wymyslaj sygnatur, dat ani tytulow - wszystko z `structuredContent`.
"""


# Strukturalne kody bledow - widoczne dla LLM z prefixem [code].
class TkError(Exception):
    """Strukturalny blad dla tk-mcp tools."""

    VALID_CODES = frozenset({
        "missing_arg",
        "invalid_arg",
        "not_found",
        "upstream_error",
    })

    def __init__(self, code: str, message: str):
        if code not in self.VALID_CODES:
            raise ValueError(f"Unknown TkError code: {code}. Valid: {sorted(self.VALID_CODES)}")
        self.code = code
        super().__init__(f"[{code}] {message}")


READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    idempotentHint=True,
    destructiveHint=False,
    openWorldHint=True,  # live trybunal.gov.pl
)


mcp = FastMCP(name="tk-mcp", instructions=INSTRUCTIONS)


# ---------- helpers ----------


def _require_query(query: str) -> str:
    q = str(query).strip()
    if not q:
        raise TkError("missing_arg", "Parametr `query` jest wymagany (np 'K 15/24' albo 'emerytalny').")
    return q


def _require_path(path: str) -> str:
    p = str(path).strip()
    if not p:
        raise TkError(
            "missing_arg",
            "Parametr `path` jest wymagany (np '/postepowanie-i-orzeczenia/wyroki/art/4844-...').",
        )
    return p


def _validate_page(page: int) -> int:
    if not isinstance(page, int) or page < 1:
        raise TkError("invalid_arg", f"`page` musi byc >= 1, dostano {page!r}.")
    return page


def _validate_choice(value: str | None, allowed: tuple[str, ...], field: str) -> str | None:
    if value is None:
        return None
    if value not in allowed:
        raise TkError(
            "invalid_arg",
            f"`{field}` ma nieznana wartosc {value!r}. Dozwolone: {', '.join(allowed)}.",
        )
    return value


async def _fetch(coro) -> tuple[Any, str]:
    """Wykonuje request klienta, mapujac bledy HTTP na kody strukturalne."""
    try:
        return await coro
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise TkError(
                "not_found",
                f"trybunal.gov.pl nie zna tego zasobu (HTTP 404): {exc.request.url}.",
            ) from exc
        raise TkError("upstream_error", f"Blad trybunal.gov.pl: {exc}") from exc
    except httpx.HTTPError as exc:
        raise TkError("upstream_error", f"Blad trybunal.gov.pl: {exc}") from exc


# ---------- TOOL 1: search_judgments ----------


@mcp.tool(annotations=READ_ONLY)
async def search_judgments(
    query: str = "",
    page: int = 1,
    sort: str | None = None,
    filter: str | None = None,
) -> dict:
    """Szuka orzeczen TK w wyszukiwarce trybunal.gov.pl (Solr, `type=7383`).

    Zwraca globalny `count` z naglowka i jedna strone wynikow. Brak naglowka
    licznika albo licznik 0 to `count=0` z pustymi `items` - nie blad.

    Args:
        query: fraza pelnotekstowa (np "K 15/24", "emerytalny")
        page: numer strony, 1-based (default 1)
        sort: "publicationDate+desc" albo "publicationDate+asc"
        filter: faseta, np "signature:K", "category:Wyrok", "modificationDate:lastYear"

    Returns:
        dict: {query, page, sort, filter, count, items: [...], has_more, source_url, retrieved_at}
    """
    t0 = time.monotonic()
    q = _require_query(query)
    page_num = _validate_page(page)
    _validate_choice(sort, ALLOWED_SORTS, "sort")
    _validate_choice(filter, ALLOWED_FILTERS, "filter")

    async with TkClient() as client:
        html, source_url = await _fetch(
            client.search(q, page=page_num, sort=sort, filter=filter)
        )

    count, raw_items = parse_search_fragment(html)
    items = [JudgmentRef(**raw) for raw in raw_items]
    has_more = bool(items) and page_num * len(items) < count

    result = JudgmentSearchResult(
        query=q,
        page=page_num,
        sort=sort,
        filter=filter,
        count=count,
        items=items,
        has_more=has_more,
        source_url=source_url,
    )

    audit.log_event(
        tool="search_judgments",
        params={"query": q, "page": page_num, "sort": sort, "filter": filter},
        result_summary={
            "count": count,
            "page_items": len(items),
            "has_more": has_more,
            "first_title": items[0].title if items else None,
        },
        source_urls=[source_url],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return result.model_dump(mode="json")


# ---------- TOOL 2: get_judgment_text ----------


@mcp.tool(annotations=READ_ONLY)
async def get_judgment_text(path: str = "") -> dict:
    """Pelny tekst orzeczenia TK ze strony trybunal.gov.pl.

    Parser scope'uje sie do kontenera `#content` (nav/naglowek emituja wlasne
    dlugie `<p>`), wiec zwrocone akapity to sklad orzekajacy i uzasadnienie, bez
    boilerplate. Bez PDF, bez JS.

    Args:
        path: URL, sciezka absolutna albo wzgledna, np
            "/postepowanie-i-orzeczenia/wyroki/art/4844-wiek-emerytalny-kobiet-i-mezczyzn"

    Returns:
        JudgmentText jako dict: {url, title, paragraphs, text, char_count, source_url, retrieved_at}
    """
    t0 = time.monotonic()
    p = _require_path(path)

    async with TkClient() as client:
        html, source_url = await _fetch(client.get_judgment(p))

    parsed = parse_judgment_text(html)
    paragraphs = list(parsed["paragraphs"])
    text = "\n\n".join(paragraphs)

    doc = JudgmentText(
        url=source_url,
        title=parsed["title"],
        paragraphs=paragraphs,
        text=text,
        char_count=len(text),
        source_url=source_url,
    )

    audit.log_event(
        tool="get_judgment_text",
        params={"path": p},
        result_summary={
            "title": doc.title,
            "paragraphs": len(doc.paragraphs),
            "char_count": doc.char_count,
        },
        source_urls=[source_url],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return doc.model_dump(mode="json")


# ---------- TOOL 3: tk_coverage ----------


@mcp.tool(annotations=READ_ONLY)
async def tk_coverage() -> Coverage:
    """Declare what this connector covers, how it is sourced, and what it does NOT cover.

    Call this before telling a user that the Constitutional Tribunal record "does not
    contain" something, and whenever a search comes back empty: the absence may be a gap
    in this connector rather than in the TK record. Every gap carries a fallback saying
    where to look instead.

    Returns:
        ``Coverage`` with families, an as-of note, and a non-empty list of known gaps.
    """
    t0 = time.monotonic()
    coverage = build_coverage()
    audit.log_event(
        tool="tk_coverage",
        params={},
        result_summary={"families": len(coverage.families), "gaps": len(coverage.known_gaps)},
        source_urls=[],
        latency_ms=(time.monotonic() - t0) * 1000,
        cache_hit=False,
    )
    return coverage


# ---------- entry point ----------


def main() -> None:
    """Entry point dla stdio MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
