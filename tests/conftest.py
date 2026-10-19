"""Wspolna konfiguracja testow."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolated_audit_log(tmp_path, monkeypatch):
    """Testy nie dopisuja do produkcyjnego audit logu."""
    monkeypatch.setenv("TK_MCP_AUDIT_DIR", str(tmp_path / "audit"))


@pytest.fixture
def fixture_html():
    """Wczytuje surowy HTML z `tests/fixtures`."""

    def _load(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")

    return _load
