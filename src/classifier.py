from __future__ import annotations

import hashlib
import json
import os
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests


OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")


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
            "particle_therapy_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low", "none"],
            },
            "ml_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low", "none"],
            },
            "categories": {
                "type": "array",
                "items": {"type": "string"},
            },
            "reasons": {
                "type": "array",
                "items": {"type": "string"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "likely_tool_type": {
                "type": "string",
                "enum": [
                    "software_tool",
                    "research_code",
                    "model_training_code",
                    "dataset_or_preprocessing",
                    "paper_companion_repo",
                    "benchmark",
                    "unclear",
                ],
            },
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


def fallback_classify(repo: dict[str, Any]) -> RepoClassification:
    pt = int(repo.get("heuristic_pt_score", 0))
    ai = int(repo.get("heuristic_ai_score", 0))
    total = int(repo.get("heuristic_total_score", 0))

    return RepoClassification(
        include=pt >= 1 and ai >= 1,
        confidence=min(0.95, max(0.10, total / 12.0)),
        summary=repo.get("description") or "Keyword-matched repository.",
        particle_therapy_relevance="high" if pt >= 2 else ("medium" if pt >= 1 else "none"),
        ml_relevance="high" if ai >= 2 else ("medium" if ai >= 1 else "none"),
        categories=[],
        reasons=["Fallback heuristic classifier used."],
        warnings=[],
        likely_tool_type="unclear",
    )


def load_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json_file(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def build_repo_fingerprint(repo: dict[str, Any], llm_cfg: dict[str, Any]) -> str:
    max_readme_chars = int(llm_cfg.get("max_readme_chars", 4000))
    max_description_chars = int(llm_cfg.get("max_description_chars", 500))
    max_topics = int(llm_cfg.get("max_topics", 20))

    payload = {
        "url": repo.get("url"),
        "description": (repo.get("description") or "")[:max_description_chars],
        "topics": (repo.get("topics") or [])[:max_topics],
        "readme_excerpt": (repo.get("readme_excerpt") or "")[:max_readme_chars],
        "heuristic_pt_score": repo.get("heuristic_pt_score", 0),
        "heuristic_ai_score": repo.get("heuristic_ai_score", 0),
        "heuristic_negative_score": repo.get("heuristic_negative_score", 0),
        "heuristic_total_score": repo.get("heuristic_total_score", 0),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def trim_repo_for_llm(repo: dict[str, Any], llm_cfg: dict[str, Any]) -> dict[str, Any]:
    max_readme_chars = int(llm_cfg.get("max_readme_chars", 4000))
    max_description_chars = int(llm_cfg.get("max_description_chars", 500))
    max_topics = int(llm_cfg.get("max_topics", 20))

    return {
        "platform": repo.get("platform"),
        "full_name": repo.get("full_name"),
        "url": repo.get("url"),
        "description": (repo.get("description") or "")[:max_description_chars],
        "stars": repo.get("stars", 0),
        "language": repo.get("language"),
        "updated_at": repo.get("updated_at"),
        "license": repo.get("license"),
        "topics": (repo.get("topics") or [])[:max_topics],
        "readme_excerpt": (repo.get("readme_excerpt") or "")[:max_readme_chars],
        "heuristic_pt_score": repo.get("heuristic_pt_score", 0),
        "heuristic_ai_score": repo.get("heuristic_ai_score", 0),
        "heuristic_negative_score": repo.get("heuristic_negative_score", 0),
        "heuristic_total_score": repo.get("heuristic_total_score", 0),
        "manual_note": repo.get("manual_note", ""),
        "manual_tags": repo.get("manual_tags", []),
    }


def classify_repo(
    repo: dict[str, Any],
    llm_cfg: dict[str, Any],
    cache_path: str | Path = "data/classification_cache.json",
) -> RepoClassification:
    enabled = bool(llm_cfg.get("enabled", False))
    if not enabled or not OPENAI_API_KEY:
        return fallback_classify(repo)

    cache_file = Path(cache_path)
    use_cache = bool(llm_cfg.get("cache_classifications", True))
    repo_fingerprint = build_repo_fingerprint(repo, llm_cfg)

    cache: dict[str, Any] = load_json_file(cache_file) if use_cache else {}
    cached = cache.get(repo_fingerprint)
    if cached:
        return RepoClassification(**cached)

    model = llm_cfg.get("model", "gpt-4.1-mini")
    max_completion_tokens = int(llm_cfg.get("max_completion_tokens", 350))
    timeout = int(llm_cfg.get("request_timeout", 60))

    retry_cfg = llm_cfg.get("retry", {})
    max_attempts = int(retry_cfg.get("max_attempts", 6))
    base_sleep = float(retry_cfg.get("base_sleep_seconds", 2.0))

    trimmed_repo = trim_repo_for_llm(repo, llm_cfg)

    system = (
        "You classify repositories for a public catalog focused on repositories "
        "that are relevant to both particle therapy and AI/ML. "
        "Be conservative. Exclude generic radiotherapy repositories unless proton, ion, "
        "hadron, or particle-therapy relevance is clear. Exclude generic AI repositories "
        "unless particle-therapy relevance is clear. "
        "A research-code repository may still be included if it is genuinely relevant."
    )

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(trimmed_repo, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": SCHEMA,
        },
        "temperature": 0.1,
        "max_completion_tokens": max_completion_tokens,
    }

    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_attempts):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=timeout)

            if response.status_code == 200:
                content = response.json()["choices"][0]["message"]["content"]
                result = RepoClassification(**json.loads(content))
                if use_cache:
                    cache[repo_fingerprint] = asdict(result)
                    save_json_file(cache_file, cache)
                return result

            if response.status_code == 429:
                sleep_for = base_sleep * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_for)
                continue

            response.raise_for_status()

        except requests.RequestException:
            if attempt < max_attempts - 1:
                sleep_for = base_sleep * (2 ** attempt) + random.uniform(0, 1)
                time.sleep(sleep_for)
                continue
            break
        except Exception:
            break

    return fallback_classify(repo)
