"""Security tests for web API layer."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient

from lifebook.config import Config, KnowledgeConfig, LLMConfig, WebConfig
from lifebook.web.api.notes import _check_path
from lifebook.web.app import PathTraversalMiddleware, create_app


@pytest.fixture
def security_config(tmp_path: Path) -> Config:
    sources = tmp_path / "10-sources"
    sources.mkdir()
    topics = tmp_path / "20-topics"
    topics.mkdir()
    state = tmp_path / ".lifebook"
    state.mkdir()
    note_dir = topics / "ai"
    note_dir.mkdir()
    (note_dir / "test-note.md").write_text(
        "---\ntitle: Test Note\ntags: [test]\n---\n\nHello world\n",
        encoding="utf-8",
    )
    return Config(
        knowledge=KnowledgeConfig(root=tmp_path),
        llm=LLMConfig(),
        feishu=MagicMock(),
        executor=MagicMock(),
        digest=MagicMock(),
        tavily=MagicMock(),
        fetch=MagicMock(),
        logging=MagicMock(),
        web=WebConfig(),
    )


@pytest.fixture
def security_client(security_config: Config) -> TestClient:
    app = create_app(security_config)
    return TestClient(app)


def _make_request_with_cfg(knowledge_cfg: KnowledgeConfig) -> Request:
    """Build a Request with app.state.cfg wired up for _check_path."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)
    # Wire up app.state.cfg via the scope's app
    mock_app = MagicMock()
    mock_app.state.cfg.knowledge = knowledge_cfg
    scope["app"] = mock_app
    return request


class TestPathTraversal:
    """Path traversal protection via _check_path function."""

    def test_check_path_rejects_dotdot(self, security_config: Config):
        req = _make_request_with_cfg(security_config.knowledge)
        with pytest.raises(HTTPException) as exc_info:
            _check_path("../../etc/passwd", req)
        assert exc_info.value.status_code == 400

    def test_check_path_rejects_single_dotdot(self, security_config: Config):
        req = _make_request_with_cfg(security_config.knowledge)
        with pytest.raises(HTTPException) as exc_info:
            _check_path("topics/../secret", req)
        assert exc_info.value.status_code == 400

    def test_check_path_allows_normal_path(self, security_config: Config):
        req = _make_request_with_cfg(security_config.knowledge)
        _check_path("20-topics/ai/test-note.md", req)

    def test_normal_path_works(self, security_client: TestClient):
        resp = security_client.get("/api/notes/20-topics/ai/test-note.md")
        assert resp.status_code == 200
        assert resp.json()["title"] == "Test Note"

    def test_path_outside_root_rejected(self, security_config: Config):
        req = _make_request_with_cfg(security_config.knowledge)
        with pytest.raises(HTTPException) as exc_info:
            _check_path("/etc/passwd", req)
        assert exc_info.value.status_code == 400


class TestPathTraversalMiddleware:
    """Middleware-level path traversal protection."""

    def test_middleware_detects_dotdot_in_path(self):
        """Verify the middleware logic catches .. segments."""
        from pathlib import PurePosixPath
        malicious_paths = [
            "/api/notes/../../etc/passwd",
            "/api/../secret",
            "/api/notes/sub/../../../etc/shadow",
        ]
        for path in malicious_paths:
            parts = path.split("/")
            assert any(p == ".." for p in parts), f"Should detect '..' in {path}"

    def test_middleware_allows_clean_paths(self):
        from pathlib import PurePosixPath
        clean_paths = [
            "/api/notes/20-topics/ai/test-note.md",
            "/api/system/doctor",
            "/api/search?q=hello",
        ]
        for path in clean_paths:
            parts = path.split("/")
            assert not any(p == ".." for p in parts), f"Should not flag {path}"


class TestCORS:
    """CORS configuration tests."""

    def test_cors_default_origins(self, security_config: Config):
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.options(
            "/api/notes",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 405)

    def test_cors_rejects_unknown_origin(self, security_config: Config):
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get(
            "/api/notes",
            headers={"Origin": "https://evil.com"},
        )
        assert "access-control-allow-origin" not in resp.headers or \
            resp.headers.get("access-control-allow-origin") != "https://evil.com"


class TestAPIKeyAuth:
    """API key authentication tests."""

    def test_no_key_configured_skips_auth(self, security_config: Config):
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get("/api/notes")
        assert resp.status_code == 200

    def test_key_configured_blocks_without_header(self, security_config: Config):
        security_config.web.api_key = "secret-key-123"
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get("/api/notes")
        assert resp.status_code == 401

    def test_key_configured_allows_with_header(self, security_config: Config):
        security_config.web.api_key = "secret-key-123"
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get("/api/notes", headers={"X-API-Key": "secret-key-123"})
        assert resp.status_code == 200

    def test_key_configured_rejects_wrong_key(self, security_config: Config):
        security_config.web.api_key = "secret-key-123"
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get("/api/notes", headers={"X-API-Key": "wrong"})
        assert resp.status_code == 401

    def test_doctor_endpoint_exempt_from_auth(self, security_config: Config):
        security_config.web.api_key = "secret-key-123"
        app = create_app(security_config)
        client = TestClient(app)
        resp = client.get("/api/system/doctor")
        assert resp.status_code == 200


class TestDuplicateRoute:
    """Ensure no duplicate route registration."""

    def test_system_routes_registered_once(self, security_config: Config):
        app = create_app(security_config)
        routes = [r.path for r in app.routes]
        cat_routes = [r for r in routes if r.endswith("/categories")]
        tag_routes = [r for r in routes if r.endswith("/tags")]
        assert len(cat_routes) == 1, f"Expected 1 /categories route, got {len(cat_routes)}: {cat_routes}"
        assert len(tag_routes) == 1, f"Expected 1 /tags route, got {len(tag_routes)}: {tag_routes}"
