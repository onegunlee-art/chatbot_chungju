"""문서 → 청크. 문단 경계를 지키면서 목표 길이에 맞춰 묶는다."""
from __future__ import annotations

import re

_PARA = re.compile(r"\n\s*\n+")
_SENT = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+")

TARGET_CHARS = 700
OVERLAP_CHARS = 120
MAX_CHARS = 1200


def _split_long(text: str) -> list[str]:
    """한 문단이 너무 길면 문장 단위로 쪼갠다."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts: list[str] = []
    buf = ""
    for sent in _SENT.split(text):
        if not sent:
            continue
        if len(buf) + len(sent) + 1 > MAX_CHARS and buf:
            parts.append(buf.strip())
            buf = sent
        else:
            buf = f"{buf} {sent}".strip()
    if buf.strip():
        parts.append(buf.strip())
    return parts


def chunk(title: str, body: str) -> list[str]:
    """제목을 각 청크 앞에 붙여, 청크 단독으로도 무엇에 관한 내용인지 알 수 있게 한다."""
    body = (body or "").strip()
    if not body:
        return []

    pieces: list[str] = []
    for para in _PARA.split(body):
        para = para.strip()
        if para:
            pieces.extend(_split_long(para))

    chunks: list[str] = []
    buf = ""
    for piece in pieces:
        if len(buf) + len(piece) + 2 > TARGET_CHARS and buf:
            chunks.append(buf.strip())
            tail = buf[-OVERLAP_CHARS:] if len(buf) > OVERLAP_CHARS else buf
            buf = f"{tail}\n{piece}"
        else:
            buf = f"{buf}\n\n{piece}".strip()
    if buf.strip():
        chunks.append(buf.strip())

    prefix = f"[{title}]\n" if title else ""
    return [prefix + c for c in chunks]
