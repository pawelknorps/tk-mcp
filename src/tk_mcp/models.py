"""Modele Pydantic v2 + czyste parsery HTML dla tk-mcp.

Strona trybunal.gov.pl nie ma API - konektor czyta HTML i wyciaga z niego
strukture. Parsery (`parse_search_fragment`, `parse_judgment_text`) sa czystymi
funkcjami bez sieci i bez zaleznosci, wiec testy offline jada na fixture'ach.

Parsowanie robimy wylacznie stdlib (`html.parser` + `re`) - bez beautifulsoup/lxml.
"""

from __future__ import annotations

import datetime as _dt
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from . import BASE_URL

# ---------- dozwolone wartosci (walidowane w server.py jako invalid_arg) ----------

#: `tx_solr[sort]` - dwie wartosci, obie zywe na stronie.
ALLOWED_SORTS = ("publicationDate+desc", "publicationDate+asc")

#: `tx_solr[filter][0]` - fasety orzeczen. SWIADOMIE brak `category:Publiczne ogłoszenie
#: orzeczenia`: to faseta *ogloszen* (komunikatow), ktora dla realnych sygnatur zwraca 0.
ALLOWED_FILTERS = (
    "signature:K",
    "signature:Kp",
    "signature:Kpt",
    "signature:P",
    "signature:Pp",
    "signature:SK",
    "signature:U",
    "category:Wyrok",
    "category:Postanowienie",
    "modificationDate:today",
    "modificationDate:lastWeek",
    "modificationDate:lastMonth",
    "modificationDate:lastYear",
    "modificationDate:all",
)

#: Klasy `<p>`, ktore w #content sa boilerplate (metadane, autor, link-switch), nie trescia.
CONTENT_EXCLUDED_P_CLASSES = frozenset({
    "article-meta",
    "last-actualization",
    "article-author",
    "meta",
    "link-switch-wrap",
})

#: Twardy `type=7383` - bez niego /wyszukiwarka zwraca sam szkielet strony, bez wynikow.
SEARCH_TYPE = "7383"


def _utcnow_iso() -> str:
    return datetime.now(_dt.UTC).isoformat(timespec="seconds")


def absolute_url(href: str) -> str:
    """Normalizuje href ze strony do absolutnego URL (wzgledny -> BASE_URL + href)."""
    h = (href or "").strip()
    if not h:
        return ""
    if h.startswith(("http://", "https://")):
        return h
    if h.startswith("/"):
        return f"{BASE_URL}{h}"
    return f"{BASE_URL}/{h}"


class _TextExtractor(HTMLParser):
    """Zbiera sam tekst z fragmentu HTML (bez tagow), z dekodowaniem encji."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._buf: list[str] = []

    def handle_data(self, data: str) -> None:
        self._buf.append(data)

    @property
    def text(self) -> str:
        return "".join(self._buf)


def _strip_tags(html: str) -> str:
    """Usuwa tagi, zostawia tekst (encje dekodowane przez HTMLParser)."""
    ex = _TextExtractor()
    ex.feed(html)
    ex.close()
    return ex.text


def _collapse(text: str) -> str:
    """Zwijanie bialych znakow do pojedynczych spacji + trim."""
    return re.sub(r"\s+", " ", text).strip()


def _class_of(attrs: str) -> str:
    m = re.search(r'class="([^"]*)"', attrs or "")
    return m.group(1).strip() if m else ""


# ---------- modele danych ----------


class JudgmentRef(BaseModel):
    """Jeden wynik z fragmentu HTML /wyszukiwarka."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    href: str = Field(description="URL absolutny wyniku (href ze strony, znormalizowany)")
    title: str = Field(default="", description="tekst <h2> wyniku")
    snippet: str = Field(default="", description="snippet; bywa pusty dla teczek spraw")
    document_id: str = Field(default="", description="atrybut data-document-id")
    document_score: str = Field(default="", description="atrybut data-document-score")
    document_url: str = Field(default="", description="atrybut data-document-url, absolutny")


class JudgmentSearchResult(BaseModel):
    """Wynik `search_judgments` - strona wynikow + globalny licznik trafien."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    query: str
    page: int = 1
    sort: str | None = None
    filter: str | None = None
    count: int = Field(default=0, description="globalna liczba trafien HUDOC/Solr (N z naglowka)")
    items: list[JudgmentRef] = Field(default_factory=list)
    has_more: bool = Field(default=False, description="czy jest kolejna strona")
    source_url: str = Field(default="")
    retrieved_at: str = Field(default_factory=_utcnow_iso)


class JudgmentText(BaseModel):
    """Pelny tekst orzeczenia z `get_judgment_text`."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    url: str = Field(description="URL absolutny orzeczenia")
    title: str = Field(default="", description="tytul artykulu (h1.article-title)")
    paragraphs: list[str] = Field(default_factory=list, description="akapity z #content, po kolapsie bialych znakow")
    text: str = Field(default="", description="wszystkie akapity zlaczone podwojnym newline")
    char_count: int = 0
    source_url: str = Field(default="")
    retrieved_at: str = Field(default_factory=_utcnow_iso)


