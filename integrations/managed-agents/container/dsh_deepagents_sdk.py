"""Managed Deep Agents SDK with project-scoped, broker-approved MCP tools."""
import hashlib
import json
import stat
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from dsh_agent_model import DSHManagedChat

_CONFIG = Path('/opt/dsh/config/managed-mcp.json')
_BRIDGE = Path('/opt/dsh/container/dsh-mcp-broker-stdio.py')
_PINS = (
    (_CONFIG, 'b86499b7b3c39d82ff2037a8dc9b24b97763a7d162528cecd9e13f803073a1d4'),
    (_BRIDGE, '67c9f3bcf31127bc6493435aa4d620a0997844cf70979b05e2363f36d29dc4dc'),
)
_ALIAS = 'pc140032646'
_NAMES = frozenset({'run_python', 'download_file', 'verify_base64'})


def _checked_project(project):
    root = Path(project).resolve(strict=True)
    if not root.is_dir() or not root.is_relative_to(Path('/workspace').resolve()):
        raise ValueError('A private /workspace project is required')
    return root


def _managed_server():
    from deepagents_code.mcp_config import resolve_mcp_server_env

    config_bytes = None
    for path, expected in _PINS:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 65536:
            raise ValueError('Operator-owned managed MCP files required')
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != expected:
            raise ValueError('Managed MCP file digest mismatch')
        if path == _CONFIG:
            config_bytes = body
    server = resolve_mcp_server_env(_ALIAS, json.loads(config_bytes)['mcpServers'][_ALIAS])
    if frozenset(server['allowedTools']) != _NAMES or not server['env']['DSH_ENVIRONMENT']:
        raise ValueError('Managed MCP scope or environment missing')
    return server


@asynccontextmanager
async def _managed_session(root, server):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=server['command'], args=server['args'], cwd=str(root), env=server['env']
    )
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer, read_timeout_seconds=timedelta(seconds=300)) as session:
            await session.initialize()
            yield session


async def list_dsh_mcp_tools(project):
    """Read the installed bridge inventory without constructing an agent or invoking tools."""
    root = _checked_project(project)
    async with _managed_session(root, _managed_server()) as session:
        names = [tool.name for tool in (await session.list_tools()).tools]
    if len(names) != len(_NAMES) or frozenset(names) != _NAMES:
        raise ValueError('Managed MCP tool inventory differs from approved scope')
    return sorted(names)


def _managed_tools(root, server):
    from langchain_core.tools import StructuredTool, ToolException

    async def call(name, arguments):
        async with _managed_session(root, server) as session:
            result = await session.call_tool(name, arguments=arguments)
        if result.isError:
            raise ToolException('Managed MCP operation denied or unavailable. Check the existing DSH Credentials result before retrying.')
        return [block.model_dump(mode='json', exclude_none=True) for block in result.content]

    async def run_python(code: str):
        return await call('run_python', {'code': code})

    async def download_file(filename: str):
        return await call('download_file', {'filename': filename})

    async def verify_base64(data: str, expected_sha256: str):
        return await call('verify_base64', {'data': data, 'expected_sha256': expected_sha256})

    return [
        StructuredTool.from_function(name=f'{_ALIAS}_{function.__name__}', coroutine=function, description=description)
        for function, description in (
            (run_python, 'Run Python through the owner-approved DSH MCP broker.'),
            (download_file, 'Read the base64 bytes of a file through the owner-approved DSH MCP broker.'),
            (verify_base64, 'Compare decoded base64 bytes with an expected SHA-256 locally.'),
        )
    ]


def create_dsh_agent(project, *, checkpointer):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend

    root = _checked_project(project)
    if checkpointer is None:
        raise ValueError('An explicit private per-user checkpointer is required')
    return create_deep_agent(
        model=DSHManagedChat(),
        backend=FilesystemBackend(root_dir=str(root), virtual_mode=True),
        checkpointer=checkpointer,
        interrupt_on={'write_file': True, 'edit_file': True, 'execute': True},
        tools=_managed_tools(root, _managed_server()),
    )
