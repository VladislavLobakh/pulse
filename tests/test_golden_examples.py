"""Schema checks for data/golden_examples.json — a manually reviewed quality
baseline for future evals. Not loaded by runtime code; these tests only keep
the file valid as that future baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from pulse.models import Source

GOLDEN_PATH = Path(__file__).parents[1] / "data" / "golden_examples.json"
REQUIRED_FIELDS = {"id", "source", "item_id", "url", "title", "expected_summary", "quality"}


def _load() -> list[dict]:
    with GOLDEN_PATH.open() as f:
        return json.load(f)


def test_golden_examples_parse_with_required_fields() -> None:
    entries = _load()
    assert isinstance(entries, list)
    for entry in entries:
        missing = REQUIRED_FIELDS - entry.keys()
        assert not missing, f"{entry.get('id')} missing fields: {missing}"
        for field in REQUIRED_FIELDS - {"quality"}:
            assert isinstance(entry[field], str) and entry[field], f"{entry.get('id')}.{field}"


def test_golden_examples_quality_and_source_are_valid() -> None:
    for entry in _load():
        quality = entry["quality"]
        # isinstance(True, int) is True in Python, so a bool must be excluded explicitly.
        assert type(quality) is int, f"{entry['id']}: quality must be int, got {type(quality)}"
        assert 1 <= quality <= 5, f"{entry['id']}: quality {quality} out of 1-5 range"

        assert Source(entry["source"]), f"{entry['id']}: unknown source {entry['source']!r}"

        parts = urlsplit(entry["url"])
        assert parts.scheme == "https", f"{entry['id']}: url must be https"
        assert parts.netloc, f"{entry['id']}: url must have a host"


def test_golden_examples_meet_dataset_minimums() -> None:
    entries = _load()

    assert len(entries) >= 3, "need at least three reviewed golden examples"

    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)), "golden example ids must be unique"

    pairs = [(entry["source"], entry["item_id"]) for entry in entries]
    assert len(pairs) == len(set(pairs)), "(source, item_id) pairs must be unique"

    sources = {entry["source"] for entry in entries}
    assert len(sources) >= 2, "golden examples must cover more than one source"
