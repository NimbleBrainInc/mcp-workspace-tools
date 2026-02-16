"""End-to-end tests for MCPB bundle deployment.

Builds the workspace-tools bundle, deploys it in a Docker container,
and verifies health, tool listing, and tool invocation over HTTP.

Prerequisites: Docker running, mcpb CLI installed.
"""

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest
import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pytest_httpserver import HTTPServer
from testcontainers.core.container import DockerContainer
from testcontainers.core.waiting_utils import wait_for_logs

from .conftest import (
    BASE_IMAGE,
    BUNDLE_NAME,
    CONTAINER_PORT,
    PROJECT_ROOT,
    PYTHON_VERSION,
)

# Map Docker arch to uv --python-platform values
_DOCKER_ARCH_TO_UV_PLATFORM = {
    "x86_64": "x86_64-unknown-linux-gnu",
    "aarch64": "aarch64-unknown-linux-gnu",
}


def _detect_docker_platform() -> str:
    """Detect the Docker daemon's architecture and return a uv platform string."""
    result = subprocess.run(
        ["docker", "info", "--format", "{{.Architecture}}"],
        capture_output=True,
        text=True,
    )
    arch = result.stdout.strip()
    platform = _DOCKER_ARCH_TO_UV_PLATFORM.get(arch)
    if not platform:
        raise RuntimeError(
            f"Unsupported Docker architecture: {arch}. "
            f"Supported: {list(_DOCKER_ARCH_TO_UV_PLATFORM.keys())}"
        )
    return platform


def build_bundle(output_dir: Path) -> Path:
    """Build MCPB bundle with Linux-compatible deps."""
    build_dir = output_dir / "build"
    shutil.copytree(
        PROJECT_ROOT,
        build_dir,
        ignore=shutil.ignore_patterns(".venv", ".git", "*.pyc", "__pycache__", "e2e"),
    )

    deps_dir = build_dir / "deps"
    if deps_dir.exists():
        shutil.rmtree(deps_dir)

    docker_platform = _detect_docker_platform()
    result = subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--target",
            str(deps_dir),
            "--python-platform",
            docker_platform,
            "--python-version",
            PYTHON_VERSION,
            ".",
        ],
        capture_output=True,
        text=True,
        cwd=build_dir,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Dep vendoring failed: {result.stderr}")

    manifest = json.loads((build_dir / "manifest.json").read_text())
    version = manifest["version"]

    bundle_path = output_dir / f"{BUNDLE_NAME}-v{version}.mcpb"
    result = subprocess.run(
        ["mcpb", "pack", str(build_dir), str(bundle_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Bundle build failed: {result.stderr}")

    if not bundle_path.exists():
        raise RuntimeError(f"Bundle not found at {bundle_path}")

    return bundle_path


@pytest.fixture(scope="module")
def bundle_path():
    """Build the MCPB bundle once for all tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = build_bundle(Path(tmpdir))
        content = path.read_bytes()
        yield path.name, content


@pytest.fixture(scope="module")
def bundle_server(bundle_path):
    """Serve the bundle over HTTP."""
    bundle_name, bundle_content = bundle_path

    server = HTTPServer(host="0.0.0.0", port=0)
    server.expect_request(f"/{bundle_name}").respond_with_data(
        bundle_content,
        content_type="application/octet-stream",
    )
    server.start()

    yield server

    server.stop()


@pytest.fixture(scope="module")
def mcpb_container(bundle_server, bundle_path):
    """Run the MCPB container with a temp git repo mounted."""
    bundle_name, _ = bundle_path
    bundle_url = f"http://host.docker.internal:{bundle_server.port}/{bundle_name}"

    # Create a temp git repo inside the container via init script
    container = (
        DockerContainer(BASE_IMAGE)
        .with_env("BUNDLE_URL", bundle_url)
        .with_env("REPO_PATH", "/tmp/test-repo")
        .with_env("TENANT_ID", "e2e-test")
        .with_bind_ports(CONTAINER_PORT, None)
        .with_kwargs(extra_hosts={"host.docker.internal": "host-gateway"})
    )

    container.start()

    try:
        # Initialize a git repo inside the container for workspace-tools to use
        container.exec("git init /tmp/test-repo")
        container.exec("git -C /tmp/test-repo config user.name E2E")
        container.exec("git -C /tmp/test-repo config user.email e2e@test.com")

        wait_for_logs(container, "Uvicorn running on", timeout=60)
        time.sleep(1)

        host_port = container.get_exposed_port(CONTAINER_PORT)
        base_url = f"http://localhost:{host_port}"

        for _ in range(30):
            try:
                resp = requests.get(f"{base_url}/health", timeout=2)
                if resp.status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.5)
        else:
            logs = container.get_logs()
            raise RuntimeError(f"Container not healthy. Logs: {logs}")

        yield base_url

    finally:
        container.stop()


def test_health_endpoint(mcpb_container):
    """Test that the health endpoint returns successfully."""
    base_url = mcpb_container

    response = requests.get(f"{base_url}/health", timeout=5)

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "mcp-workspace-tools"


@pytest.mark.asyncio
async def test_mcp_tools_list(mcpb_container):
    """Test that the MCP tools/list endpoint returns all expected tools."""
    base_url = mcpb_container

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools_response = await session.list_tools()
            tools = tools_response.tools

            assert tools, "No tools returned from MCP server"

            tool_names = {tool.name for tool in tools}
            expected_tools = {
                "file_read",
                "file_write",
                "file_list",
                "file_delete",
                "git_commit",
                "index_query",
                "skill_validate",
            }

            assert expected_tools.issubset(tool_names), (
                f"Missing tools: {expected_tools - tool_names}"
            )

            for tool in tools:
                assert tool.name
                assert tool.description
                assert tool.inputSchema


@pytest.mark.asyncio
async def test_mcp_file_write_and_read(mcpb_container):
    """Test file_write then file_read over MCP."""
    base_url = mcpb_container

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Write a file
            write_result = await session.call_tool(
                "file_write",
                {"path": "e2e-test.md", "content": "# E2E Test\nHello from MCPB!"},
            )
            assert write_result.content
            assert "Written" in write_result.content[0].text

            # Read it back
            read_result = await session.call_tool(
                "file_read",
                {"path": "e2e-test.md"},
            )
            assert read_result.content
            assert "E2E Test" in read_result.content[0].text


@pytest.mark.asyncio
async def test_mcp_skill_validate(mcpb_container):
    """Test skill_validate over MCP."""
    base_url = mcpb_container

    manifest_yaml = (
        "name: test-skill\n"
        'version: "1.0.0"\n'
        "description: A test skill\n"
        "triggers:\n"
        '  keywords: ["test"]\n'
    )

    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "skill_validate",
                {"manifest_yaml": manifest_yaml},
            )
            assert result.content
            text = result.content[0].text
            assert "valid" in text.lower()
