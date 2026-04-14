from __future__ import annotations

import json
import os
from dataclasses import dataclass

import requests

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")


@dataclass
class RepoClassification:
    include: bool
    confidence: float
    summary: str
    particle_therapy_relevance: str
    ml_relevance: str
    categories: list[str]
    reasons: list[str]
    warnings: list[str]
    likely_tool_type: str


SCHEMA = {
    "name": "repo_classifier",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "include": {"type": "boolean"},
            "confidence": {"type": "number"},
            "summary": {"type": "string"},
            "particle_therapy_relevance": {"type": "string"},
            "ml_relevance": {"type": "string"},
            "categories": {"type": "array", "items": {"type": "string"}},
            "reasons": {"type": "array", "items": {"type": "string"}},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "likely_tool_type": {"type": "string"},
        },
        "required": [
            "include",
            "confidence",
            "summary",
            "particle_therapy_relevance",
            "ml_relevance",
            "categories",
            "reasons",
            "warnings",
            "likely_tool_type",
        ],
    },
}


def fallback_classify(repo: dict) -> RepoClassification:
    pt = repo.get("heuristic_pt_score", 0)
    ai = repo.get("heuristic_ai_score", 0)
    total = repo.get("heuristic_total_score", 0)
    return RepoClassification(
        include=pt >= 1 and ai >= 1,
        confidence=min(0.95, max(0.1, total / 12)),
        summary=repo.get("description") or "Keyword-matched repository.",
        particle_therapy_relevance="high" if pt >= 2 else "medium",
        ml_relevance="high" if ai >= 2 else "medium",
        categories=[],
        reasons=["Fallback heuristic classifier used."],
        warnings=[],
        likely_tool_type="unclear",
    )


def classify_repo(repo: dict) -> RepoClassification:
    if not OPENAI_API_KEY:
        return fallback_classify(repo)

    system = (
        "You classify repositories for a public catalog focused on repositories "
        "that are relevant to both particle therapy and AI/ML. "
        "Be conservative. Exclude generic radiotherapy repos unless proton, ion, "
        "hadron, or particle-therapy relevance is clear. Exclude generic AI repos "
        "unless particle-therapy relevance is clear."
    )

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(repo, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": SCHEMA,
        },
        "temperature": 0.1,
    }

    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=60,
    )
    response.raise_for_status()
    content = response.json()["choices"][0]["message"]["content"]
    return RepoClassification(**json.loads(content))
