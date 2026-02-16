"""Workspace Tools MCP Server.

Git-backed workspace tools for AI agents: file operations, commits,
full-text search, and skill manifest validation.

Environment variables:
    REPO_PATH: Path to the git repository root (required).
    TENANT_ID: Tenant identifier (optional, defaults to "default").
"""

import logging
import os
import sys
from importlib.resources import files
from typing import Any

import yaml
from fastmcp import FastMCP
from jsonschema import Draft7Validator
from starlette.requests import Request
from starlette.responses import JSONResponse

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("mcp_workspace_tools")

mcp = FastMCP("workspace-tools")

# ---------------------------------------------------------------------------
# Lazy initialization for repo and index
# ---------------------------------------------------------------------------

_repo = None
_index = None


def _get_repo():
    """Lazily initialize GitRepo from environment."""
    global _repo
    if _repo is None:
        from .git_ops import GitRepo

        repo_path = os.environ.get("REPO_PATH", "/repo")
        tenant_id = os.environ.get("TENANT_ID", "default")
        _repo = GitRepo(repo_path, tenant_id=tenant_id)
        logger.info("Initialized GitRepo at %s for tenant %s", repo_path, tenant_id)
    return _repo


def _get_index():
    """Lazily initialize IndexQuery from the repo's index database."""
    global _index
    if _index is None:
        from pathlib import Path

        from .index_query import IndexQuery

        repo_path = os.environ.get("REPO_PATH", "/repo")
        db_path = Path(repo_path) / "system" / ".index.db"
        if db_path.exists():
            _index = IndexQuery(db_path)
            logger.info("Initialized IndexQuery at %s", db_path)
        else:
            logger.warning("Index database not found at %s", db_path)
    return _index


# ---------------------------------------------------------------------------
# Health endpoint (for HTTP transport if ever used)
# ---------------------------------------------------------------------------


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse({"status": "healthy", "service": "mcp-workspace-tools"})


# ---------------------------------------------------------------------------
# File tools
# ---------------------------------------------------------------------------


@mcp.tool()
def file_read(path: str) -> str:
    """Read a file from the tenant repo by relative path.

    Args:
        path: Repo-relative file path.

    Returns:
        The file content as a string.
    """
    return _get_repo().read_file(path)


@mcp.tool()
def file_write(path: str, content: str) -> str:
    """Write content to a file in the tenant repo. Creates parent dirs and stages.

    Args:
        path: Repo-relative file path.
        content: File content to write.

    Returns:
        Confirmation message.
    """
    _get_repo().write_file(path, content)
    return f"Written: {path}"


@mcp.tool()
def file_list(directory: str = "", pattern: str = "*") -> list[str]:
    """List tracked files in the repo, optionally filtered by directory and glob.

    Args:
        directory: Directory prefix to filter by.
        pattern: Glob pattern for filenames.

    Returns:
        List of matching file paths.
    """
    return _get_repo().list_files(directory=directory, pattern=pattern)


@mcp.tool()
def file_delete(path: str) -> str:
    """Delete a file from the tenant repo and stage the deletion.

    Args:
        path: Repo-relative file path.

    Returns:
        Confirmation message.
    """
    _get_repo().delete_file(path)
    return f"Deleted: {path}"


# ---------------------------------------------------------------------------
# Git tools
# ---------------------------------------------------------------------------


@mcp.tool()
def git_commit(message: str) -> str:
    """Commit all staged changes with the given message.

    Args:
        message: Commit message.

    Returns:
        Confirmation with commit OID.
    """
    oid = _get_repo().commit(message)
    return f"Committed: {oid}"


# ---------------------------------------------------------------------------
# Index tools
# ---------------------------------------------------------------------------


