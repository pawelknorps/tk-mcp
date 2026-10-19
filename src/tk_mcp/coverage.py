"""Element 9 of the MateMatic MCP canon: this connector declares its own coverage.

Knowledge about what a corpus does NOT hold is useless while it lives only as prose
in the server instructions - the model has to remember it and choose to relay it, and
an agent has no way to ask. Here it is callable.

Every gap below is grounded in this connector's own source and tool surface. The list
is deliberately never empty: no legal corpus is complete, so an empty gap list would
mean "nobody checked", not "there are no gaps".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _CoverageBase(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CoverageFamily(_CoverageBase):
    """One data family this connector exposes."""

    name: str = Field(description="Data family, e.g. 'Federal legislation'.")
    tool: str = Field(description="Tool or tools that reach this family.")
    source: str = Field(description="Official source the data comes from.")
    captured_at: str | None = Field(
        default=None,
        description="Date this family was last captured (ISO). None when queried live.",
    )
    live: bool = Field(default=True, description="True when queried live instead of from a snapshot.")


class CoverageGap(_CoverageBase):
    """A known, named hole in this connector's coverage - plus the way around it."""

    id: str = Field(description="Stable gap identifier.")
    family: str = Field(description="Which family the gap belongs to.")
    missing: str = Field(description="What is NOT available through this connector.")
    fallback: str = Field(description="Where to go instead.")


class Coverage(_CoverageBase):
    """What this connector covers, how it is sourced, and what it does not cover."""

    status: Literal["ok", "degraded", "failed"] = "ok"
    as_of_note: str = Field(description="States what the dates mean, and what they do not promise.")
    families: list[CoverageFamily] = Field(default_factory=list)
    known_gaps: list[CoverageGap] = Field(
        default_factory=list,
        description="Never empty. An empty list would mean 'not checked', not 'no gaps'.",
    )


SOURCE = "trybunal.gov.pl (official Constitutional Tribunal site, HTML, no auth)"

AS_OF_NOTE = (
    "Data is queried live against trybunal.gov.pl, so there is no local snapshot date. A "
    "date shown on the site is the site's own key date - not proof that a ruling is valid, "
    "final, or still in force. The connector returns ruling text verbatim and never "
    "adjudicates its legal status."
)

_FAMILIES: list[dict] = [
    {
        "name": "Constitutional Tribunal judgments (wyroki)",
        "tool": "search_judgments",
    },
    {
        "name": "Constitutional Tribunal decisions (postanowienia)",
        "tool": "search_judgments",
    },
    {"name": "Judgment full text", "tool": "get_judgment_text"},
]

_GAPS: list[dict] = [
    {
        "id": "TK-001",
        "family": "Judgment full text",
        "missing": "`search_judgments` returns only links, titles and short snippets from the Solr fragment; the ruling's own text (skład orzekający, uzasadnienie) is not in the search response.",
        "fallback": "Take `href` from the search result and call `get_judgment_text` for the paragraphs scoped to #content.",
    },
    {
        "id": "TK-002",
        "family": "Constitutional Tribunal judgments (wyroki)",
        "missing": "`sitemap.xml` answers HTTP 500, so there is no bulk enumeration of the corpus. A search page shows roughly ten results, and the count heading is global to the query.",
        "fallback": "Page through with `page` (1-based) until `has_more` is false, or narrow with a facet; for a full inventory use the official sources (ipo.trybunal.gov.pl, orzeczenia.trybunal.gov.pl).",
    },
    {
        "id": "TK-003",
        "family": "Constitutional Tribunal judgments (wyroki)",
        "missing": "TK rulings from 2024-2026 sit inside the ongoing ustrojowy dispute about the Tribunal's composition and the validity of its rulings. This connector returns the text verbatim and does NOT adjudicate validity, finality, or whether a given skład was properly appointed.",
        "fallback": "Verify skład orzekający and podstawa prawna against official sources (trybunal.gov.pl, Monitor Polski, ipo.trybunal.gov.pl) before relying on a ruling.",
    },
    {
        "id": "TK-004",
        "family": "Constitutional Tribunal judgments (wyroki)",
        "missing": "`category:Wyrok` / `category:Postanowienie` are this site's own editorial categories, not a legal taxonomy. They classify what the site published, not the formal type of ruling under the TK statute.",
        "fallback": "Read the ruling text (`get_judgment_text`) and the signature: K / Kp / P / U / SK and the disposition are the legal markers, not the site category.",
    },
    {
        "id": "TK-005",
        "family": "Constitutional Tribunal decisions (postanowienia)",
        "missing": "Search results mix document types: teczki sprawy (`/s/...`), komunikat/prasowe pages (`/wiadomosci/...`) and news, alongside real judgments (`/wyroki/art/...`). For a recent signature the result set carries ONLY the case file (`/s/<slug>`) and no judgment link, so there is no mechanical search->full-text path; this holds for older rulings (`K 63/07`) where both links appear and the case page itself links the ruling.",
        "fallback": "Filter by `href`: keep `/wyroki/art/` or `/sprawy-w-trybunale/art/`, then `get_judgment_text`. When only `/s/<slug>` is present, open the case page in a browser - the ruling may not yet be published as a `/wyroki/art/` node.",
    },
    {
        "id": "TK-006",
        "family": "Judgment full text",
        "missing": "The parser extracts `<p>` and `<blockquote>` text from #content. Voting/metadata `<table>` blocks (e.g. the judges' signature table) and any content held only in a PDF attachment are NOT extracted.",
        "fallback": "Read the official page in a browser, or fetch the linked PDF/IPO document outside the connector.",
    },
    {
        "id": "TK-007",
        "family": "Constitutional Tribunal judgments (wyroki)",
        "missing": "`category:Publiczne ogłoszenie orzeczenia` is an ANNOUNCEMENTS facet: for real signatures it returns 0 and must not be used to find judgments. The connector therefore does not offer it as a judgment filter.",
        "fallback": "Use `category:Wyrok` / `category:Postanowienie`; for announcements read the site directly.",
    },
]


def build_coverage() -> Coverage:
    """Assemble the declared coverage for this connector."""
    return Coverage(
        status="ok",
        as_of_note=AS_OF_NOTE,
        families=[CoverageFamily(source=SOURCE, live=True, **f) for f in _FAMILIES],
        known_gaps=[CoverageGap(**g) for g in _GAPS],
    )
