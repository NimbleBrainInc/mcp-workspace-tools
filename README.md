# Workspace Tools MCP Server

[![mpak](https://img.shields.io/badge/mpak-registry-blue)](https://mpak.dev/packages/@nimblebraininc/workspace-tools)
[![NimbleBrain](https://img.shields.io/badge/NimbleBrain-nimblebrain.ai-purple)](https://nimblebrain.ai)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Git-backed file operations, commits, full-text search, and skill validation for [NimbleBrain](https://nimblebrain.ai) agents. This server gives agents a structured way to read, write, and commit files in a git repository, query an indexed knowledge base, and validate skill manifests.

This is one of the core MCP servers that powers NimbleBrain's agent runtime. It's open source so you can see exactly what the agent can do, fork it to add your own tools, or use it as a reference for building workspace-style MCP servers.

## Extending

Want to give the agent new capabilities? This server is the right place to add tools that operate on the workspace (the git repo the agent has access to). Some ideas:

- Add a `file_move` or `file_rename` tool
- Add a `git_diff` tool to show uncommitted changes
- Add a `git_log` tool to show commit history
- Add domain-specific query actions to `index_query`
- Add validation tools for your own file formats

Fork this repo, add your tools to `src/mcp_workspace_tools/server.py`, and deploy your custom version.

## Tools

### file_read

Read a file from the repo by relative path.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `string` | Yes | Repo-relative file path |

### file_write

Write content to a file. Creates parent directories and stages the file for commit.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `string` | Yes | Repo-relative file path |
| `content` | `string` | Yes | File content to write |

### file_list

List tracked files in the repo, optionally filtered by directory and glob pattern.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `directory` | `string` | No | Directory prefix to filter by |
| `pattern` | `string` | No | Glob pattern for filenames (default: `*`) |

### file_delete

Delete a file and stage the deletion.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `path` | `string` | Yes | Repo-relative file path |

### git_commit

Commit all staged changes with the given message.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `string` | Yes | Commit message |

### index_query

Query the SQLite index for full-text search and entity resolution.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action` | `string` | Yes | Query action: `search`, `resolve_entity`, `files_by_type`, `files_by_tag` |
| `query` | `string` | No | Search query or entity name |
| `entity_type` | `string` | No | Entity type for resolve/filter |
| `tag` | `string` | No | Tag for files_by_tag |
| `limit` | `integer` | No | Max results (default: 20) |

### skill_validate

Validate a skill manifest YAML string against the schema.

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `manifest_yaml` | `string` | Yes | Full YAML content of a skill manifest |

## Configuration

| Env Var | Required | Description |
|---------|----------|-------------|
| `REPO_PATH` | Yes | Path to the git repository root |
| `TENANT_ID` | No | Tenant identifier (defaults to "default") |

## Development

```bash
git clone https://github.com/NimbleBrainInc/mcp-workspace-tools.git
cd mcp-workspace-tools

# Install dependencies
uv sync --group dev

# Run all checks (format, lint, typecheck, tests)
make check

# Run the server locally (stdio)
uv run python -m mcp_workspace_tools.server

# Run the server locally (HTTP)
make run-http
```

## License

MIT
