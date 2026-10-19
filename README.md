# tk-mcp

Serwer MCP dla **orzecznictwa Trybunału Konstytucyjnego**: wyszukiwarka wyroków
i postanowień oraz pełny tekst orzeczenia. Źródło: oficjalna strona
`trybunal.gov.pl` (HTML, bez auth).

Strona nie ma API - konektor czyta HTML. Wyszukiwarka to Solr (`type=7383`),
pełny tekst czytamy z kontenera `#content` strony orzeczenia.

## Instalacja

```bash
uv pip install -e ".[dev]"
```

## Narzędzia

| Tool | Opis |
|------|------|
| `search_judgments(query, page, sort, filter)` | wyszukiwarka orzeczeń; `count` = globalna liczba trafień, `items` = jedna strona wyników |
| `get_judgment_text(path)` | pełny tekst orzeczenia (akapity z `#content`, bez PDF) |
| `tk_coverage()` | co konektor pokrywa, a czego nie (każda luka ma `fallback`) |

Fasety (`filter`): `signature:K|Kp|Kpt|P|Pp|SK|U`, `category:Wyrok`,
`category:Postanowienie`, `modificationDate:today|lastWeek|lastMonth|lastYear|all`.
Sortowanie: `publicationDate+desc` / `publicationDate+asc`.

## Uruchomienie

```bash
tk-mcp          # stdio
python -m tk_mcp.server
```

## Rozwój

```bash
pytest
pytest -m smoke -v   # testy online (live trybunal.gov.pl)
ruff check
```

Audit log: `~/.matematic/audit/tk-mcp.jsonl` (override: `TK_MCP_AUDIT_DIR`).
Logowane są metadane wywołań (params_hash, result_summary, source_urls,
latency_ms) - bez pełnych treści orzeczeń.

## Uwagi o źródle

- `type=7383` jest obowiązkowy w wyszukiwarce - bez niego strona zwraca sam szkielet.
- Brak trafień = `count=0`, nie błąd.
- `category:Publiczne ogłoszenie orzeczenia` to faseta *ogłoszeń* (komunikatów),
  nie orzeczeń - dla realnych sygnatur zwraca 0.
- Orzeczenia TK z lat 2024-2026 są częścią sporu ustrojowego: konektor zwraca
  treść verbatim i **nie** rozstrzyga o ważności ani prawidłowości składu.
