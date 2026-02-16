"""Unit tests for the standalone index_query module."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from mcp_workspace_tools.index_query import IndexQuery


@pytest.fixture
def index_db(tmp_path: Path) -> Path:
    """Create a test SQLite index database with FTS."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))

    # Create the files table
    conn.execute("""
        CREATE TABLE files (
            path TEXT PRIMARY KEY,
            content TEXT,
            frontmatter TEXT
        )
    """)

    # Create FTS virtual table
    conn.execute("""
        CREATE VIRTUAL TABLE files_fts USING fts5(path, content)
    """)

    # Insert test data
    rows = [
        (
            "apps/crm/contacts/alice.md",
            "# Alice\nAlice is a sales contact.",
            json.dumps({"type": "contact", "title": "Alice", "tags": ["sales", "vip"]}),
        ),
        (
            "apps/crm/contacts/bob.md",
            "# Bob\nBob is an engineering contact.",
            json.dumps({"type": "contact", "title": "Bob", "tags": ["engineering"]}),
        ),
        (
            "system/skills/greeting.skill/manifest.yaml",
            "name: greeting\nversion: 1.0.0",
            json.dumps({"type": "skill", "title": "Greeting Skill", "tags": ["greeting"]}),
        ),
    ]

    for path, content, frontmatter in rows:
        conn.execute(
            "INSERT INTO files (path, content, frontmatter) VALUES (?, ?, ?)",
            (path, content, frontmatter),
        )
        conn.execute(
            "INSERT INTO files_fts (path, content) VALUES (?, ?)",
            (path, content),
        )

    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def index(index_db: Path) -> IndexQuery:
    return IndexQuery(index_db)


def test_search(index: IndexQuery):
    results = index.search("Alice")
    assert len(results) >= 1
    assert any("alice" in r.path for r in results)


def test_search_no_results(index: IndexQuery):
    results = index.search("zzzznonexistent")
    assert len(results) == 0


def test_search_limit(index: IndexQuery):
    results = index.search("contact", limit=1)
    assert len(results) == 1


def test_resolve_entity(index: IndexQuery):
    results = index.resolve_entity("contact", "Alice")
    assert len(results) >= 1
    assert results[0].frontmatter["title"] == "Alice"


def test_resolve_entity_no_match(index: IndexQuery):
    results = index.resolve_entity("contact", "zzzznonexistent")
    assert len(results) == 0


def test_files_by_type(index: IndexQuery):
    results = index.files_by_type("contact")
    assert len(results) == 2
    paths = {r.path for r in results}
    assert "apps/crm/contacts/alice.md" in paths
    assert "apps/crm/contacts/bob.md" in paths


def test_files_by_type_skill(index: IndexQuery):
    results = index.files_by_type("skill")
    assert len(results) == 1
    assert results[0].frontmatter["title"] == "Greeting Skill"


def test_files_by_tag(index: IndexQuery):
    results = index.files_by_tag("sales")
    assert len(results) == 1
    assert "alice" in results[0].path


def test_files_by_tag_engineering(index: IndexQuery):
    results = index.files_by_tag("engineering")
    assert len(results) == 1
    assert "bob" in results[0].path


def test_files_by_tag_no_match(index: IndexQuery):
    results = index.files_by_tag("nonexistent-tag")
    assert len(results) == 0
