"""Tests for the ArXiv collector — all HTTP and extraction calls are mocked."""

from __future__ import annotations

import threading
import xml.etree.ElementTree as ET

import httpx
import pytest

import pulse.collectors.arxiv as arxiv
import pulse.collectors.tavily as tavily
from pulse.models import Source

_DEFAULT_URL = object()


@pytest.fixture(autouse=True)
def _reset_arxiv_request_gate() -> None:
    arxiv._last_arxiv_request_started_at = None
    yield
    arxiv._last_arxiv_request_started_at = None


def _entry(
    paper_id: str,
    *,
    title: str = "  Agentic   Retrieval\nSystems  ",
    summary: str | None = "  An abstract about\nagentic retrieval. ",
    published: str | None = "2025-02-03T10:11:12Z",
    alternate_url: str | None | object = _DEFAULT_URL,
    pdf_url: str | None | object = _DEFAULT_URL,
) -> str:
    if alternate_url is _DEFAULT_URL:
        alternate_url = f"http://arxiv.org/abs/{paper_id}"
    if pdf_url is _DEFAULT_URL:
        pdf_url = f"http://arxiv.org/pdf/{paper_id}"
    summary_xml = f"<summary>{summary}</summary>" if summary is not None else ""
    published_xml = f"<published>{published}</published>" if published is not None else ""
    alternate_xml = (
        f'<link href="{alternate_url}" rel="alternate" type="text/html"/>'
        if alternate_url is not None
        else ""
    )
    pdf_xml = (
        f'<link href="{pdf_url}" rel="related" type="application/pdf" title="pdf"/>'
        if pdf_url is not None
        else ""
    )
    return f"""
    <entry>
      <id>http://arxiv.org/abs/{paper_id}</id>
      <title>{title}</title>
      {published_xml}
      {summary_xml}
      {alternate_xml}
      {pdf_xml}
    </entry>
    """


def _feed(*entries: str) -> bytes:
    return ('<feed xmlns="http://www.w3.org/2005/Atom">' + "".join(entries) + "</feed>").encode()


class _Response:
    def __init__(self, content: bytes, *, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.request = httpx.Request("GET", arxiv.ARXIV_API_URL)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


def _mock_search(
    monkeypatch,
    content: bytes,
    *,
    extracted: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    http_calls: list[dict] = []
    extract_calls: list[dict] = []

    def fake_get(url, **kwargs):
        http_calls.append({"url": url, **kwargs})
        return _Response(content)

    def fake_extract(urls, **kwargs):
        extract_calls.append({"urls": urls, **kwargs})
        return extracted or {}

    monkeypatch.setattr(arxiv.httpx, "get", fake_get)
    monkeypatch.setattr(arxiv, "extract_content", fake_extract)
    return http_calls, extract_calls


def test_build_arxiv_query_converts_terms_phrases_fields_and_exclusions() -> None:
    original = 'RAG "tool use" -survey -ti:"position paper" cat:cs.AI'

    converted = arxiv.build_arxiv_query(original)

    assert converted == (
        'all:RAG AND all:"tool use" AND cat:cs.AI ANDNOT all:survey ANDNOT ti:"position paper"'
    )
    assert original == 'RAG "tool use" -survey -ti:"position paper" cat:cs.AI'


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("agentic RAG", "all:agentic AND all:RAG"),
        ('"graph   neural networks"', 'all:"graph neural networks"'),
        ("au:Hinton abs:transformers", "au:Hinton AND abs:transformers"),
        ("topic -survey -cat:stat.ML", "all:topic ANDNOT all:survey ANDNOT cat:stat.ML"),
        ("ALL:agents TI:planning", "all:agents AND ti:planning"),
    ],
)
def test_build_arxiv_query_rules(query: str, expected: str) -> None:
    assert arxiv.build_arxiv_query(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        '"unterminated',
        '""',
        "-",
        "--survey",
        "site:arxiv.org",
        "foo AND bar",
        "foo OR bar",
        "foo ANDNOT bar",
        "-survey",
        "foo bare,comma",
        "ti:",
        '"bad\\phrase"',
    ],
)
def test_build_arxiv_query_rejects_invalid_inputs(query: str) -> None:
    with pytest.raises(ValueError):
        arxiv.build_arxiv_query(query)


