"""수집기 공통 자료구조."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

_WS = re.compile(r"[ \t\r\f\v]+")
_NL = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """공백 정규화. 해시 안정성을 위해 수집 직후 반드시 통과시킨다."""
    text = text.replace("\xa0", " ").replace("\u200b", "")
    text = _WS.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _NL.sub("\n\n", text).strip()


def content_hash(title: str, body: str) -> str:
    return hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()


@dataclass
class RawDoc:
    """수집기가 돌려주는 한 건의 문서."""

    source_id: str
    external_id: str
    url: str
    title: str
    body: str
    category: str | None = None
    department: str | None = None
    published_at: datetime | None = None
    valid_until: datetime | None = None
    trust_tier: int = 1
    extra: dict = field(default_factory=dict)

    def normalized(self) -> RawDoc:
        self.title = normalize_text(self.title)
        self.body = normalize_text(self.body)
        return self

    @property
    def hash(self) -> str:
        return content_hash(self.title, self.body)


class Collector(Protocol):
    source_id: str

    async def collect(self, limit: int | None = None) -> list[RawDoc]: ...
