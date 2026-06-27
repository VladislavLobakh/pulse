"""Generate synthetic AI articles for test fixtures."""

from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

from pulse.models import Source

fake = Faker()

ARTICLE_COUNT = 30
AI_TOPICS = [
    "LangGraph",
    "MCP",
    "FastMCP",
    "Claude",
    "GPT-4o",
    "RAG",
    "AI agents",
    "Pydantic",
    "LangChain",
    "Tavily",
    "Instructor",
    "asyncio",
    "vector databases",
    "Qdrant",
    "Modal",
    "LLM inference",
    "fine-tuning",
    "embeddings",
    "multimodal AI",
    "tool calling",
]
TITLE_TEMPLATES = [
    "Why {topic} is changing AI engineering in 2026",
    "Building production {topic} pipelines: lessons learned",
    "How to use {topic} with LangGraph",
    "{topic}: a deep dive for AI engineers",
    "Getting started with {topic} in Python",
    "The {topic} ecosystem in 2026",
    "{topic} vs alternatives: what to use in production",
    "Show HN: We built a {topic} integration",
    "Ask HN: Best practices for {topic}?",
    "Understanding {topic} internals",
]

PROJECT_ROOT = Path(__file__).resolve().parents[3]
OUTPUT_PATH = PROJECT_ROOT / "data" / "pulse_test_articles.json"


@dataclass
class TestArticle:
    title: str
    content: str
    source: str
    date: str
    topics: list[str]


def generate_article() -> TestArticle:
    topic1, topic2 = random.sample(AI_TOPICS, 2)
    topics = [topic1, topic2]
    if random.random() > 0.5:
        extra = random.choice(AI_TOPICS)
        if extra not in topics:
            topics.append(extra)

    template = random.choice(TITLE_TEMPLATES)
    title = template.format(topic=topic1)
    content = (fake.paragraph(nb_sentences=4) + " " + fake.sentence())[:200]
    source = random.choice(list(Source)).value
    days_ago = random.randint(0, 29)
    date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d")

    return TestArticle(title=title, content=content, source=source, date=date, topics=topics)


def main() -> None:
    random.seed(42)
    articles = [generate_article() for _ in range(ARTICLE_COUNT)]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump([asdict(a) for a in articles], f, indent=2, ensure_ascii=False)
    print(f"Generated {len(articles)} synthetic articles → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