@mcp.tool()
def index_query(
    action: str,
    query: str = "",
    entity_type: str = "",
    tag: str = "",
    limit: int = 20,
) -> Any:
    """Query the SQLite index. Actions: search, resolve_entity, files_by_type, files_by_tag.

    Args:
        action: Query action to perform.
        query: Search query or entity name.
        entity_type: Entity type for resolve/filter.
        tag: Tag for files_by_tag.
        limit: Max results.

    Returns:
        List of matching results.
    """
    idx = _get_index()
    if idx is None:
        raise RuntimeError("Index not available")

    if action == "search":
        results = idx.search(query, limit=limit)
        return [{"path": r.path, "snippet": r.snippet} for r in results]

    if action == "resolve_entity":
        results = idx.resolve_entity(entity_type, query)
        return [{"path": r.path, "frontmatter": r.frontmatter} for r in results]

    if action == "files_by_type":
        results = idx.files_by_type(entity_type)
        return [{"path": r.path, "frontmatter": r.frontmatter} for r in results]

    if action == "files_by_tag":
        results = idx.files_by_tag(tag)
        return [{"path": r.path, "frontmatter": r.frontmatter} for r in results]

    raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Skill validation
# ---------------------------------------------------------------------------

# Minimal JSON Schema for skill manifest validation (no import from agent models).
# This validates structure without depending on the agent's SkillManifest Pydantic model.
_SKILL_MANIFEST_SCHEMA = {
    "type": "object",
    "required": ["name", "version", "description"],
    "properties": {
        "manifest_version": {"type": "integer", "minimum": 1},
        "name": {"type": "string", "minLength": 1},
        "version": {"type": "string", "minLength": 1},
        "description": {"type": "string", "minLength": 1},
        "triggers": {
            "type": "object",
            "properties": {
                "keywords": {"type": "array", "items": {"type": "string"}},
                "entities": {"type": "array", "items": {"type": "string"}},
                "schedule": {
                    "type": "object",
                    "properties": {
                        "cron": {"type": "string"},
                        "condition": {"type": ["string", "null"]},
                    },
                },
            },
        },
        "required_tools": {"type": "array", "items": {"type": "string"}},
        "scopes": {
            "type": "object",
            "properties": {
                "read": {"type": "array", "items": {"type": "string"}},
                "write": {"type": "array", "items": {"type": "string"}},
            },
        },
        "token_cost": {"type": "integer", "minimum": 0},
    },
}


@mcp.tool()
def skill_validate(manifest_yaml: str) -> dict[str, Any]:
    """Validate a skill manifest YAML string. Returns success or structured errors.

    Call this before writing a manifest.yaml to catch issues early.

    Args:
        manifest_yaml: The full YAML content of a skill manifest to validate.

    Returns:
        Dict with 'valid' bool and either 'manifest' summary or 'errors' list.
    """
    try:
        raw = yaml.safe_load(manifest_yaml)
    except yaml.YAMLError as exc:
        return {
            "valid": False,
            "errors": [{"type": "yaml_parse_error", "message": str(exc)}],
        }

    if not isinstance(raw, dict):
        return {
            "valid": False,
            "errors": [
                {
                    "type": "invalid_structure",
                    "message": f"Expected a YAML mapping, got {type(raw).__name__}",
                }
            ],
        }

    validator = Draft7Validator(_SKILL_MANIFEST_SCHEMA)
    errors = []
    for error in validator.iter_errors(raw):
        errors.append(
            {
                "type": "schema_validation_error",
                "field": ".".join(str(p) for p in error.absolute_path) or "(root)",
                "message": error.message,
            }
        )

    if errors:
        return {"valid": False, "errors": errors}

    return {
        "valid": True,
        "manifest": {
            "name": raw.get("name", ""),
            "version": raw.get("version", ""),
            "description": raw.get("description", ""),
            "triggers": {
                "keywords": raw.get("triggers", {}).get("keywords", []),
                "has_schedule": raw.get("triggers", {}).get("schedule") is not None,
            },
            "required_tools": raw.get("required_tools", []),
            "token_cost": raw.get("token_cost", 0),
        },
    }


# ---------------------------------------------------------------------------
# SKILL.md resource
# ---------------------------------------------------------------------------

try:
    SKILL_CONTENT = files("mcp_workspace_tools").joinpath("SKILL.md").read_text()
except FileNotFoundError:
    SKILL_CONTENT = (
        "Workspace tools for file operations, git commits, search, and skill validation."
    )


@mcp.resource("skill://workspace-tools/usage")
def workspace_tools_skill() -> str:
    """How to effectively use workspace tools."""
    return SKILL_CONTENT


# ---------------------------------------------------------------------------
# Entrypoints
# ---------------------------------------------------------------------------

app = mcp.http_app()

if __name__ == "__main__":
    logger.info("Running in stdio mode")
    mcp.run()
