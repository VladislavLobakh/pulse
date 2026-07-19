"""Tests for the newsletter collector — all HTTP calls are mocked, no real feeds."""

from __future__ import annotations

import httpx
import pytest

import pulse.collectors.newsletter as newsletter
from pulse.models import Source

LATENT = newsletter.NEWSLETTER_FEEDS[0]
WILLISON = newsletter.NEWSLETTER_FEEDS[1]


def _rss_item(
    *,
    title: str | None = "  Agentic   Engineering\nReport ",
    link: str | None = "https://www.latent.space/p/agentic-report",
    description: str | None = "<p>About <b>agentic</b> engineering.</p>",
    content: str | None = None,
    pub_date: str | None = "Tue, 03 Feb 2026 10:11:12 GMT",
) -> str:
    parts = ["<item>"]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if link is not None:
        parts.append(f"<link>{link}</link>")
    if description is not None:
        parts.append(f"<description><![CDATA[{description}]]></description>")
    if content is not None:
        parts.append(f"<content:encoded><![CDATA[{content}]]></content:encoded>")
    if pub_date is not None:
        parts.append(f"<pubDate>{pub_date}</pubDate>")
    parts.append("</item>")
    return "".join(parts)


def _rss_feed(*items: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
        "<channel><title>Latent Space</title><link>https://www.latent.space</link>"
        + "".join(items)
        + "</channel></rss>"
    ).encode()


def _atom_entry(
    *,
    title: str | None = "Exploring agentic workflows",
    link: str | None = "https://simonwillison.net/2026/Feb/3/agentic/#atom-everything",
    summary: str | None = "<p>Notes on <em>agentic</em> workflows.</p>",
    updated: str | None = "2026-02-03T10:11:12Z",
) -> str:
    parts = ["<entry><id>tag:simonwillison.net,2026:entry</id>"]
    if title is not None:
        parts.append(f"<title>{title}</title>")
    if link is not None:
        parts.append(f'<link rel="alternate" href="{link}"/>')
    if summary is not None:
        parts.append(f"<summary type='html'>{summary.replace('<', '&lt;')}</summary>")
    if updated is not None:
        parts.append(f"<updated>{updated}</updated>")
    parts.append("</entry>")
    return "".join(parts)


def _atom_feed(*entries: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom"><title>Simon Willison</title>'
        + "".join(entries)
        + "</feed>"
    ).encode()


class _Response:
    def __init__(self, content: bytes, *, status_code: int = 200, url: str = "") -> None:
        self.content = content
        self.status_code = status_code
        self.request = httpx.Request("GET", url or "https://example.com/feed")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "request failed",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )


def _mock_feeds(monkeypatch, responses: dict[str, bytes | int | Exception]) -> list[dict]:
    calls: list[dict] = []

    def fake_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        value = responses[url]
        if isinstance(value, Exception):
            raise value
        if isinstance(value, int):
            return _Response(b"", status_code=value, url=url)
        return _Response(value, url=url)

    monkeypatch.setattr(newsletter.httpx, "get", fake_get)
    return calls


def test_rss_item_normalizes_shared_source_item_fields(monkeypatch) -> None:
    _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(_rss_item()), WILLISON.url: _atom_feed()})

    result = newsletter.fetch_newsletter_items("agentic engineering")

    assert result.failed_feeds == ()
    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "Agentic Engineering Report"
    assert item.url == "https://www.latent.space/p/agentic-report"
    assert item.summary == "[Latent Space] About agentic engineering."
    assert item.published_date == "2026-02-03"
    assert 0.0 < item.score <= 1.0
    assert item.source is Source.NEWSLETTER


def test_atom_entry_normalizes_shared_source_item_fields(monkeypatch) -> None:
    _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(), WILLISON.url: _atom_feed(_atom_entry())})

    result = newsletter.fetch_newsletter_items("agentic workflows")

    assert result.failed_feeds == ()
    assert len(result.items) == 1
    item = result.items[0]
    assert item.title == "Exploring agentic workflows"
    assert item.url == "https://simonwillison.net/2026/Feb/3/agentic/"
    assert item.summary == "[Simon Willison] Notes on agentic workflows."
    assert item.published_date == "2026-02-03"
    assert item.source is Source.NEWSLETTER


def test_full_entry_content_is_preferred_over_short_description(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(
                    description="Read more.",
                    content="<p>Deep dive into quantization for language models.</p>",
                )
            ),
            WILLISON.url: _atom_feed(),
        },
    )

    result = newsletter.fetch_newsletter_items("quantization")

    assert len(result.items) == 1
    item = result.items[0]
    assert item.score == 1.0
    assert item.summary == "[Latent Space] Deep dive into quantization for language models."


def test_entry_without_content_falls_back_to_description(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(_rss_item(description="Only the description mentions llamas.")),
            WILLISON.url: _atom_feed(),
        },
    )

    result = newsletter.fetch_newsletter_items("llamas")

    assert len(result.items) == 1
    assert result.items[0].summary == "[Latent Space] Only the description mentions llamas."


