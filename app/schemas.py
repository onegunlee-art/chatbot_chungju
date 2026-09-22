from __future__ import annotations

from pydantic import BaseModel, Field


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="anonymous", max_length=128)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


class Citation(BaseModel):
    n: int
    title: str
    url: str
    source: str
    trust: str
    published_at: str | None = None
    status: str = "active"


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    unanswered: bool


class IngestRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=500)
