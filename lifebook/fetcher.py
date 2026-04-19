"""URL fetchers: Tavily primary, httpx+readability fallback."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from tavily import TavilyClient

from .config import Config, FetchConfig, TavilyConfig

logger = logging.getLogger(__name__)


@dataclass
class FetchResult:
    ok: bool
    status: str                # "ok" | "needs_clip" | "fetch_failed"
    url: str
    title: str | None = None
    content: str = ""
    via: str = ""              # "tavily" | "httpx" | "skip"
    error: str | None = None


def _domain(url: str) -> str:
    host = urlparse(url).hostname or ""
    return host.lower().lstrip("www.")


def _should_skip(url: str, skip_domains: list[str]) -> bool:
    host = urlparse(url).hostname or ""
    for d in skip_domains:
        if host == d or host.endswith("." + d):
            return True
    return False


def _extract_title_from_markdown(md: str) -> str | None:
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()
    return None


class Fetcher:
    def __init__(self, tavily_cfg: TavilyConfig, fetch_cfg: FetchConfig):
        self.tavily_cfg = tavily_cfg
        self.fetch_cfg = fetch_cfg
        self._tavily = TavilyClient(api_key=tavily_cfg.api_key) if tavily_cfg.api_key else None

    def fetch(self, url: str) -> FetchResult:
        if _should_skip(url, self.fetch_cfg.skip_domains):
            logger.info("skip domain, needs clipper: %s", url)
            return FetchResult(
                ok=False, status="needs_clip", url=url, via="skip",
                error=f"domain in skip list ({_domain(url)}); use Web Clipper",
            )

        # Try Tavily first
        if self._tavily:
            try:
                r = self._tavily.extract(
                    urls=[url],
                    extract_depth=self.tavily_cfg.extract_depth,
                    format="markdown",
                )
                results = r.get("results") or []
                if results:
                    item = results[0]
                    raw = item.get("raw_content") or ""
                    title = item.get("title") or _extract_title_from_markdown(raw)
                    if raw.strip():
                        return FetchResult(
                            ok=True, status="ok", url=url, title=title,
                            content=raw, via="tavily",
                        )
                logger.warning("tavily returned empty for %s; failed=%s", url, r.get("failed_results"))
            except Exception as e:
                logger.warning("tavily error for %s: %s", url, e)

        # Fallback to httpx + readability
        if self.fetch_cfg.enable_fallback:
            try:
                return self._httpx_fetch(url)
            except Exception as e:
                logger.warning("httpx fallback error for %s: %s", url, e)
                return FetchResult(
                    ok=False, status="fetch_failed", url=url, via="httpx",
                    error=str(e),
                )

        return FetchResult(
            ok=False, status="fetch_failed", url=url, via="tavily",
            error="tavily returned no content and fallback disabled",
        )

    def _httpx_fetch(self, url: str) -> FetchResult:
        from readability import Document
        from bs4 import BeautifulSoup

        with httpx.Client(
            headers={"User-Agent": self.fetch_cfg.user_agent},
            timeout=self.fetch_cfg.timeout,
            follow_redirects=True,
        ) as c:
            r = c.get(url)
            r.raise_for_status()
            html = r.text

        doc = Document(html)
        title = doc.short_title()
        summary_html = doc.summary(html_partial=True)
        text = BeautifulSoup(summary_html, "lxml").get_text("\n").strip()
        if not text:
            return FetchResult(
                ok=False, status="fetch_failed", url=url, via="httpx",
                error="readability produced empty content",
            )
        return FetchResult(
            ok=True, status="ok", url=url, title=title or None,
            content=text, via="httpx",
        )


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
    if not cfg.tavily.api_key:
        return "搜索失败: Tavily API key 未配置"
    client = TavilyClient(api_key=cfg.tavily.api_key)
    try:
        resp = client.search(query=query, max_results=max_results)
        results = resp.get("results", [])
        if not results:
            return "没有找到相关结果。"
        parts = []
        for r in results:
            parts.append(f"{r.get('title', '')}\n{r.get('url', '')}\n{r.get('content', '')}\n")
        return "\n".join(parts)
    except Exception as e:
        logger.error("web search failed: %s", e)
        return f"搜索失败: {e}"
