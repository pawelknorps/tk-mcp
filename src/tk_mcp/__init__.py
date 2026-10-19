"""tk-mcp - MCP server for the Polish Constitutional Tribunal (Trybunal Konstytucyjny) rulings site."""

__version__ = "0.1.0"
__author__ = "MateMatic"
__license__ = "Apache-2.0"

# trybunal.gov.pl NIE stoi za Cloudflare Bot Management, ale wysylamy UA przegladarki -
# strona odrzuca czesc botowych UA. Stan zweryfikowany 2026-10-19.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
BASE_URL = "https://trybunal.gov.pl"
