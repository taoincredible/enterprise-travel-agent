"""当前差旅项目使用的 MCP Client 适配层。"""

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


SERVER_FILE = Path(__file__).resolve().parent / "mcp_server.py"
TRVL_COMMAND = "/opt/homebrew/bin/trvl"


def parse_mcp_text(text: str) -> dict:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed.setdefault("fetched_at", datetime.now().astimezone().isoformat(timespec="seconds"))
        return parsed
    except json.JSONDecodeError:
        lowered = text.lower()
        failed = any(word in lowered for word in ("required", "failed", "error", "blocked", "rate_limit"))
        return {"success": not failed, "text": text, "fetched_at": datetime.now().astimezone().isoformat(timespec="seconds")}


async def call_stdio_mcp_tool_async(
    command: str,
    args: list[str],
    tool_name: str,
    arguments: dict,
    env: dict | None = None,
) -> dict:
    params = StdioServerParameters(
        command=command,
        args=args,
        env=env,
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            try:
                result = await asyncio.wait_for(session.call_tool(tool_name, arguments), timeout=25)
            except asyncio.TimeoutError:
                return {"success": False, "error": "MCP Tool 请求超时（25秒）"}
            if not result.content:
                return {"success": False, "error": "MCP Tool 没有返回内容"}
            return parse_mcp_text(result.content[0].text)


async def call_mcp_tool_async(tool_name: str, arguments: dict) -> dict:
    return await call_stdio_mcp_tool_async(
        command=sys.executable,
        args=[str(SERVER_FILE)],
        tool_name=tool_name,
        arguments=arguments,
    )


async def call_trvl_async(intent: str, params: dict, query: str | None = None) -> dict:
    """调用 trvl 的 travel 总路由，默认禁止浏览器 Cookie 和遥测。"""
    import os

    if not Path(TRVL_COMMAND).exists():
        return {"success": False, "error": f"未找到 trvl：{TRVL_COMMAND}"}
    arguments = {"intent": intent, "params": params}
    if query:
        arguments["query"] = query
    result = await call_stdio_mcp_tool_async(
        command=TRVL_COMMAND,
        args=["mcp"],
        tool_name="travel",
        arguments=arguments,
        env={
            **os.environ,
            "TRVL_NO_BROWSER_COOKIES": "1",
            "TRVL_NO_TELEMETRY": "1",
        },
    )
    result["mcp_server"] = "trvl"
    return result


def call_mcp_tool(tool_name: str, arguments: dict) -> dict:
    return asyncio.run(call_mcp_tool_async(tool_name, arguments))