# ---------- czyste parsery (testowalne offline) ----------


def parse_search_fragment(html: str) -> tuple[int, list[dict[str, Any]]]:
    """Parsuje fragment HTML z /wyszukiwarka.

    Zwraca (count, items):
    - `count` to globalna liczba trafien z naglowka ``Wyniki dla "..." (N)``;
      gdy naglowka nie ma LUB jest ``(0)`` - count == 0, items puste. Brak
      trafien to nie blad.
    - `items` to surowe dict-y jednej strony wynikow (max ~10): href, title,
      snippet, document_id, document_score, document_url.
    """
    count = 0
    heading = re.search(r'<h1[^>]*class="[^"]*section-title[^"]*"[^>]*>(.*?)</h1>', html, re.DOTALL)
    if heading:
        cm = re.search(r"\((\d+)\)", heading.group(1))
        if cm:
            count = int(cm.group(1))

    items: list[dict[str, Any]] = []
    for block in re.findall(r'<li class="article-item">(.*?)</li>', html, re.DOTALL):
        href = re.search(r'href="([^"]*)"', block)
        h2 = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.DOTALL)
        score = re.search(r'data-document-score="([^"]*)"', block)
        doc_id = re.search(r'data-document-id="([^"]*)"', block)
        doc_url = re.search(r'data-document-url="([^"]*)"', block)
        items.append({
            "href": absolute_url(href.group(1)) if href else "",
            "title": _collapse(_strip_tags(h2.group(1))) if h2 else "",
            "snippet": _snippet(block),
            "document_id": doc_id.group(1) if doc_id else "",
            "document_score": score.group(1) if score else "",
            "document_url": absolute_url(doc_url.group(1)) if doc_url else "",
        })
    return count, items


def _snippet(block: str) -> str:
    """Snippet wyniku: pierwszy niepusty, nie-boilerplate `<p>` poza `<h2>`."""
    for m in re.finditer(r"<p([^>]*)>(.*?)</p>", block, re.DOTALL):
        if any(c in CONTENT_EXCLUDED_P_CLASSES for c in _class_of(m.group(1)).split()):
            continue
        text = _collapse(_strip_tags(m.group(2)))
        if text:
            return text
    return ""


class _JudgmentParser(HTMLParser):
    """Wyciaga tytul i akapity TYLKO z kontenera ``<div id="content">``.

    Nav/naglowek strony emituja wlasne, dlugie `<p>` - dlatego liczymy glebokosc
    `<div>` od `id="content"` i zbieramy akapity dopiero wewnatrz. `<blockquote>`
    (cytowany przepis, protokolant) traktujemy jak akapit, bo stoi jako sibling
    `<p>` i niesie tresc wyroku.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_content = False
        self._depth = 0
        self.title = ""
        self._in_title = False
        self._title_buf: list[str] = []
        self.paragraphs: list[str] = []
        self._stack: list[str] = []
        self._buf: list[str] | None = None
        self._skip = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "div":
            if not self.in_content:
                if (a.get("id") or "") == "content":
                    self.in_content = True
                    self._depth = 0
                return
            self._depth += 1
            return

        if not self.in_content:
            return

        if tag == "h1" and not self.title and not self._in_title:
            self._in_title = True
            self._title_buf = []
            return

        if tag in ("p", "blockquote"):
            self._stack.append(tag)
            if len(self._stack) == 1:
                excluded = any(
                    c in CONTENT_EXCLUDED_P_CLASSES for c in (a.get("class") or "").split()
                )
                self._skip = excluded
                self._buf = None if excluded else []

    def handle_data(self, data: str) -> None:
        if not self.in_content:
            return
        if self._in_title:
            self._title_buf.append(data)
        elif self._buf is not None and not self._skip:
            self._buf.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self.in_content:
            self._depth -= 1
            if self._depth < 0:
                self.in_content = False
            return

        if not self.in_content:
            return

        if tag == "h1" and self._in_title:
            self.title = _collapse("".join(self._title_buf))
            self._in_title = False
            return

        if tag in ("p", "blockquote") and self._stack:
            self._stack.pop()
            if not self._stack:
                if self._buf is not None:
                    text = _collapse("".join(self._buf))
                    if text:
                        self.paragraphs.append(text)
                self._buf = None
                self._skip = False


def parse_judgment_text(html: str) -> dict[str, Any]:
    """Parsuje strone orzeczenia, scope'ujac sie do ``<div id="content">``.

    Zwraca {"title": str, "paragraphs": list[str]}. Puste i boilerplate akapity
    (klasy z CONTENT_EXCLUDED_P_CLASSES) sa odrzucane.
    """
    parser = _JudgmentParser()
    parser.feed(html)
    parser.close()
    return {"title": parser.title, "paragraphs": parser.paragraphs}