def test_parse_valid_record_normalizes_shared_source_item_fields() -> None:
    papers = arxiv.parse_arxiv_feed(_feed(_entry("2502.01234v2")), max_results=10)

    assert len(papers) == 1
    item = papers[0].item
    assert item.title == "Agentic Retrieval Systems"
    assert item.url == "https://arxiv.org/abs/2502.01234v2"
    assert item.summary == "An abstract about agentic retrieval."
    assert item.published_date == "2025-02-03"
    assert item.score == 0.0
    assert item.source is Source.ARXIV
    assert papers[0].pdf_url == "https://arxiv.org/pdf/2502.01234v2"


def test_canonical_url_prefers_versioned_entry_identifier() -> None:
    papers = arxiv.parse_arxiv_feed(
        _feed(
            _entry(
                "2502.01234v2",
                alternate_url="https://arxiv.org/abs/2502.01234",
            )
        ),
        max_results=10,
    )

    assert papers[0].item.url == "https://arxiv.org/abs/2502.01234v2"


def test_missing_optional_fields_use_safe_defaults() -> None:
    papers = arxiv.parse_arxiv_feed(
        _feed(_entry("2502.01234", summary=None, published=None, pdf_url=None)),
        max_results=10,
    )

    assert papers[0].item.summary == ""
    assert papers[0].item.published_date == ""
    assert papers[0].pdf_url is None


def test_invalid_publication_date_uses_safe_default() -> None:
    papers = arxiv.parse_arxiv_feed(
        _feed(_entry("2502.01234", published="not-a-date")),
        max_results=10,
    )

    assert papers[0].item.published_date == ""


def test_malformed_individual_records_are_skipped() -> None:
    missing_title = _entry("2502.00001", title=" \n ")
    missing_url = _entry(
        "2502.00002",
        alternate_url="https://example.com/not-arxiv",
    ).replace("http://arxiv.org/abs/2502.00002", "https://example.com/no-id")
    valid = _entry("2502.00003", title="Valid")

    papers = arxiv.parse_arxiv_feed(
        _feed(missing_title, missing_url, valid),
        max_results=10,
    )

    assert [paper.item.title for paper in papers] == ["Valid"]


def test_result_bound_is_enforced_after_malformed_records() -> None:
    entries = [_entry(f"2502.{index:05d}", title=f"Paper {index}") for index in range(1, 5)]

    papers = arxiv.parse_arxiv_feed(_feed(*entries), max_results=2)

    assert [paper.item.title for paper in papers] == ["Paper 1", "Paper 2"]


def test_valid_empty_feed_returns_empty_list() -> None:
    assert arxiv.parse_arxiv_feed(_feed(), max_results=10) == []


def test_valid_feed_with_only_malformed_papers_returns_empty_list() -> None:
    assert (
        arxiv.parse_arxiv_feed(
            _feed(_entry("2502.01234", title="")),
            max_results=10,
        )
        == []
    )


def test_invalid_xml_raises_parse_error() -> None:
    with pytest.raises(ET.ParseError):
        arxiv.parse_arxiv_feed(b"<feed>", max_results=10)


def test_non_atom_root_raises_feed_error() -> None:
    with pytest.raises(arxiv.ArxivFeedError):
        arxiv.parse_arxiv_feed(b"<feed></feed>", max_results=10)


def test_atom_error_entry_raises_api_error() -> None:
    error_entry = """
    <entry>
      <id>http://arxiv.org/api/errors#bad_query</id>
      <title>Error</title>
      <summary>bad query</summary>
      <link href="http://arxiv.org/api/errors#bad_query" rel="alternate"/>
    </entry>
    """

    with pytest.raises(arxiv.ArxivAPIError):
        arxiv.parse_arxiv_feed(_feed(error_entry), max_results=10)