def test_html_entities_are_unescaped_before_summary_and_scoring(monkeypatch) -> None:
    responses = {
        LATENT.url: _rss_feed(_rss_item(content="<p>yesterday&#8217;s agent update</p>")),
        WILLISON.url: _atom_feed(),
    }
    _mock_feeds(monkeypatch, responses)

    result = newsletter.fetch_newsletter_items("yesterday")
    numeric_entity_result = newsletter.fetch_newsletter_items("8217")

    assert result.items[0].summary == "[Latent Space] yesterday’s agent update"
    assert result.items[0].score == 1.0
    assert numeric_entity_result.items == []


def test_missing_title_or_link_skips_entry_but_keeps_siblings(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(title=" \n "),
                _rss_item(link=None, title="No link agentic"),
                _rss_item(title="Valid agentic"),
            ),
            WILLISON.url: _atom_feed(),
        },
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Valid agentic"]
    assert result.failed_feeds == ()


def test_entry_that_raises_is_skipped_without_failing_the_feed(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(title="Broken agentic entry", link="https://www.latent.space/p/broken"),
                _rss_item(title="Healthy agentic entry"),
            ),
            WILLISON.url: _atom_feed(),
        },
    )
    original = newsletter._normalize_entry

    def explode_on_broken(feed, entry, query_tokens):
        if "Broken" in (entry.get("title") or ""):
            raise KeyError("corrupt entry")
        return original(feed, entry, query_tokens)

    monkeypatch.setattr(newsletter, "_normalize_entry", explode_on_broken)

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Healthy agentic entry"]
    assert result.failed_feeds == ()


def test_url_fragment_is_stripped(monkeypatch) -> None:
    _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(), WILLISON.url: _atom_feed(_atom_entry())})

    result = newsletter.fetch_newsletter_items("agentic")

    assert result.items[0].url == "https://simonwillison.net/2026/Feb/3/agentic/"


@pytest.mark.parametrize("link", ["/relative/post", "ftp://example.com/post", "not a url"])
def test_non_absolute_http_links_skip_the_entry(monkeypatch, link: str) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(_rss_item(link=link), _rss_item(title="Valid agentic")),
            WILLISON.url: _atom_feed(),
        },
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Valid agentic"]


@pytest.mark.parametrize("pub_date", [None, "not-a-date"])
def test_missing_or_unparseable_date_uses_safe_default(monkeypatch, pub_date) -> None:
    _mock_feeds(
        monkeypatch,
        {LATENT.url: _rss_feed(_rss_item(pub_date=pub_date)), WILLISON.url: _atom_feed()},
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert result.items[0].published_date == ""


def test_summary_with_feed_prefix_is_bounded_but_scoring_sees_full_text(monkeypatch) -> None:
    long_text = "filler " * 200 + "zephyr"
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(_rss_item(content=long_text, description="Short.")),
            WILLISON.url: _atom_feed(),
        },
    )

    result = newsletter.fetch_newsletter_items("zephyr")

    assert len(result.items) == 1
    item = result.items[0]
    assert item.score == 1.0
    assert len(item.summary) <= newsletter.SUMMARY_MAX_CHARS
    assert item.summary.startswith("[Latent Space] filler")
    assert "zephyr" not in item.summary


@pytest.mark.parametrize(
    ("query", "text", "expected"),
    [
        ("agentic retrieval", "Agentic retrieval systems", 1.0),
        ("agentic quantum", "agentic stuff only", 0.5),
        ("AGENTIC", "shipping agentic tools", 1.0),
        ("agent", "agents everywhere", 1.0),
        ("gpt", "gpts are here", 0.0),
        ("gpt", "plain gpt release", 1.0),
        ("tool-use", "tool use in practice", 1.0),
    ],
)
def test_relevance_score_is_deterministic(query: str, text: str, expected: float) -> None:
    assert newsletter.relevance_score(query, text) == expected


@pytest.mark.parametrize("query", ["", "   ", "the and of", "!!!"])
def test_unscoreable_query_raises_before_http(monkeypatch, query: str) -> None:
    monkeypatch.setattr(
        newsletter.httpx,
        "get",
        lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )

    with pytest.raises(ValueError):
        newsletter.fetch_newsletter_items(query)


def test_stopword_set_is_pinned() -> None:
    assert newsletter._STOPWORDS == {
        "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "to", "with",
    }  # fmt: skip


@pytest.mark.parametrize("stopword", sorted(newsletter._STOPWORDS))
def test_stopwords_do_not_dilute_the_score(stopword: str) -> None:
    assert newsletter.relevance_score(f"{stopword} agents", "agents") == 1.0


