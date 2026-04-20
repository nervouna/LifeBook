"""LLM prompts and tool schemas for extraction and writing."""
from __future__ import annotations

from .extract import EXTRACT_SYSTEM, EXTRACT_TOOL_SCHEMA, build_extract_system, build_extract_tool_schema
from .writer import (
    BACKFILL_SYSTEM,
    BACKFILL_TOOL_SCHEMA,
    CHECKLIST_SYSTEM,
    CONCEPT_SYSTEM,
    CONCEPT_TOOL_SCHEMA,
    CONTENT_SYSTEM,
    DISCUSS_SYSTEM,
    FRAMEWORK_SYSTEM,
    FRAMEWORK_TOOL_SCHEMA,
    SECTION_SYSTEM,
    UPDATE_DRAFT_TOOL,
)

__all__ = [
    "BACKFILL_SYSTEM",
    "BACKFILL_TOOL_SCHEMA",
    "CHECKLIST_SYSTEM",
    "CONCEPT_SYSTEM",
    "CONCEPT_TOOL_SCHEMA",
    "CONTENT_SYSTEM",
    "DISCUSS_SYSTEM",
    "EXTRACT_SYSTEM",
    "EXTRACT_TOOL_SCHEMA",
    "FRAMEWORK_SYSTEM",
    "FRAMEWORK_TOOL_SCHEMA",
    "SECTION_SYSTEM",
    "UPDATE_DRAFT_TOOL",
    "build_extract_system",
    "build_extract_tool_schema",
]