def test_search_sends_only_converted_query_and_explicit_timeout(monkeypatch) -> None:
    http_calls, _ = _mock_search(monkeypatch, _feed(), extracted={})
    original = 'agentic "tool use" -survey'

    assert (
        arxiv.search_arxiv_papers(
            original,
            max_results=3,
            pdf_enrichment_limit=0,
        )
        == []
    )

    assert len(http_calls) == 1
    call = http_calls[0]
    assert call["url"] == arxiv.ARXIV_API_URL
    assert call["params"] == {
        "search_query": 'all:agentic AND all:"tool use" ANDNOT all:survey',
        "start": 0,
        "max_results": 3,
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    assert call["timeout"] == 30.0
    assert original == 'agentic "tool use" -survey'


def test_search_waits_three_seconds_between_request_starts(monkeypatch) -> None:
    clock = [100.0]
    sleeps: list[float] = []
    request_starts: list[float] = []

    monkeypatch.setattr(arxiv.time, "monotonic", lambda: clock[0])

    def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock[0] += seconds

    def fake_get(*args, **kwargs):
        request_starts.append(clock[0])
        return _Response(_feed())

    monkeypatch.setattr(arxiv.time, "sleep", fake_sleep)
    monkeypatch.setattr(arxiv.httpx, "get", fake_get)

    arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=0)
    arxiv.search_arxiv_papers("retrieval", pdf_enrichment_limit=0)

    assert request_starts == [100.0, 103.0]
    assert sleeps == [arxiv.ARXIV_REQUEST_INTERVAL_SECONDS]


def test_search_serializes_arxiv_http_connections(monkeypatch) -> None:
    clock = [100.0]
    first_started = threading.Event()
    release_first = threading.Event()
    second_worker_ready = threading.Event()
    second_started = threading.Event()
    call_count = 0
    count_lock = threading.Lock()
    errors: list[BaseException] = []

    monkeypatch.setattr(arxiv.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        arxiv.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    def fake_get(*args, **kwargs):
        nonlocal call_count
        with count_lock:
            call_count += 1
            current_call = call_count
        if current_call == 1:
            first_started.set()
            assert release_first.wait(timeout=2)
        else:
            second_started.set()
        return _Response(_feed())

    def search(query: str, ready: threading.Event | None = None) -> None:
        if ready:
            ready.set()
        try:
            arxiv.search_arxiv_papers(query, pdf_enrichment_limit=0)
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(arxiv.httpx, "get", fake_get)
    first = threading.Thread(target=search, args=("agentic",))
    second = threading.Thread(target=search, args=("retrieval", second_worker_ready))

    first.start()
    assert first_started.wait(timeout=2)
    second.start()
    assert second_worker_ready.wait(timeout=2)
    assert not second_started.wait(timeout=0.05)

    release_first.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert not first.is_alive()
    assert not second.is_alive()
    assert errors == []
    assert call_count == 2
    assert second_started.is_set()


@pytest.mark.parametrize("max_results", [0, 11, -1, 1.5, True])
def test_search_rejects_invalid_max_results(monkeypatch, max_results) -> None:
    monkeypatch.setattr(
        arxiv.httpx,
        "get",
        lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )

    with pytest.raises(ValueError):
        arxiv.search_arxiv_papers("agentic", max_results=max_results)


def test_search_propagates_http_status_error(monkeypatch) -> None:
    monkeypatch.setattr(
        arxiv.httpx,
        "get",
        lambda *args, **kwargs: _Response(_feed(), status_code=503),
    )

    with pytest.raises(httpx.HTTPStatusError):
        arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=0)


def test_search_propagates_timeout(monkeypatch) -> None:
    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(arxiv.httpx, "get", timeout)

    with pytest.raises(httpx.ReadTimeout):
        arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=0)


