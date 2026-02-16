"""Standalone SQLite index query module.

Provides full-text search and entity resolution against an SQLite index
database.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """A full-text search result."""

    path: str
    snippet: str


@dataclass
class EntityResult:
    """An entity query result."""

    path: str
    frontmatter: dict[str, Any]


class IndexQuery:
    """SQLite index query client for full-text search and entity resolution."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        logger.debug("Opened index database at %s", self._db_path)

    def search(self, query: str, limit: int = 20) -> list[SearchResult]:
        """Full-text search across indexed files.

        Args:
            query: Search query string.
            limit: Maximum number of results.

        Returns:
            List of SearchResult with path and snippet.
        """
        try:
            cursor = self._conn.execute(
                "SELECT path, snippet(files_fts, 1, '<b>', '</b>', '...', 32) as snippet "
                "FROM files_fts WHERE files_fts MATCH ? ORDER BY rank LIMIT ?",
                (query, limit),
            )
            return [SearchResult(path=row["path"], snippet=row["snippet"]) for row in cursor]
        except sqlite3.OperationalError as e:
            logger.warning("FTS search failed: %s", e)
            return []

    def resolve_entity(self, entity_type: str, query: str) -> list[EntityResult]:
        """Query entities by type and name.

        Args:
            entity_type: Entity type (e.g., 'contact', 'skill').
            query: Entity name or partial match.

        Returns:
            List of EntityResult with path and frontmatter.
        """
        try:
            cursor = self._conn.execute(
                "SELECT path, frontmatter FROM files "
                "WHERE json_extract(frontmatter, '$.type') = ? "
                "AND (path LIKE ? OR json_extract(frontmatter, '$.title') LIKE ?)",
                (entity_type, f"%{query}%", f"%{query}%"),
            )
            return [
                EntityResult(path=row["path"], frontmatter=_parse_json(row["frontmatter"]))
                for row in cursor
            ]
        except sqlite3.OperationalError as e:
            logger.warning("Entity resolution failed: %s", e)
            return []

    def files_by_type(self, entity_type: str) -> list[EntityResult]:
        """Filter files by entity type.

        Args:
            entity_type: Entity type to filter by.

        Returns:
            List of EntityResult with path and frontmatter.
        """
        try:
            cursor = self._conn.execute(
                "SELECT path, frontmatter FROM files WHERE json_extract(frontmatter, '$.type') = ?",
                (entity_type,),
            )
            return [
                EntityResult(path=row["path"], frontmatter=_parse_json(row["frontmatter"]))
                for row in cursor
            ]
        except sqlite3.OperationalError as e:
            logger.warning("files_by_type failed: %s", e)
            return []

    def files_by_tag(self, tag: str) -> list[EntityResult]:
        """Filter files that contain a specific tag.

        Args:
            tag: Tag to search for in the tags array.

        Returns:
            List of EntityResult with path and frontmatter.
        """
        try:
            cursor = self._conn.execute(
                "SELECT path, frontmatter FROM files "
                "WHERE EXISTS (SELECT 1 FROM json_each(json_extract(frontmatter, '$.tags')) "
                "WHERE value = ?)",
                (tag,),
            )
            return [
                EntityResult(path=row["path"], frontmatter=_parse_json(row["frontmatter"]))
                for row in cursor
            ]
        except sqlite3.OperationalError as e:
            logger.warning("files_by_tag failed: %s", e)
            return []


def _parse_json(raw: str | None) -> dict[str, Any]:
    """Safely parse a JSON string from the database."""
    if not raw:
        return {}
    import json

    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
