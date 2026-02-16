"""Standalone git operations using pygit2.

Provides file CRUD and commit operations against a local git repository.
"""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path

import pygit2

logger = logging.getLogger(__name__)


class GitRepo:
    """Git repository wrapper for file operations and commits."""

    def __init__(self, repo_path: str, tenant_id: str = "default") -> None:
        self._repo_path = Path(repo_path)
        self._tenant_id = tenant_id
        self._repo = pygit2.Repository(str(self._repo_path))
        logger.debug("Opened git repo at %s (tenant=%s)", repo_path, tenant_id)

    def read_file(self, path: str) -> str:
        """Read a file from the working directory.

        Args:
            path: Repo-relative file path.

        Returns:
            File content as a string.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        full_path = self._repo_path / path
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        return full_path.read_text(encoding="utf-8")

    def write_file(self, path: str, content: str) -> None:
        """Write content to a file, create parent dirs, and stage it.

        Args:
            path: Repo-relative file path.
            content: File content to write.
        """
        full_path = self._repo_path / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        self._repo.index.read()
        self._repo.index.add(path)
        self._repo.index.write()
        logger.debug("Wrote and staged: %s", path)

    def list_files(self, directory: str = "", pattern: str = "*") -> list[str]:
        """List tracked files in the index, filtered by directory and glob.

        Args:
            directory: Directory prefix to filter by.
            pattern: Glob pattern for filenames.

        Returns:
            List of matching repo-relative file paths.
        """
        self._repo.index.read()
        results: list[str] = []
        for entry in self._repo.index:
            entry_path = entry.path
            if directory and not entry_path.startswith(directory.rstrip("/") + "/"):
                if entry_path != directory:
                    continue
            if pattern != "*":
                filename = os.path.basename(entry_path)
                if not fnmatch.fnmatch(filename, pattern):
                    continue
            results.append(entry_path)
        return sorted(results)

    def delete_file(self, path: str) -> None:
        """Delete a file from the working directory and stage the deletion.

        Args:
            path: Repo-relative file path.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        full_path = self._repo_path / path
        if not full_path.is_file():
            raise FileNotFoundError(f"File not found: {path}")
        full_path.unlink()
        self._repo.index.read()
        self._repo.index.remove(path)
        self._repo.index.write()
        logger.debug("Deleted and staged removal: %s", path)

    def commit(self, message: str) -> str:
        """Commit staged changes with the given message.

        Args:
            message: Commit message.

        Returns:
            The commit OID as a hex string.
        """
        self._repo.index.read()
        tree = self._repo.index.write_tree()
        sig = self._repo.default_signature

        parents = []
        try:
            parents = [self._repo.head.target]
        except pygit2.GitError:
            pass  # Initial commit, no parents

        oid = self._repo.create_commit("HEAD", sig, sig, message, tree, parents)
        logger.debug("Committed %s: %s", str(oid), message)
        return str(oid)
