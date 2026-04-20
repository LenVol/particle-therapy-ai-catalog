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
    strong_hits = int(repo.get("heuristic_strong_particle_hits", 0))
    particle_hits = int(repo.get("heuristic_particle_hits", 0))
    ai_hits = int(repo.get("heuristic_ai_hits", 0))
    title_strong_hits = int(repo.get("heuristic_title_strong_particle_hits", 0))
    title_ai_hits = int(repo.get("heuristic_title_ai_hits", 0))
    total = int(repo.get("heuristic_total_score", 0))

    pt_total = strong_hits + particle_hits + title_strong_hits
    ai_total = ai_hits + title_ai_hits
    include = bool(repo.get("heuristic_passes", False)) or bool(repo.get("forced_include", False))

    summary = (
        repo.get("description")
        or repo.get("manual_note")
        or "Included by heuristic/manual filtering."
    )

    categories = repo.get("manual_tags", []) or []
    reasons = list(repo.get("heuristic_reasons", []) or [])
    warnings: list[str] = []

    if repo.get("is_manual"):
        reasons.append(f"Manual seed source: {repo.get('manual_source', 'unknown')}.")
    if repo.get("forced_include"):
        reasons.append("Forced include was enabled for this repository.")
    if repo.get("readme_word_count", 0) < 20:
        warnings.append("Very short README.")
    if not repo.get("has_code", True):
        warnings.append("Code presence could not be verified.")

    return RepoClassification(
        include=include,
        confidence=min(0.95, max(0.10, total / 20.0)),
        summary=summary,
        particle_therapy_relevance=(
            "high" if (strong_hits + title_strong_hits) >= 1 and pt_total >= 2
            else "medium" if pt_total >= 1
            else "none"
        ),
        ml_relevance=(
            "high" if ai_total >= 2
            else "medium" if ai_total >= 1
            else "none"
        ),
        categories=categories,
        reasons=reasons,
        warnings=warnings,
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
        "full_name": repo.get("full_name"),
        "description": (repo.get("description") or "")[:max_description_chars],
        "topics": (repo.get("topics") or [])[:max_topics],
        "readme_excerpt": (repo.get("readme_excerpt") or "")[:max_readme_chars],
        "manual_note": repo.get("manual_note", ""),
        "manual_tags": repo.get("manual_tags", []),
        "is_manual": repo.get("is_manual", False),
        "manual_source": repo.get("manual_source"),
        "heuristic_strong_particle_hits": repo.get("heuristic_strong_particle_hits", 0),
        "heuristic_particle_hits": repo.get("heuristic_particle_hits", 0),
        "heuristic_support_hits": repo.get("heuristic_support_hits", 0),
        "heuristic_ai_hits": repo.get("heuristic_ai_hits", 0),
        "heuristic_negative_hits": repo.get("heuristic_negative_hits", 0),
        "heuristic_generic_radiotherapy_hits": repo.get("heuristic_generic_radiotherapy_hits", 0),
        "heuristic_title_strong_particle_hits": repo.get("heuristic_title_strong_particle_hits", 0),
        "heuristic_title_ai_hits": repo.get("heuristic_title_ai_hits", 0),
        "heuristic_total_score": repo.get("heuristic_total_score", 0),
        "heuristic_has_strong_particle_anchor": repo.get("heuristic_has_strong_particle_anchor", False),
        "heuristic_passes": repo.get("heuristic_passes", False),
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
        "manual_note": repo.get("manual_note", ""),
        "manual_tags": repo.get("manual_tags", []),
        "is_manual": repo.get("is_manual", False),
        "manual_source": repo.get("manual_source"),
        "forced_include": repo.get("forced_include", False),
        "has_code": repo.get("has_code", False),
        "readme_word_count": repo.get("readme_word_count", 0),
        "heuristic_strong_particle_hits": repo.get("heuristic_strong_particle_hits", 0),
        "heuristic_particle_hits": repo.get("heuristic_particle_hits", 0),
        "heuristic_support_hits": repo.get("heuristic_support_hits", 0),
        "heuristic_ai_hits": repo.get("heuristic_ai_hits", 0),
        "heuristic_negative_hits": repo.get("heuristic_negative_hits", 0),
        "heuristic_generic_radiotherapy_hits": repo.get("heuristic_generic_radiotherapy_hits", 0),
        "heuristic_title_strong_particle_hits": repo.get("heuristic_title_strong_particle_hits", 0),
        "heuristic_title_ai_hits": repo.get("heuristic_title_ai_hits", 0),
        "heuristic_total_score": repo.get("heuristic_total_score", 0),
        "heuristic_has_strong_particle_anchor": repo.get("heuristic_has_strong_particle_anchor", False),
        "heuristic_passes": repo.get("heuristic_passes", False),
        "heuristic_reasons": repo.get("heuristic_reasons", []),
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
        "You classify repositories for a catalog focused on particle therapy and AI/ML. "
        "Include repositories that are directly about AI/ML in particle therapy, and also include "
        "foundational particle-therapy software tools that are clearly relevant to research workflows "
        "around AI/ML, treatment planning, dose calculation, segmentation, adaptation, or analysis. "
        "Exclude unrelated generic ML repositories and unrelated generic radiotherapy repositories. "
        "Research code is acceptable; the repository does not need to be a polished end-user tool."
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
