"""psycopg3 커넥션 풀. 애플리케이션 전역에서 하나만 쓴다."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

log = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def _configure(conn: Connection) -> None:
    register_vector(conn)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            max_size=10,
            kwargs={"row_factory": dict_row},
            configure=_configure,
            open=True,
        )
    return _pool


@contextmanager
def connection() -> Iterator[Connection]:
    with get_pool().connection() as conn:
        yield conn


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def apply_schema(schema_path: str = "db/schema.sql") -> None:
    """개발 편의용. 운영에서는 마이그레이션 도구를 쓰는 것을 권장."""
    with open(schema_path, encoding="utf-8") as f:
        sql = f.read()
    with connection() as conn:
        conn.execute(sql)
        conn.commit()
    log.info("schema applied from %s", schema_path)
