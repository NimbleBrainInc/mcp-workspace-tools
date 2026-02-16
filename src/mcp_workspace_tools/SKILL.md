# Workspace Tools

## Tool Selection

| Intent | Tool |
|--------|------|
| Read a file | `file_read(path)` |
| Write or create a file | `file_write(path, content)` |
| List files in a directory | `file_list(directory, pattern)` |
| Delete a file | `file_delete(path)` |
| Commit staged changes | `git_commit(message)` |
| Full-text search | `index_query(action="search", query)` |
| Find entities by type | `index_query(action="resolve_entity", entity_type, query)` |
| Find files by type | `index_query(action="files_by_type", entity_type)` |
| Find files by tag | `index_query(action="files_by_tag", tag)` |
| Validate a skill manifest | `skill_validate(manifest_yaml)` |

## Key Patterns

- `file_write` automatically creates parent directories and stages the file for commit.
- `file_delete` stages the deletion. Call `git_commit` afterward to persist.
- Always validate skill manifests with `skill_validate` before writing them.
- `index_query` with action="search" does full-text search across all indexed files.

## Multi-Step Workflows

### Create a new file and commit
1. `file_write(path, content)`
2. `git_commit(message)`

### Search, read, modify
1. `index_query(action="search", query="...")` to find relevant files
2. `file_read(path)` to read the found file
3. `file_write(path, modified_content)` to update
4. `git_commit(message)` to commit

### Create a skill
1. Write manifest YAML string
2. `skill_validate(manifest_yaml)` to check for errors
3. `file_write("system/skills/{name}.skill/manifest.yaml", manifest_yaml)`
4. `file_write("system/skills/{name}.skill/prompts/main.md", prompt_content)`
5. `git_commit("add skill: {name}")`