def test_zero_score_entries_are_dropped_and_order_is_deterministic(monkeypatch) -> None:
    responses = {
        LATENT.url: _rss_feed(
            _rss_item(title="Alpha only", link="https://www.latent.space/p/1", content="alpha"),
            _rss_item(title="Nothing", link="https://www.latent.space/p/2", content="unrelated"),
        ),
        WILLISON.url: _atom_feed(
            _atom_entry(
                title="Alpha and beta",
                link="https://simonwillison.net/2026/Feb/3/both/",
                summary="alpha beta",
            )
        ),
    }
    _mock_feeds(monkeypatch, responses)

    first = newsletter.fetch_newsletter_items("alpha beta")
    second = newsletter.fetch_newsletter_items("alpha beta")

    assert [item.title for item in first.items] == ["Alpha and beta", "Alpha only"]
    assert [item.score for item in first.items] == [1.0, 0.5]
    assert first == second


def test_score_ties_keep_feed_configuration_order(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(title="Latent agentic", link="https://www.latent.space/p/tie")
            ),
            WILLISON.url: _atom_feed(
                _atom_entry(title="Willison agentic", link="https://simonwillison.net/tie/")
            ),
        },
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Latent agentic", "Willison agentic"]


def test_duplicate_canonical_urls_keep_first_feed_item(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(title="Latent agentic copy", link="https://example.com/post/")
            ),
            WILLISON.url: _atom_feed(
                _atom_entry(
                    title="Willison agentic copy",
                    link="https://example.com/post#atom-everything",
                )
            ),
        },
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Latent agentic copy"]
    assert result.items[0].summary.startswith("[Latent Space]")


def test_irrelevant_duplicate_does_not_hide_later_relevant_item(monkeypatch) -> None:
    _mock_feeds(
        monkeypatch,
        {
            LATENT.url: _rss_feed(
                _rss_item(
                    title="Irrelevant copy",
                    link="https://example.com/post/",
                    content="unrelated",
                )
            ),
            WILLISON.url: _atom_feed(
                _atom_entry(
                    title="Relevant agentic copy",
                    link="https://example.com/post#atom-everything",
                )
            ),
        },
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Relevant agentic copy"]
    assert result.items[0].summary.startswith("[Simon Willison]")


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout("timed out"),
        503,
        b"<html><body>not a feed</body></html>",
        b"<rss",
    ],
)
def test_one_failed_feed_preserves_the_other_feed(monkeypatch, failure) -> None:
    _mock_feeds(
        monkeypatch,
        {LATENT.url: failure, WILLISON.url: _atom_feed(_atom_entry())},
    )

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Exploring agentic workflows"]
    assert result.failed_feeds == ("Latent Space",)


def test_bozo_feed_with_entries_is_still_used(monkeypatch) -> None:
    truncated = _rss_feed(_rss_item()).removesuffix(b"</channel></rss>")
    _mock_feeds(monkeypatch, {LATENT.url: truncated, WILLISON.url: _atom_feed()})

    result = newsletter.fetch_newsletter_items("agentic")

    assert [item.title for item in result.items] == ["Agentic Engineering Report"]
    assert result.failed_feeds == ()


def test_all_feeds_failing_raises(monkeypatch) -> None:
    _mock_feeds(monkeypatch, {LATENT.url: 503, WILLISON.url: httpx.ReadTimeout("timed out")})

    with pytest.raises(newsletter.NewsletterFeedError):
        newsletter.fetch_newsletter_items("agentic")


def test_valid_empty_feeds_return_no_items_and_no_failures(monkeypatch) -> None:
    _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(), WILLISON.url: _atom_feed()})

    result = newsletter.fetch_newsletter_items("agentic")

    assert result.items == []
    assert result.failed_feeds == ()


def test_max_results_bound_is_enforced_after_scoring(monkeypatch) -> None:
    items = [
        _rss_item(title=f"Agentic {index}", link=f"https://www.latent.space/p/{index}")
        for index in range(1, 5)
    ]
    _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(*items), WILLISON.url: _atom_feed()})

    result = newsletter.fetch_newsletter_items("agentic", max_results=2)

    assert [item.title for item in result.items] == ["Agentic 1", "Agentic 2"]


@pytest.mark.parametrize("max_results", [0, 11, -1, 1.5, True])
def test_invalid_max_results_rejected_before_http(monkeypatch, max_results) -> None:
    monkeypatch.setattr(
        newsletter.httpx,
        "get",
        lambda *args, **kwargs: pytest.fail("HTTP must not be called"),
    )

    with pytest.raises(ValueError):
        newsletter.fetch_newsletter_items("agentic", max_results=max_results)


def test_request_shape_one_bounded_get_per_configured_feed(monkeypatch) -> None:
    calls = _mock_feeds(monkeypatch, {LATENT.url: _rss_feed(), WILLISON.url: _atom_feed()})

    newsletter.fetch_newsletter_items("agentic")

    assert [call["url"] for call in calls] == [LATENT.url, WILLISON.url]
    for call in calls:
        assert call["timeout"] == newsletter.FEED_TIMEOUT_SECONDS
        assert call["headers"] == {"User-Agent": "PULSE/0.1"}
        assert call["follow_redirects"] is True