@pytest.mark.parametrize(
    ("configured_limit", "expected_urls"),
    [
        (-1, 0),
        (0, 0),
        (1, 1),
        (2, 2),
        (99, 2),
    ],
)
def test_pdf_enrichment_limit_is_clamped_and_uses_one_batch(
    monkeypatch,
    configured_limit: int,
    expected_urls: int,
) -> None:
    content = _feed(
        _entry("2502.00001", title="One"),
        _entry("2502.00002", title="Two"),
        _entry("2502.00003", title="Three"),
    )
    _, extract_calls = _mock_search(monkeypatch, content, extracted={})
    original = 'agentic "tool use"'

    arxiv.search_arxiv_papers(original, pdf_enrichment_limit=configured_limit)

    assert len(extract_calls) == (1 if expected_urls else 0)
    if extract_calls:
        assert len(extract_calls[0]["urls"]) == expected_urls
        assert extract_calls[0]["query"] == original
        assert extract_calls[0]["chunks_per_source"] == arxiv.PDF_CHUNKS_PER_SOURCE
        assert extract_calls[0]["timeout"] == arxiv.EXTRACT_TIMEOUT_SECONDS


def test_successful_enrichment_appends_bounded_highlights(monkeypatch) -> None:
    pdf_url = "https://arxiv.org/pdf/2502.00001"
    original_abstract = "An abstract about agentic retrieval."
    _mock_search(monkeypatch, _feed(_entry("2502.00001")), extracted={pdf_url: "x " * 2000})

    items = arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=1)

    assert items[0].summary.startswith(original_abstract + "\n\nPDF highlights: ")
    appended = items[0].summary[len(original_abstract) :]
    assert len(appended) <= arxiv.PDF_APPEND_MAX_CHARS


def test_partial_enrichment_failure_keeps_unenriched_abstract(monkeypatch) -> None:
    first_url = "https://arxiv.org/pdf/2502.00001"
    _mock_search(
        monkeypatch,
        _feed(
            _entry("2502.00001", title="One", summary="Abstract one."),
            _entry("2502.00002", title="Two", summary="Abstract two."),
        ),
        extracted={first_url: "Relevant details."},
    )

    items = arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=2)

    assert items[0].summary == "Abstract one.\n\nPDF highlights: Relevant details."
    assert items[1].summary == "Abstract two."


def test_global_enrichment_failure_keeps_every_abstract(monkeypatch) -> None:
    monkeypatch.setattr(
        arxiv.httpx,
        "get",
        lambda *args, **kwargs: _Response(_feed(_entry("2502.00001"))),
    )

    def fail(*args, **kwargs):
        raise TimeoutError("extract failed")

    monkeypatch.setattr(arxiv, "extract_content", fail)

    items = arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=2)

    assert items[0].summary == "An abstract about agentic retrieval."


def test_missing_tavily_credentials_keep_original_abstract(monkeypatch) -> None:
    original_abstract = "Credential-independent abstract."
    monkeypatch.setattr(
        arxiv.httpx,
        "get",
        lambda *args, **kwargs: _Response(_feed(_entry("2502.00001", summary=original_abstract))),
    )
    monkeypatch.setattr(tavily, "load_dotenv", lambda: None)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    monkeypatch.setattr(
        tavily,
        "TavilyClient",
        lambda *args, **kwargs: pytest.fail("Tavily client must not be created"),
    )

    items = arxiv.search_arxiv_papers("agentic", pdf_enrichment_limit=1)

    assert items[0].summary == original_abstract


@pytest.mark.parametrize("pdf_enrichment_limit", [1.5, True, "2"])
def test_pdf_enrichment_limit_requires_an_integer(monkeypatch, pdf_enrichment_limit) -> None:
    monkeypatch.setattr(
        arxiv.httpx,
        "get",
        lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )

    with pytest.raises(ValueError):
        arxiv.search_arxiv_papers(
            "agentic",
            pdf_enrichment_limit=pdf_enrichment_limit,
        )
