"""Unit tests for the standalone git_ops module."""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest

from mcp_workspace_tools.git_ops import GitRepo


def _init_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    pygit2.init_repository(str(repo_path), bare=False)
    repo = pygit2.Repository(str(repo_path))
    repo.config["user.name"] = "Test"
    repo.config["user.email"] = "test@test.com"

    # Initial file + commit
    (repo_path / "hello.txt").write_text("hello world\n", encoding="utf-8")
    repo.index.read()
    repo.index.add("hello.txt")
    repo.index.write()
    tree = repo.index.write_tree()
    sig = pygit2.Signature("Test", "test@test.com")
    repo.create_commit("HEAD", sig, sig, "init", tree, [])
    return repo_path


@pytest.fixture
def git_repo(tmp_path: Path) -> GitRepo:
    repo_path = _init_repo(tmp_path)
    return GitRepo(str(repo_path), tenant_id="test")


def test_read_file(git_repo: GitRepo):
    content = git_repo.read_file("hello.txt")
    assert content == "hello world\n"


def test_read_file_not_found(git_repo: GitRepo):
    with pytest.raises(FileNotFoundError):
        git_repo.read_file("nonexistent.txt")


def test_write_file_creates_parents(git_repo: GitRepo):
    git_repo.write_file("a/b/c.txt", "nested content")
    assert git_repo.read_file("a/b/c.txt") == "nested content"


def test_write_file_stages(git_repo: GitRepo):
    git_repo.write_file("staged.txt", "staged")
    files = git_repo.list_files()
    assert "staged.txt" in files


def test_list_files_all(git_repo: GitRepo):
    files = git_repo.list_files()
    assert "hello.txt" in files


def test_list_files_directory_filter(git_repo: GitRepo):
    git_repo.write_file("dir/a.md", "a")
    git_repo.write_file("dir/b.txt", "b")
    git_repo.write_file("other/c.md", "c")

    files = git_repo.list_files(directory="dir")
    assert "dir/a.md" in files
    assert "dir/b.txt" in files
    assert "other/c.md" not in files


def test_list_files_pattern_filter(git_repo: GitRepo):
    git_repo.write_file("dir/a.md", "a")
    git_repo.write_file("dir/b.txt", "b")

    files = git_repo.list_files(directory="dir", pattern="*.md")
    assert "dir/a.md" in files
    assert "dir/b.txt" not in files


def test_delete_file(git_repo: GitRepo):
    git_repo.delete_file("hello.txt")
    with pytest.raises(FileNotFoundError):
        git_repo.read_file("hello.txt")


def test_delete_file_not_found(git_repo: GitRepo):
    with pytest.raises(FileNotFoundError):
        git_repo.delete_file("nonexistent.txt")


def test_commit(git_repo: GitRepo):
    git_repo.write_file("new.txt", "new content")
    oid = git_repo.commit("add new file")
    assert len(oid) == 40  # hex SHA


def test_commit_after_delete(git_repo: GitRepo):
    git_repo.delete_file("hello.txt")
    oid = git_repo.commit("delete hello")
    assert len(oid) == 40
