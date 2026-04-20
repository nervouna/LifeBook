"""Coverage tests for web_search.py line 42."""
from __future__ import annotations

from unittest.mock import MagicMock, patch


class TestWebSearchNoResults:
    def test_empty_results(self, tmp_path):
        from lifebook.web_search import web_search
        from lifebook.config import Config, KnowledgeConfig, LLMConfig, TavilyConfig
        cfg = Config(
            knowledge=KnowledgeConfig(root=tmp_path),
            llm=LLMConfig(),
            feishu=MagicMock(),
            executor=MagicMock(),
            digest=MagicMock(),
            tavily=TavilyConfig(api_key="fake"),
            fetch=MagicMock(),
            logging=MagicMock(),
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("lifebook.web_search.httpx.post", return_value=mock_resp):
            result = web_search("test", cfg)
        assert "没有找到相关结果" in result
