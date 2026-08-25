"""差旅助手的 MCP 工具服务器。

第一阶段只提供天气工具，先独立验证 MCP Server 和 Tool，暂不接入聊天路由。
"""

import asyncio
import json
from urllib.parse import quote
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("travel-tools")


def _fetch_weather(city: str) -> dict:
    url = f"https://wttr.in/{quote(city)}?format=j1"
    request = Request(url, headers={"User-Agent": "travel-assistant/0.1"})
    with urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


@mcp.tool()
async def get_weather(city: str) -> dict:
    """查询指定城市的当前天气和未来三天预报。"""
    city = city.strip()
    if not city:
        return {"success": False, "error": "city 不能为空"}

    try:
        data = await asyncio.to_thread(_fetch_weather, city)
        current = data.get("current_condition", [{}])[0]
        description = (current.get("weatherDesc") or [{}])[0].get("value", "")
        forecast = []
        for day in data.get("weather", [])[:3]:
            forecast.append(
                {
                    "date": day.get("date"),
                    "min_temp_c": day.get("mintempC"),
                    "max_temp_c": day.get("maxtempC"),
                }
            )
        return {
            "success": True,
            "city": city,
            "current": {
                "description": description,
                "temp_c": current.get("temp_C"),
                "humidity": current.get("humidity"),
            },
            "forecast": forecast,
            "source": "https://wttr.in",
        }
    except Exception as exc:
        return {
            "success": False,
            "city": city,
            "error": f"天气查询失败：{exc}",
            "source": "https://wttr.in",
        }


def _search_web(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS

    raw_results = DDGS().text(
        query,
        max_results=max_results,
        safesearch="on",
        region="cn-zh",
        backend="auto",
    )
    results = []
    for item in raw_results:
        results.append(
            {
                "title": item.get("title", ""),
                "snippet": item.get("body", ""),
                "url": item.get("href", ""),
            }
        )
    return results


@mcp.tool()
async def search_web(query: str, max_results: int = 5) -> dict:
    """搜索公开网页，返回标题、摘要和链接。"""
    query = query.strip()
    if not query:
        return {"success": False, "error": "query 不能为空"}

    max_results = max(1, min(max_results, 10))
    try:
        results = await asyncio.to_thread(_search_web, query, max_results)
        return {
            "success": bool(results),
            "query": query,
            "results": results,
            "source": "DDGS",
            "error": None if results else "未找到相关结果",
        }
    except Exception as exc:
        return {
            "success": False,
            "query": query,
            "results": [],
            "source": "DDGS",
            "error": f"网页搜索失败：{exc}",
        }


if __name__ == "__main__":
    mcp.run(transport="stdio")
