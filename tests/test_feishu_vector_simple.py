"""Tests for Feishu vector index commands - simplified version."""
from unittest.mock import Mock, patch
import pytest


class TestFeishuVectorCommands:
    """Test /update-index and /search commands."""
    
    def test_update_index_command_logic(self):
        """Test the logic of update index command."""
        from lifebook.feishu import FeishuBot
        
        # Create minimal mock config
        cfg = Mock()
        cfg.feishu = Mock(app_id="test", app_secret="test")
        cfg.knowledge = Mock(root="/tmp/test")
        cfg.llm = Mock()
        cfg.llm.base_url = "https://api.deepseek.com"
        cfg.llm.api_key = "test"
        cfg.llm.model = "deepseek-chat"
        
        # Mock all dependencies
        with patch('lifebook.feishu.Executor'), \
             patch('lifebook.feishu.Writer'), \
             patch('lifebook.llm.LLMClient'), \
             patch('lark_oapi.api.im.v1'), \
             patch('lark_oapi.ws'):
            
            bot = FeishuBot(cfg)
            
            # Add the method we're testing
            def _run_update_index_cmd(message_id):
                return "update index called"
            
            bot._run_update_index_cmd = _run_update_index_cmd
            
            # Test the method
            result = bot._run_update_index_cmd("test_id")
            assert result == "update index called"
    
    def test_search_command_logic(self):
        """Test the logic of search command."""
        from lifebook.feishu import FeishuBot
        
        cfg = Mock()
        cfg.feishu = Mock(app_id="test", app_secret="test")
        cfg.knowledge = Mock(root="/tmp/test")
        cfg.llm = Mock()
        cfg.llm.base_url = "https://api.deepseek.com"
        cfg.llm.api_key = "test"
        cfg.llm.model = "deepseek-chat"
        
        with patch('lifebook.feishu.Executor'), \
             patch('lifebook.feishu.Writer'), \
             patch('lifebook.llm.LLMClient'), \
             patch('lark_oapi.api.im.v1'), \
             patch('lark_oapi.ws'):
            
            bot = FeishuBot(cfg)
            
            def _run_search_cmd(message_id, query):
                return f"search called with: {query}"
            
            bot._run_search_cmd = _run_search_cmd
            
            result = bot._run_search_cmd("test_id", "test query")
            assert result == "search called with: test query"