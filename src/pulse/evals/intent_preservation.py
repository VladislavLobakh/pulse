"""Intent-preservation evals for the HN ReAct reason/observe prompts.

Runs deterministic regression cases against live OpenRouter models and checks
the structured output with plain keyword/regex assertions (no LLM judge).
Every LLM input is built by the production code paths — the agent's
`ReActConfig` plus `patterns.react.build_reason_messages` /
`build_observe_messages` — so the evals cannot silently drift from what the
app actually sends. Needs
OPENROUTER_API_KEY; network use is why this is a script, not a pytest test.

Usage:
    uv run python -m pulse.evals.intent_preservation
        Regression mode: each production model runs only the cases for the
        step it serves (REASON_MODELS x reason cases, OBSERVE_MODELS x
        observe cases).
    uv run python -m pulse.evals.intent_preservation <model-slug> [<model-slug> ...]
        Candidate screening: each given model runs every case, since a
        candidate is being assessed for any role.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from pulse.agents import hn
from pulse.models import Source, SourceItem
from pulse.patterns.react import (
    ReActState,
    ReasonDecision,
    SourceBatchScore,
    build_observe_messages,
    build_reason_messages,
    make_initial_state,
)

SITE = "site:news.ycombinator.com"

# The product's historical drift attractor: generated queries injected these
# even for unrelated topics. Forbidden in every non-AI case.
_AI_TERMS = ["AI", "LLM", "LLMs", "agents", "MCP", "OpenAI", "LangGraph", "RAG", "GPT"]


def _has_word(query: str, term: str) -> bool:
    # Optional plural suffix: "issue" matches "issues" — the contract allows
    # spelling variants, so the checker must not fail them.
    return (
        re.search(rf"(?<![\w-]){re.escape(term)}(?:e?s)?(?![\w-])", query, re.IGNORECASE)
        is not None
    )


def _state(
    original_query: str,
    *,
    generated_query: str | None = None,
    iteration: int = 0,
    last_score: float = 0.0,
    titles: list[str] | None = None,
) -> ReActState:
    """A production-shaped state advanced to the point a case simulates."""
    state = make_initial_state(original_query, max_results=hn.MAX_RESULTS)
    state["query"] = generated_query or original_query
    state["iteration"] = iteration
    state["last_score"] = last_score
    state["items"] = [
        SourceItem(
            title=title,
            url="https://news.ycombinator.com/item?id=1",
            score=0.5,
            summary=title,
            source=Source.HACKER_NEWS,
        )
        for title in titles or []
    ]
    return state


@dataclass
class ReasonCase:
    name: str
    original_query: str
    required_all: list[list[str]] = field(default_factory=list)  # each group: any-of
    required_literals: list[str] = field(default_factory=list)  # exact substrings
    forbidden: list[str] = field(default_factory=list)
    # Simulated poor first attempt: (drifting generated query, previous titles).
    retry_feedback: tuple[str, list[str]] | None = None

    def run(self, model: str) -> list[str]:
        if self.retry_feedback:
            generated, titles = self.retry_feedback
            state = _state(
                self.original_query,
                generated_query=generated,
                iteration=1,
                last_score=0.3,
                titles=titles,
            )
        else:
            state = _state(self.original_query)
        config = hn._config()
        # Call-time kwargs override the partial's, so only the model under
        # test is swapped — sampling params stay as production binds them.
        decision = config.reason_llm(
            messages=build_reason_messages(state, config),
            models=[model],
            response_model=ReasonDecision,
        )
        failures = self._check(decision)
        return failures + ([f"  -> query={decision.query!r}"] if failures else [])

    def _check(self, decision: ReasonDecision) -> list[str]:
        failures = []
        for group in self.required_all:
            if not any(_has_word(decision.query, term) for term in group):
                failures.append(f"missing any of {group}")
        for literal in self.required_literals:
            if literal not in decision.query:
                failures.append(f"missing literal {literal!r}")
        for term in self.forbidden:
            if _has_word(decision.query, term):
                failures.append(f"forbidden term {term!r} in query")
        return failures


@dataclass
class ObserveCase:
    name: str
    original_query: str
    generated_query: str
    titles: list[str]
    max_relevance: float | None = None  # drifted batch must score at or below
    min_relevance: float | None = None  # on-topic batch must score at or above

    def run(self, model: str) -> list[str]:
        state = _state(
            self.original_query, generated_query=self.generated_query, titles=self.titles
        )
        config = hn._config()
        score = config.observe_llm(
            messages=build_observe_messages(state, config),
            models=[model],
            response_model=SourceBatchScore,
        )
        failures = []
        if self.max_relevance is not None and score.relevance > self.max_relevance:
            failures.append(f"relevance={score.relevance:.2f} > {self.max_relevance} (drift)")
        if self.min_relevance is not None and score.relevance < self.min_relevance:
            failures.append(f"relevance={score.relevance:.2f} < {self.min_relevance}")
        return failures


REASON_CASES: list[ReasonCase] = [
    ReasonCase(
        name="1 kube ingress (first pass)",
        original_query="Kubernetes ingress nginx tuning",
        required_all=[["Kubernetes", "k8s"], ["ingress", "nginx"]],
        forbidden=_AI_TERMS,
    ),
    ReasonCase(
        name="1r kube ingress (retry after drift)",
        original_query="Kubernetes ingress nginx tuning",
        required_all=[["Kubernetes", "k8s"], ["ingress", "nginx"]],
        forbidden=_AI_TERMS,
        retry_feedback=(
            "LLM deployment Kubernetes",
            ["Show HN: my LLM stack", "Scaling GPT agents", "OpenAI infra notes"],
        ),
    ),
    ReasonCase(
        name="2 postgres vacuum",
        original_query="postgres vacuum tuning",
        required_all=[["postgres", "postgresql"], ["vacuum", "autovacuum", "bloat"]],
        forbidden=[*_AI_TERMS, "vector", "embedding"],
    ),
    ReasonCase(
        name="3 AI agents scaling",
        original_query="AI agents production scaling",
        required_all=[["AI", "agents", "agent"], ["production", "scaling", "scale"]],
    ),
    ReasonCase(
        name="4 MCP server deployment",
        original_query="MCP server deployment",
        required_all=[
            ["MCP", "Model Context Protocol"],
            ["deployment", "deploy", "deploying", "server"],
        ],
    ),
    ReasonCase(
        name="5 LangGraph streaming bug",
        original_query="LangGraph streaming bug",
        required_all=[["LangGraph"], ["streaming", "stream"], ["bug", "issue", "error"]],
    ),
    ReasonCase(
        # Broad request: the topic still comes from the user's own words ("AI"),
        # not from any agent-side default domain.
        name="6 broad query keeps user's topic",
        original_query="Find interesting AI articles on Hacker News",
        required_all=[["AI", "artificial intelligence", "LLM", "LLMs"]],
    ),
    ReasonCase(
        name="7 nginx 502 (retry)",
        original_query="nginx ingress controller 502 timeout",
        required_all=[["nginx", "ingress", "ingress-nginx"], ["502", "timeout"]],
        forbidden=_AI_TERMS,
        retry_feedback=(
            "nginx ingress controller 502 timeout",
            ["Ask HN: hosting on a VPS", "Nginx vs Caddy", "Cloudflare outage postmortem"],
        ),
    ),
    ReasonCase(
        # Operator preservation: quotes and site: must survive verbatim even
        # though the domain is already pinned at the fetch layer.
        name="8 quoted phrases + site operator",
        original_query=f'"nginx ingress" "proxy-buffer-size" {SITE}',
        required_literals=['"nginx ingress"', '"proxy-buffer-size"', SITE],
        forbidden=_AI_TERMS,
    ),
    ReasonCase(
        name="9 negative constraint",
        original_query="AI agents production scaling -crypto",
        required_all=[["AI", "agents", "agent"], ["production", "scaling", "scale"]],
        required_literals=["-crypto"],
    ),
]

OBSERVE_CASES: list[ObserveCase] = [
    ObserveCase(
        name="O1 drifted batch scores low",
        original_query="Kubernetes ingress nginx tuning",
        generated_query="LLM deployment Kubernetes",
        titles=[
            "Serving LLMs on Kubernetes with vLLM",
            "Scaling GPT inference in production",
            "OpenAI-compatible gateways compared",
        ],
        max_relevance=0.4,
    ),
    ObserveCase(
        name="O2 on-topic batch scores high",
        original_query="Kubernetes ingress nginx tuning",
        generated_query="ingress-nginx performance tuning Kubernetes",
        titles=[
            "Tuning ingress-nginx for 100k RPS",
            "Kubernetes ingress-nginx proxy-buffer-size pitfalls",
            "Nginx ingress controller keepalive tuning notes",
        ],
        min_relevance=0.6,
    ),
]


Case = ReasonCase | ObserveCase


def _regression_plan() -> dict[str, list[Case]]:
    """Each production model paired with only the cases for the step it
    serves — combinations production never runs are never evaluated."""
    plan: dict[str, list[Case]] = {}
    for model in hn.REASON_MODELS:
        plan.setdefault(model, []).extend(REASON_CASES)
    for model in hn.OBSERVE_MODELS:
        plan.setdefault(model, []).extend(OBSERVE_CASES)
    return plan


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args:
        models = [f"openrouter/{m.removeprefix('openrouter/')}" for m in args]
        plan: dict[str, list[Case]] = {m: [*REASON_CASES, *OBSERVE_CASES] for m in models}
    else:
        plan = _regression_plan()

    exit_code = 0
    for model, cases in plan.items():
        passed = 0
        print(f"\n=== {model} ===")
        for case in cases:
            try:
                failures = case.run(model)
            except Exception as exc:  # provider errors count as case failure
                failures = [f"error: {exc}"]
            passed += not failures
            status = "PASS" if not failures else "FAIL"
            print(f"[{status}] {case.name}" + ("" if not failures else f" — {failures}"))
        print(f"--- {model}: {passed}/{len(cases)} passed")
        if passed != len(cases):
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
