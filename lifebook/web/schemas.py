"""Pydantic request/response models for the web API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class NoteListItem(BaseModel):
    path: str
    title: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    created: str = ""
    status: str = "active"
    summary: str = ""


class NoteDetail(BaseModel):
    path: str
    title: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    created: str = ""
    body: str = ""
    metadata: dict = Field(default_factory=dict)


class NoteUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None
    category: str | None = None
    body: str | None = None


class NoteListResponse(BaseModel):
    items: list[NoteListItem]
    total: int
    page: int
    per_page: int


class InboxItem(BaseModel):
    path: str
    title: str = ""
    status: str = "inbox"
    source_type: str = "manual"
    source: str = ""
    created: str = ""
    error: str | None = None


class InboxListResponse(BaseModel):
    items: list[InboxItem]
    total: int


class InboxIngestRequest(BaseModel):
    url_or_text: str
    source_type: str = "manual"
    title: str | None = None


class SearchResultItem(BaseModel):
    path: str
    title: str
    score: float
    preview: str = ""


class SearchRequest(BaseModel):
    query: str
    limit: int = 10


class SearchResponse(BaseModel):
    results: list[SearchResultItem]
    query: str


class WriterStatus(BaseModel):
    active: bool
    stage: str | None = None
    title: str | None = None


class WriterStartRequest(BaseModel):
    idea: str


class WriterChatRequest(BaseModel):
    message: str


class WriterChatResponse(BaseModel):
    reply: str
    stage: str | None = None


class PodcastGenerateRequest(BaseModel):
    note_path: str


class PodcastGenerateMultiRequest(BaseModel):
    since: str
    limit: int = 10


class StatsResponse(BaseModel):
    topic_count: int
    inbox_count: int
    categories: list[str]
    index_status: str = "unknown"


class DoctorResponse(BaseModel):
    checks: list[dict]
    config_source: str = ""


class CategoryListResponse(BaseModel):
    categories: list[str]


class TagListResponse(BaseModel):
    tags: list[str]


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None
