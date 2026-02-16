"""Tests for the workspace-tools MCP server.

Uses FastMCP test client against a temp git repo.
"""

from __future__ import annotations

from pathlib import Path

import pygit2
import pytest
from fastmcp import Client

from mcp_workspace_tools.server import mcp


def _init_test_repo(tmp_path: Path) -> Path:
    """Create a minimal git repo for testing."""
    repo_path = tmp_path / "test-repo"
    repo_path.mkdir()

    pygit2.init_repository(str(repo_path), bare=False)
    repo = pygit2.Repository(str(repo_path))
    repo.config["user.name"] = "Test"
    repo.config["user.email"] = "test@test.com"

    # Create an initial file and commit
    test_dir = repo_path / "apps" / "crm" / "data"
    test_dir.mkdir(parents=True)
    test_file = test_dir / "contact.md"
    test_file.write_text("---\ntype: contact\ntitle: Test\n---\n# Test\n", encoding="utf-8")

    repo.index.read()
    repo.index.add("apps/crm/data/contact.md")
    repo.index.write()
    tree = repo.index.write_tree()
    sig = pygit2.Signature("Test", "test@test.com")
    repo.create_commit("HEAD", sig, sig, "Initialize repo", tree, [])

    return repo_path


@pytest.fixture(autouse=True)
def setup_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a test repo and configure env vars."""
    repo_path = _init_test_repo(tmp_path)
    monkeypatch.setenv("REPO_PATH", str(repo_path))
    monkeypatch.setenv("TENANT_ID", "test")

    # Reset the lazy globals so each test gets a fresh repo
    import mcp_workspace_tools.server as srv

    srv._repo = None
    srv._index = None

    return repo_path


@pytest.fixture
def mcp_server():
    """Return the MCP server instance."""
    return mcp


@pytest.mark.asyncio
async def test_tools_list(mcp_server):
    """Test that all 7 tools are registered."""
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        tool_names = [t.name for t in tools]
        assert "file_read" in tool_names
        assert "file_write" in tool_names
        assert "file_list" in tool_names
        assert "file_delete" in tool_names
        assert "git_commit" in tool_names
        assert "index_query" in tool_names
        assert "skill_validate" in tool_names
        assert len(tool_names) == 7


@pytest.mark.asyncio
async def test_file_read(mcp_server):
    """Test reading an existing file."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("file_read", {"path": "apps/crm/data/contact.md"})
        assert "# Test" in str(result)


@pytest.mark.asyncio
async def test_file_write_and_read(mcp_server):
    """Test writing then reading a file."""
    async with Client(mcp_server) as client:
        write_result = await client.call_tool(
            "file_write",
            {"path": "apps/new-file.md", "content": "# New File\nHello"},
        )
        assert "Written" in str(write_result)

        read_result = await client.call_tool("file_read", {"path": "apps/new-file.md"})
        assert "# New File" in str(read_result)


@pytest.mark.asyncio
async def test_file_list(mcp_server):
    """Test listing files."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("file_list", {"directory": "apps/crm/data"})
        assert "apps/crm/data/contact.md" in str(result)


@pytest.mark.asyncio
async def test_file_delete(mcp_server):
    """Test deleting a file."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("file_delete", {"path": "apps/crm/data/contact.md"})
        assert "Deleted" in str(result)


@pytest.mark.asyncio
async def test_git_commit(mcp_server):
    """Test committing staged changes."""
    async with Client(mcp_server) as client:
        # Write a file to have something to commit
        await client.call_tool(
            "file_write",
            {"path": "test-commit.md", "content": "# Test\n"},
        )
        result = await client.call_tool("git_commit", {"message": "test commit"})
        assert "Committed" in str(result)


@pytest.mark.asyncio
async def test_skill_validate_valid(mcp_server):
    """Test validating a valid skill manifest."""
    manifest_yaml = """
name: test-skill
version: "1.0.0"
description: A test skill
triggers:
  keywords: ["test"]
required_tools:
  - local:file_read
scopes:
  read: ["apps/"]
  write: ["apps/"]
token_cost: 100
"""
    async with Client(mcp_server) as client:
        result = await client.call_tool("skill_validate", {"manifest_yaml": manifest_yaml})
        result_str = str(result)
        assert "valid" in result_str


@pytest.mark.asyncio
async def test_skill_validate_invalid_yaml(mcp_server):
    """Test validating invalid YAML."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("skill_validate", {"manifest_yaml": "{{invalid yaml"})
        result_str = str(result)
        assert "yaml_parse_error" in result_str or "error" in result_str.lower()


@pytest.mark.asyncio
async def test_skill_validate_missing_fields(mcp_server):
    """Test validating a manifest missing required fields."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("skill_validate", {"manifest_yaml": "foo: bar"})
        result_str = str(result)
        assert "valid" in result_str
