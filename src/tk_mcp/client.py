"""httpx async client dla trybunal.gov.pl (Trybunal Konstytucyjny).

Strona jest HTML-only (brak API i brak JSON), wiec klient zwraca surowy tekst
odpowiedzi, a parsowanie zyje w `models.py`. Wysylamy UA przegladarki - strona
odrzuca czesc botowych UA (stan 2026-10-19). Wszystko read-only.
"""

from __future__ import annotations

import asyncio
from typing import Any, Self

import httpx

from . import BASE_URL, USER_AGENT
from .models import SEARCH_TYPE


def build_search_params(
    query: str,
    page: int = 1,
    sort: str | None = None,
    filter: str | None = None,
) -> dict[str, Any]:
    """Buduje parametry zapytania /wyszukiwarka (czysta funkcja, testowalna offline).

    `type=7383` jest obowiazkowy. `tx_solr[page]` dodajemy tylko dla page > 1
    (page=1 to domyslna strona). `tx_solr[filter][0]` to pierwszy (i jedyny)
    facet - Solr indeksuje filtry od zera.
    """
    params: dict[str, Any] = {
        "tx_solr[q]": query,
        "type": SEARCH_TYPE,
    }
    if page > 1:
        params["tx_solr[page]"] = page
    if sort:
        params["tx_solr[sort]"] = sort
    if filter:
        params["tx_solr[filter][0]"] = filter
    return params


def judgment_path(path: str) -> str:
    """Normalizuje wejscie `get_judgment` do sciezki/URL-a z beginning slash."""
    p = str(path).strip()
    if p.startswith(("http://", "https://")):
        return p
    return p if p.startswith("/") else f"/{p}"


class TkClient:
    """Async HTTP client dla trybunal.gov.pl.

    Uzywaj jako async context manager:
        async with TkClient() as c:
            html, url = await c.search("K 15/24")
    """

    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html",
            },
            timeout=timeout,
            follow_redirects=True,
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(
        self,
        url: str,
        params: dict | None = None,
        max_retries: int = 3,
    ) -> tuple[str, str]:
        """GET + TEXT z retry/backoff na 429/503. 404 leci jako HTTPStatusError.

        Returns:
            (html, full_url)
        """
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                resp = await self._client.get(url, params=params)
            except httpx.RequestError as exc:
                last_exc = exc
                await asyncio.sleep(2**attempt)
                continue

            if resp.status_code in (429, 503):
                wait = resp.headers.get("Retry-After")
                try:
                    delay = float(wait) if wait is not None else 2**attempt
                except ValueError:
                    delay = 2**attempt
                await asyncio.sleep(min(delay, 60.0))
                continue

            resp.raise_for_status()
            return resp.text, str(resp.request.url)

        if last_exc is not None:
            raise last_exc
        raise httpx.HTTPError(f"Failed after {max_retries} retries: {url}")

    # ---------- wyszukiwarka ----------

    async def search(
        self,
        query: str,
        page: int = 1,
        sort: str | None = None,
        filter: str | None = None,
    ) -> tuple[str, str]:
        """GET /wyszukiwarka - fragment HTML z wynikami (Solr, `type=7383`).

        Returns:
            (html_fragment, source_url)
        """
        params = build_search_params(query, page=page, sort=sort, filter=filter)
        return await self._get("/wyszukiwarka", params=params)

    # ---------- orzeczenie ----------

    async def get_judgment(self, path: str) -> tuple[str, str]:
        """GET strony orzeczenia (pelny HTML z #content).

        `path` moze byc pelnym URL-em, sciezka absolutna albo wzgledna.

        Returns:
            (html, source_url)
        """
        return await self._get(judgment_path(path))
