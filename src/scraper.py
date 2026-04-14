from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

import yaml

from src.classifier import classify_repo
from src.providers import (
    github_get_file,
    gitlab_get_file,
    polite_sleep,
    search_github_repositories,
    search_gitlab_projects,
)
from src.render_readme import write_readme
from src.render_site import write_site
from src.scoring import passes_prefilter, score_text


LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

README_CANDIDATES = ["README.md", "README.rst", "README.txt", "Readme.md", "readme.md"]
EXTRA_FILES = [
    "requirements.txt",
    "pyproject.toml",
    "environment.yml",
    "environment.yaml",
    "setup.py",
    "docs/index.md",
    "docs/README.md",
]


def load_yaml(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def safe_write_json(path: str | Path, payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def collect_github_text(owner: str, repo: str) -> tuple[str, str]:
    readme = ""
    extra_chunks: list[str] = []

    for candidate in README_CANDIDATES:
        readme = github_get_file(owner, repo, candidate)
        if readme:
            break

    for candidate in EXTRA_FILES:
        if candidate in README_CANDIDATES and readme:
            continue
        text = github_get_file(owner, repo, candidate)
        if text:
            extra_chunks.append(text[:4000])

    return readme[:12000], "\n\n".join(extra_chunks)[:12000]


def collect_gitlab_text(project_id: int, default_branch: str | None) -> tuple[str, str]:
    if not default_branch:
        return "", ""

    readme = ""
    extra_chunks: list[str] = []

    for candidate in README_CANDIDATES:
        readme = gitlab_get_file(project_id, candidate, default_branch)
        if readme:
            break

    for candidate in EXTRA_FILES:
        if candidate in README_CANDIDATES and readme:
            continue
        text = gitlab_get_file(project_id, candidate, default_branch)
        if text:
            extra_chunks.append(text[:4000])

    return readme[:12000], "\n\n".join(extra_chunks)[:12000]


def build_blob(description: str, topics: list[str], readme: str, extra: str) -> str:
    return " ".join([
        description or "",
        " ".join(topics or []),
        readme or "",
        extra or "",
    ])


def build_github_record(item: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    full_name = item["full_name"]
    owner, repo = full_name.split("/", 1)

    readme, extra = collect_github_text(owner, repo)
    blob = build_blob(
        item.get("description") or "",
        item.get("topics") or [],
        readme,
        extra,
    )

    heuristic = score_text(
        blob,
        taxonomy["particle_therapy_terms"],
        taxonomy["ai_terms"],
        taxonomy["negative_terms"],
    )

    return {
        "platform": "github",
        "full_name": full_name,
        "url": item["html_url"],
        "description": item.get("description") or "",
        "stars": item.get("stargazers_count", 0),
        "language": item.get("language"),
        "updated_at": item.get("updated_at"),
        "license": (item.get("license") or {}).get("spdx_id"),
        "topics": item.get("topics") or [],
        "readme_excerpt": readme,
        "extra_excerpt": extra,
        "heuristic_pt_score": heuristic.pt_score,
        "heuristic_ai_score": heuristic.ai_score,
        "heuristic_negative_score": heuristic.negative_score,
        "heuristic_total_score": heuristic.total_score,
    }


def build_gitlab_record(item: dict[str, Any], taxonomy: dict[str, Any]) -> dict[str, Any]:
    project_id = item["id"]
    default_branch = item.get("default_branch")

    readme, extra = collect_gitlab_text(project_id, default_branch)
    blob = build_blob(
        item.get("description") or "",
        item.get("topics") or [],
        readme,
        extra,
    )

    heuristic = score_text(
        blob,
        taxonomy["particle_therapy_terms"],
        taxonomy["ai_terms"],
        taxonomy["negative_terms"],
    )

    return {
        "platform": "gitlab",
        "full_name": item.get("path_with_namespace")
        or item.get("name_with_namespace")
        or str(project_id),
        "url": item["web_url"],
        "description": item.get("description") or "",
        "stars": item.get("star_count", 0),
        "language": None,
        "updated_at": item.get("last_activity_at"),
        "license": None,
        "topics": item.get("topics") or [],
        "readme_excerpt": readme,
        "extra_excerpt": extra,
        "heuristic_pt_score": heuristic.pt_score,
        "heuristic_ai_score": heuristic.ai_score,
        "heuristic_negative_score": heuristic.negative_score,
        "heuristic_total_score": heuristic.total_score,
    }


def apply_overrides(entries: list[dict[str, Any]], overrides: dict[str, Any]) -> list[dict[str, Any]]:
    excluded = set(overrides.get("exclude", []))
    included = set(overrides.get("include", []))
    notes = overrides.get("notes", {})
    tags = overrides.get("tags", {})

    result: list[dict[str, Any]] = []

    for entry in entries:
        if entry["url"] in excluded:
            continue

        if entry["url"] in included:
            entry["forced_include"] = True

        if entry["url"] in notes:
            entry["manual_note"] = notes[entry["url"]]

        if entry["url"] in tags:
            entry["manual_tags"] = tags[entry["url"]]

        result.append(entry)

    return result


def discover_repositories(
    queries: list[str],
    taxonomy: dict[str, Any],
    settings: dict[str, Any],
) -> list[dict[str, Any]]:
    scraper_cfg = settings.get("scraper", {})
    github_per_query = int(scraper_cfg.get("github_per_query", 25))
    gitlab_per_query = int(scraper_cfg.get("gitlab_per_query", 25))
    use_gitlab = bool(scraper_cfg.get("use_gitlab", True))
    sleep_seconds = float(scraper_cfg.get("polite_sleep_seconds", 0.35))

    seen: dict[str, dict[str, Any]] = {}

    for query in queries:
        LOGGER.info("GitHub query: %s", query)
        try:
            for item in search_github_repositories(query, per_page=github_per_query):
                record = build_github_record(item, taxonomy)
                current = seen.get(record["url"])
                if current is None or record["heuristic_total_score"] > current["heuristic_total_score"]:
                    seen[record["url"]] = record
                polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("GitHub query failed for %r: %s", query, exc)

        if use_gitlab:
            LOGGER.info("GitLab query: %s", query)
            try:
                for item in search_gitlab_projects(query, per_page=gitlab_per_query):
                    record = build_gitlab_record(item, taxonomy)
                    current = seen.get(record["url"])
                    if current is None or record["heuristic_total_score"] > current["heuristic_total_score"]:
                        seen[record["url"]] = record
                    polite_sleep(sleep_seconds)
            except Exception as exc:
                LOGGER.warning("GitLab query failed for %r: %s", query, exc)

    return sorted(
        seen.values(),
        key=lambda row: (row["heuristic_total_score"], row["stars"]),
        reverse=True,
    )


def run() -> int:
    queries_cfg = load_yaml("config/queries.yml")
    taxonomy = load_yaml("config/taxonomy.yml")
    overrides = load_yaml("config/manual_overrides.yml")
    settings = load_yaml("config/settings.yml")

    queries = queries_cfg.get("queries", [])
    if not queries:
        raise ValueError("config/queries.yml contains no queries.")

    all_candidates = discover_repositories(queries, taxonomy, settings)
    all_candidates = apply_overrides(all_candidates, overrides)

    safe_write_json("data/all_candidates.json", all_candidates)

    scraper_cfg = settings.get("scraper", {})
    llm_cfg = settings.get("llm", {})

    min_heuristic_score = int(scraper_cfg.get("min_heuristic_score", 4))
    classify_sleep_seconds = float(scraper_cfg.get("classify_sleep_seconds", 1.25))
    max_llm_repos = int(llm_cfg.get("max_repos_per_run", 25))
    llm_enabled = bool(llm_cfg.get("enabled", False))
    cache_classifications = bool(scraper_cfg.get("cache_classifications", True))
    llm_cfg["cache_classifications"] = cache_classifications

    prefiltered: list[dict[str, Any]] = []
    for repo in all_candidates:
        heuristic = score_text(
            build_blob(
                repo.get("description", ""),
                repo.get("topics", []),
                repo.get("readme_excerpt", ""),
                repo.get("extra_excerpt", ""),
            ),
            taxonomy["particle_therapy_terms"],
            taxonomy["ai_terms"],
            taxonomy["negative_terms"],
        )

        if passes_prefilter(heuristic, min_total=min_heuristic_score) or repo.get("forced_include", False):
            prefiltered.append(repo)

    prefiltered = sorted(
        prefiltered,
        key=lambda row: (row["heuristic_total_score"], row["stars"]),
        reverse=True,
    )

    if llm_enabled:
        prefiltered = prefiltered[:max_llm_repos]

    included: list[dict[str, Any]] = []

    for repo in prefiltered:
        classification = classify_repo(
            repo=repo,
            llm_cfg=llm_cfg,
            cache_path="data/classification_cache.json",
        )

        if not classification.include and not repo.get("forced_include", False):
            time.sleep(classify_sleep_seconds)
            continue

        repo["classification"] = {
            "include": classification.include,
            "confidence": classification.confidence,
            "summary": classification.summary,
            "particle_therapy_relevance": classification.particle_therapy_relevance,
            "ml_relevance": classification.ml_relevance,
            "categories": classification.categories,
            "reasons": classification.reasons,
            "warnings": classification.warnings,
            "likely_tool_type": classification.likely_tool_type,
        }

        included.append(repo)
        time.sleep(classify_sleep_seconds)

    included = sorted(
        included,
        key=lambda row: (
            row["classification"]["confidence"],
            row["heuristic_total_score"],
            row["stars"],
        ),
        reverse=True,
    )

    safe_write_json("data/catalog.json", included)
    write_readme(included)
    write_site(included)

    LOGGER.info("All candidates: %d", len(all_candidates))
    LOGGER.info("Prefiltered candidates: %d", len(prefiltered))
    LOGGER.info("Included repositories: %d", len(included))

    return 0
