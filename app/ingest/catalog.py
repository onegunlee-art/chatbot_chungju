"""수집 대상 목록(sources.yaml) 읽기.

pipeline.py 와 분리해 둔 이유: `verify` 는 DB 도 임베딩 모델도 쓰지 않는다.
목록만 읽는데 psycopg 와 torch 까지 끌려오면, 노트북에서 선택자 한 번 확인하려고
수 기가바이트를 설치해야 한다. 이 파일은 pyyaml 하나만 필요하다.
"""
from __future__ import annotations

from pathlib import Path

import yaml

SOURCES_PATH = Path(__file__).parent / "sources.yaml"


def load_sources(path: Path | str = SOURCES_PATH) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["sources"]


def active_sources(sources: list[dict] | None = None) -> list[dict]:
    """enabled 이고 verified 인 소스만 실제 수집에 쓴다.

    선택자를 사람이 확인하지 않은 소스가 조용히 쓰레기를 넣는 일을 막는다.
    """
    return [s for s in (sources or load_sources()) if s.get("enabled") and s.get("verified")]


def find_source(source_id: str, sources: list[dict] | None = None) -> dict | None:
    return next((s for s in (sources or load_sources()) if s["id"] == source_id), None)
