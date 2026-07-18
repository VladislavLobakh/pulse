"""ArXiv collector — deterministic query conversion, Atom parsing, and enrichment."""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from pulse.collectors.tavily import EXTRACT_TIMEOUT_SECONDS, extract_content
from pulse.logging_config import get_logger
from pulse.models import Source, SourceItem, SourceItemList

logger = get_logger(__name__)

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ARXIV_TIMEOUT_SECONDS = 30.0
ARXIV_REQUEST_INTERVAL_SECONDS = 3.0
MAX_RESULTS = 10
MAX_PDF_ENRICHMENT = 2
PDF_CHUNKS_PER_SOURCE = 3
PDF_APPEND_MAX_CHARS = 1500

ATOM_NAMESPACE = "http://www.w3.org/2005/Atom"
ATOM = f"{{{ATOM_NAMESPACE}}}"
ALLOWED_FIELDS = frozenset({"all", "ti", "au", "abs", "co", "jr", "cat", "rn"})
BOOLEAN_OPERATORS = frozenset({"AND", "OR", "ANDNOT"})

_TOKEN_RE = re.compile(
    r"(?P<exclude>-)?(?:(?P<field>[A-Za-z]+):)?"
    r'(?:"(?P<phrase>[^"]*)"|(?P<bare>[^\s"]+))'
)
_BARE_TERM_RE = re.compile(r"^[\w.+/#-]+$", re.UNICODE)
_ARXIV_ID_RE = re.compile(r"^(?:\d{4}\.\d{4,5}|[A-Za-z.-]+/\d{7})(?:v\d+)?$")
_ARXIV_REQUEST_LOCK = threading.Lock()
_last_arxiv_request_started_at: float | None = None


class ArxivAPIError(RuntimeError):
    """The ArXiv API returned an Atom error entry."""


class ArxivFeedError(ValueError):
    """The response was XML but not an ArXiv Atom feed."""


@dataclass
class _ArxivPaper:
    item: SourceItem
    pdf_url: str | None


def _next_token(query: str, position: int) -> tuple[re.Match[str], int]:
    while position < len(query) and query[position].isspace():
        position += 1
    if position >= len(query):
        raise StopIteration

    match = _TOKEN_RE.match(query, position)
    if match is None:
        raise ValueError("invalid ArXiv query token")
    end = match.end()
    if end < len(query) and not query[end].isspace():
        raise ValueError("invalid ArXiv query token")
    return match, end


def build_arxiv_query(original_query: str) -> str:
    """Convert a small user-query grammar into documented ArXiv syntax."""
    if not isinstance(original_query, str) or not original_query.strip():
        raise ValueError("ArXiv query must not be empty")

    positives: list[str] = []
    exclusions: list[str] = []
    position = 0
    while True:
        try:
            match, position = _next_token(original_query, position)
        except StopIteration:
            break

        field = (match.group("field") or "all").lower()
        if field not in ALLOWED_FIELDS:
            raise ValueError("unsupported ArXiv field prefix")

        phrase = match.group("phrase")
        bare = match.group("bare")
        if phrase is not None:
            value = " ".join(phrase.split())
            if not value or "\\" in value:
                raise ValueError("invalid quoted ArXiv phrase")
            clause = f'{field}:"{value}"'
        else:
            if bare is None or bare.startswith("-") or not _BARE_TERM_RE.fullmatch(bare):
                raise ValueError("invalid bare ArXiv term")
            if bare.upper() in BOOLEAN_OPERATORS:
                raise ValueError("raw Boolean operators are not supported")
            clause = f"{field}:{bare}"

        target = exclusions if match.group("exclude") else positives
        target.append(clause)

    if not positives:
        raise ValueError("ArXiv query requires at least one positive term")

    converted = " AND ".join(positives)
    if exclusions:
        converted += " ANDNOT " + " ANDNOT ".join(exclusions)
    return converted


def _normalize_whitespace(value: str | None) -> str:
    return " ".join((value or "").split())


def _is_arxiv_host(host: str | None) -> bool:
    return bool(host) and (host == "arxiv.org" or host.endswith(".arxiv.org"))


def _arxiv_id_from_url(url: str, path_prefix: str) -> str | None:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme not in {"http", "https"} or not _is_arxiv_host(parts.hostname):
        return None
    if not parts.path.startswith(path_prefix):
        return None
    arxiv_id = parts.path.removeprefix(path_prefix).removesuffix(".pdf").strip("/")
    if not _ARXIV_ID_RE.fullmatch(arxiv_id):
        return None
    return arxiv_id


def _canonical_abs_url(url: str) -> str | None:
    arxiv_id = _arxiv_id_from_url(url, "/abs/")
    return f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else None


def _canonical_pdf_url(url: str) -> str | None:
    arxiv_id = _arxiv_id_from_url(url, "/pdf/")
    return f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else None


def _entry_links(entry: ET.Element) -> list[ET.Element]:
    return list(entry.findall(f"{ATOM}link"))


def _entry_abs_url(entry: ET.Element) -> str | None:
    candidates: list[str] = []
    for link in _entry_links(entry):
        if link.get("rel") == "alternate" and isinstance(link.get("href"), str):
            canonical = _canonical_abs_url(link.get("href", ""))
            if canonical:
                candidates.append(canonical)
    entry_id = entry.findtext(f"{ATOM}id") or ""
    if canonical_id := _canonical_abs_url(entry_id):
        candidates.append(canonical_id)
    return next(
        (url for url in candidates if re.search(r"v\d+$", url)),
        candidates[0] if candidates else None,
    )


