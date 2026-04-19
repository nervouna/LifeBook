"""Web search via Tavily API."""
import logging

import httpx

from .config import Config

logger = logging.getLogger(__name__)

WEB_SEARCH_TOOL = {
    "name": "web_search",
    "description": "搜索互联网获取最新信息。当讨论中需要验证事实、补充数据、或查找最新动态时使用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词（建议用英文以获得更好结果）",
            }
        },
        "required": ["query"],
    },
}


def web_search(query: str, cfg: Config, max_results: int = 5) -> str:
    """Search the web via Tavily. Returns formatted results as a string."""
    try:
        resp = httpx.post(
            "https://api.tavily.com/search",
            json={
                "query": query,
                "max_results": max_results,
                "api_key": cfg.tavily.api_key,
            },
            timeout=cfg.tavily.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if not results:
            return "没有找到相关结果。"
        parts = []
        for r in results:
            parts.append(f"{r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}\n")
        return "\n".join(parts)
    except Exception as e:
        logger.error("web search failed: %s", e)
        return f"搜索失败: {e}"
