"""Shared fixtures and module-level mocks for tests."""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Patch heavy optional dependencies so test collection doesn't fail
# when chromadb / sentence_transformers are not installed.
for mod in (
    "chromadb",
    "chromadb.config",
    "sentence_transformers",
):
    if mod not in sys.modules:
        sys.modules[mod] = MagicMock()