def _entry_pdf_url(entry: ET.Element) -> str | None:
    for link in _entry_links(entry):
        if link.get("title") == "pdf" and isinstance(link.get("href"), str):
            canonical = _canonical_pdf_url(link.get("href", ""))
            if canonical:
                return canonical
    return None


def _is_error_url(url: str) -> bool:
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return _is_arxiv_host(parts.hostname) and parts.path == "/api/errors"


def _is_error_entry(entry: ET.Element) -> bool:
    entry_id = entry.findtext(f"{ATOM}id") or ""
    if _is_error_url(entry_id):
        return True
    return any(_is_error_url(link.get("href", "")) for link in _entry_links(entry))


def _published_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.strip().replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return ""


def parse_arxiv_feed(xml_data: str | bytes, *, max_results: int) -> list[_ArxivPaper]:
    root = ET.fromstring(xml_data)
    if root.tag != f"{ATOM}feed":
        raise ArxivFeedError("response root is not an Atom feed")

    entries = root.findall(f"{ATOM}entry")
    if any(_is_error_entry(entry) for entry in entries):
        raise ArxivAPIError("ArXiv returned an error entry")

    papers: list[_ArxivPaper] = []
    for entry in entries:
        title = _normalize_whitespace(entry.findtext(f"{ATOM}title"))
        url = _entry_abs_url(entry)
        if not title or not url:
            continue
        item = SourceItem(
            title=title,
            url=url,
            score=0.0,
            summary=_normalize_whitespace(entry.findtext(f"{ATOM}summary")),
            source=Source.ARXIV,
            published_date=_published_date(entry.findtext(f"{ATOM}published")),
        )
        papers.append(_ArxivPaper(item=item, pdf_url=_entry_pdf_url(entry)))
        if len(papers) == max_results:
            break
    return papers


def _validate_max_results(max_results: int) -> None:
    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer")
    if not 1 <= max_results <= MAX_RESULTS:
        raise ValueError(f"max_results must be between 1 and {MAX_RESULTS}")


def _clamp_pdf_enrichment_limit(pdf_enrichment_limit: int) -> int:
    if isinstance(pdf_enrichment_limit, bool) or not isinstance(pdf_enrichment_limit, int):
        raise ValueError("pdf_enrichment_limit must be an integer")
    return min(max(pdf_enrichment_limit, 0), MAX_PDF_ENRICHMENT)


def _request_arxiv_feed(arxiv_query: str, max_results: int) -> httpx.Response:
    global _last_arxiv_request_started_at

    # The legacy API permits one connection and one request start every three seconds.
    with _ARXIV_REQUEST_LOCK:
        now = time.monotonic()
        if _last_arxiv_request_started_at is not None:
            remaining = ARXIV_REQUEST_INTERVAL_SECONDS - (now - _last_arxiv_request_started_at)
            if remaining > 0:
                time.sleep(remaining)
        _last_arxiv_request_started_at = time.monotonic()
        return httpx.get(
            ARXIV_API_URL,
            params={
                "search_query": arxiv_query,
                "start": 0,
                "max_results": max_results,
                "sortBy": "relevance",
                "sortOrder": "descending",
            },
            headers={"User-Agent": "PULSE/0.1"},
            follow_redirects=True,
            timeout=ARXIV_TIMEOUT_SECONDS,
        )


def _append_pdf_highlights(item: SourceItem, raw_content: str) -> None:
    highlights = _normalize_whitespace(raw_content)
    if not highlights or highlights in item.summary:
        return
    prefix = "\n\nPDF highlights: " if item.summary else "PDF highlights: "
    available = PDF_APPEND_MAX_CHARS - len(prefix)
    appended = prefix + highlights[:available].rstrip()
    if appended != prefix:
        item.summary += appended


def _enrich_papers(papers: list[_ArxivPaper], original_query: str, limit: int) -> None:
    selected = [paper for paper in papers if paper.pdf_url][:limit]
    if not selected:
        return

    urls = [paper.pdf_url for paper in selected if paper.pdf_url]
    try:
        extracted = extract_content(
            urls,
            query=original_query,
            chunks_per_source=PDF_CHUNKS_PER_SOURCE,
            timeout=EXTRACT_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        logger.warning("ArXiv PDF enrichment skipped: %s", type(exc).__name__)
        return

    normalized_extracted = {
        canonical: content
        for url, content in extracted.items()
        if (canonical := _canonical_pdf_url(url)) is not None
    }
    for paper in selected:
        if paper.pdf_url and paper.pdf_url in normalized_extracted:
            _append_pdf_highlights(paper.item, normalized_extracted[paper.pdf_url])


def search_arxiv_papers(
    query: str,
    *,
    max_results: int = MAX_RESULTS,
    pdf_enrichment_limit: int = MAX_PDF_ENRICHMENT,
) -> SourceItemList:
    """Search ArXiv once, normalize valid papers, and optionally enrich a subset."""
    _validate_max_results(max_results)
    enrichment_limit = _clamp_pdf_enrichment_limit(pdf_enrichment_limit)
    arxiv_query = build_arxiv_query(query)

    response = _request_arxiv_feed(arxiv_query, max_results)
    response.raise_for_status()
    papers = parse_arxiv_feed(response.content, max_results=max_results)
    _enrich_papers(papers, query, enrichment_limit)
    return [paper.item for paper in papers]
