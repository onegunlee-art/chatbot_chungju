"""설정(sources.yaml) 기반 수집기.

충주시청 홈페이지의 게시판 구조는 개편될 수 있으므로, 파이썬 코드를 고치지 않고
YAML 의 CSS 선택자만 바꿔서 대응할 수 있게 만들었다. 선택자가 맞는지는
`python -m app.cli verify <source_id>` 로 실제 응답을 보고 확인한다.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from dateutil import parser as dateparser
from selectolax.parser import HTMLParser
from tenacity import retry, stop_after_attempt, wait_exponential

from app.ingest.base import RawDoc

log = logging.getLogger(__name__)

USER_AGENT = "ChungjuCityBot/0.1 (+public information indexing; contact: 충주시청)"
# 출처의 날짜는 모두 한국 표준시 기준이다. 서버 TZ 와 무관하게 해석이 같도록 고정한다.
KST = ZoneInfo("Asia/Seoul")
_DATE_RE = re.compile(r"(\d{4})[.\-/년\s]+(\d{1,2})[.\-/월\s]+(\d{1,2})")


def parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    m = _DATE_RE.search(text)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        try:
            return datetime(y, mo, d, tzinfo=KST)
        except ValueError:
            return None
    try:
        parsed = dateparser.parse(text, fuzzy=True)
        return parsed.replace(tzinfo=KST) if parsed and parsed.tzinfo is None else parsed
    except (ValueError, OverflowError):
        return None


def _text(node) -> str:
    return node.text(separator="\n", strip=True) if node is not None else ""


class HtmlBoardCollector:
    """목록 페이지 → 상세 페이지 순회형 게시판 수집기."""

    def __init__(self, config: dict) -> None:
        self.source_id: str = config["id"]
        self.cfg = config
        self.sel = config["selectors"]
        self.trust_tier: int = config.get("trust_tier", 1)
        self.category: str | None = config.get("category")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        resp = await client.get(url, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def _list_urls(self) -> list[str]:
        base = self.cfg["list_url"]
        pages = self.cfg.get("pages", 1)
        if pages <= 1 or "{page}" not in base:
            return [base.replace("{page}", "1")]
        return [base.replace("{page}", str(p)) for p in range(1, pages + 1)]

    def _parse_list(self, html: str, page_url: str) -> list[dict]:
        tree = HTMLParser(html)
        items: list[dict] = []
        for row in tree.css(self.sel["row"]):
            link = row.css_first(self.sel["link"])
            if link is None:
                continue
            href = link.attributes.get("href", "")
            if not href or href.startswith("javascript:"):
                # 게시판이 JS 함수로 이동하는 경우: 글번호만 뽑아 상세 URL 템플릿에 끼운다
                num = self._extract_id(href) or self._extract_id(_text(row))
                if not num or "detail_url" not in self.cfg:
                    continue
                url = self.cfg["detail_url"].replace("{id}", num)
            else:
                url = urljoin(page_url, href)
                num = self._extract_id(url) or url

            items.append(
                {
                    "external_id": str(num),
                    "url": url,
                    "title": _text(link) or _text(row.css_first(self.sel.get("title", "td"))),
                    "published_at": parse_date(
                        _text(row.css_first(self.sel["date"])) if self.sel.get("date") else None
                    ),
                }
            )
        return items

    def _extract_id(self, text: str) -> str | None:
        pattern = self.cfg.get("id_pattern", r"(\d{3,})")
        m = re.search(pattern, text or "")
        return m.group(1) if m else None

    def _parse_detail(self, html: str) -> dict:
        tree = HTMLParser(html)
        body_node = tree.css_first(self.sel["body"])
        out = {"body": _text(body_node)}
        if self.sel.get("detail_title"):
            out["title"] = _text(tree.css_first(self.sel["detail_title"]))
        if self.sel.get("department"):
            out["department"] = _text(tree.css_first(self.sel["department"]))
        if self.sel.get("detail_date"):
            out["published_at"] = parse_date(_text(tree.css_first(self.sel["detail_date"])))
        return out

    async def collect(self, limit: int | None = None) -> list[RawDoc]:
        docs: list[RawDoc] = []
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(headers=headers) as client:
            listings: list[dict] = []
            for page_url in self._list_urls():
                try:
                    html = await self._get(client, page_url)
                except httpx.HTTPError as e:
                    log.warning("[%s] 목록 조회 실패 %s: %s", self.source_id, page_url, e)
                    continue
                listings.extend(self._parse_list(html, page_url))

            # 중복 제거 (페이지 경계에서 같은 글이 겹칠 수 있다)
            unique = list({item["external_id"]: item for item in listings}.values())
            if limit:
                unique = unique[:limit]

            sem = asyncio.Semaphore(self.cfg.get("concurrency", 4))

            async def fetch_one(item: dict) -> RawDoc | None:
                async with sem:
                    await asyncio.sleep(self.cfg.get("delay_seconds", 0.3))
                    try:
                        detail_html = await self._get(client, item["url"])
                    except httpx.HTTPError as e:
                        log.warning("[%s] 본문 조회 실패 %s: %s", self.source_id, item["url"], e)
                        return None
                detail = self._parse_detail(detail_html)
                if not detail.get("body"):
                    return None
                return RawDoc(
                    source_id=self.source_id,
                    external_id=item["external_id"],
                    url=item["url"],
                    title=detail.get("title") or item["title"],
                    body=detail["body"],
                    category=self.category,
                    department=detail.get("department"),
                    published_at=detail.get("published_at") or item.get("published_at"),
                    trust_tier=self.trust_tier,
                ).normalized()

            results = await asyncio.gather(*(fetch_one(i) for i in unique))
            docs = [d for d in results if d is not None]
        return docs


class RssCollector:
    """RSS/Atom 피드 수집기."""

    def __init__(self, config: dict) -> None:
        self.source_id: str = config["id"]
        self.cfg = config
        self.trust_tier: int = config.get("trust_tier", 1)
        self.category: str | None = config.get("category")

    async def collect(self, limit: int | None = None) -> list[RawDoc]:
        headers = {"User-Agent": USER_AGENT}
        async with httpx.AsyncClient(headers=headers) as client:
            resp = await client.get(self.cfg["feed_url"], timeout=30.0, follow_redirects=True)
            resp.raise_for_status()
            tree = HTMLParser(resp.text)

        docs: list[RawDoc] = []
        for item in tree.css("item, entry")[: limit or 1000]:
            link_node = item.css_first("link")
            link = _text(link_node) or (link_node.attributes.get("href", "") if link_node else "")
            title = _text(item.css_first("title"))
            body = _text(item.css_first("description, content, summary"))
            if not link or not body:
                continue
            docs.append(
                RawDoc(
                    source_id=self.source_id,
                    external_id=_text(item.css_first("guid, id")) or link,
                    url=link,
                    title=title,
                    body=body,
                    category=self.category,
                    published_at=parse_date(_text(item.css_first("pubDate, published, updated"))),
                    trust_tier=self.trust_tier,
                ).normalized()
            )
        return docs


COLLECTOR_TYPES = {"html_board": HtmlBoardCollector, "rss": RssCollector}


def build_collector(config: dict):
    kind = config.get("type", "html_board")
    if kind not in COLLECTOR_TYPES:
        raise ValueError(f"알 수 없는 수집기 종류: {kind}")
    return COLLECTOR_TYPES[kind](config)
