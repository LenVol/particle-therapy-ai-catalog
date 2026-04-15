from __future__ import annotations

import csv
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

import yaml

from src.classifier import classify_repo
from src.providers import (
    get_github_repository,
    get_gitlab_project,
    github_get_file,
    github_list_repository_paths,
    gitlab_get_file,
    gitlab_list_repository_paths,
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

CODE_EXTENSIONS = {
    ".py", ".ipynb", ".m", ".jl", ".r", ".cpp", ".cc", ".c", ".h", ".hpp",
    ".java", ".kt", ".scala", ".go", ".rs", ".js", ".ts", ".tsx", ".jsx",
    ".php", ".rb", ".swift", ".cs", ".lua", ".sh", ".zsh", ".ps1"
}

CODE_FILENAMES = {
    "setup.py", "pyproject.toml", "requirements.txt", "environment.yml", "environment.yaml",
    "pom.xml", "build.gradle", "gradlew", "makefile", "cmakelists.txt",
    "package.json", "dockerfile", "snakefile"
}


def load_yaml(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def safe_write_json(path: str | Path, payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_repo_name(full_name: str) -> str:
    text = full_name or ""
    text = text.replace("/", " ")
    text = text.replace("-", " ")
    text = text.replace("_", " ")
    return text


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def repo_has_code(paths: list[str]) -> bool:
    for path in paths:
        lower = path.lower()
        name = lower.split("/")[-1]
        if name in CODE_FILENAMES:
            return True
        for ext in CODE_EXTENSIONS:
            if lower.endswith(ext):
                return True
    return False


def collect_github_text_and_paths(owner: str, repo: str, branch: str | None) -> tuple[str, str, list[str]]:
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

    paths = github_list_repository_paths(owner, repo, branch=branch)
    return readme[:12000], "\n\n".join(extra_chunks)[:12000], paths


def collect_gitlab_text_and_paths(project_id: int, default_branch: str | None) -> tuple[str, str, list[str]]:
    if not default_branch:
        return "", "", []

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

    paths = gitlab_list_repository_paths(project_id, default_branch)
    return readme[:12000], "\n\n".join(extra_chunks)[:12000], paths


def build_blob(full_name: str, description: str, topics: list[str], readme: str, extra: str) -> str:
    parts = [
        full_name or "",
        normalize_repo_name(full_name),
        description or "",
        " ".join(topics or []),
        readme or "",
        extra or "",
    ]
    return " ".join(parts)


def build_github_record(item: dict[str, Any], taxonomy: dict[str, Any], min_heuristic_score: int) -> dict[str, Any]:
    full_name = item["full_name"]
    owner, repo = full_name.split("/", 1)

    readme, extra, paths = collect_github_text_and_paths(owner, repo, item.get("default_branch"))
    blob = build_blob(full_name, item.get("description") or "", item.get("topics") or [], readme, extra)
    title_blob = normalize_repo_name(full_name)
    heuristic = score_text(blob, taxonomy, min_total=min_heuristic_score, title_blob=title_blob)

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
        "readme_word_count": count_words(readme),
        "has_code": repo_has_code(paths),
        "repo_paths_sample": paths[:200],
        "is_fork": item.get("fork", False),
        "heuristic_strong_particle_hits": heuristic.strong_particle_hits,
        "heuristic_particle_hits": heuristic.particle_hits,
        "heuristic_support_hits": heuristic.support_hits,
        "heuristic_ai_hits": heuristic.ai_hits,
        "heuristic_negative_hits": heuristic.negative_hits,
        "heuristic_generic_radiotherapy_hits": heuristic.generic_radiotherapy_hits,
        "heuristic_title_strong_particle_hits": heuristic.title_strong_particle_hits,
        "heuristic_title_ai_hits": heuristic.title_ai_hits,
        "heuristic_total_score": heuristic.total_score,
        "heuristic_has_strong_particle_anchor": heuristic.has_strong_particle_anchor,
        "heuristic_passes": heuristic.passes,
        "heuristic_reasons": heuristic.reasons,
    }


def build_gitlab_record(item: dict[str, Any], taxonomy: dict[str, Any], min_heuristic_score: int) -> dict[str, Any]:
    project_id = item["id"]
    default_branch = item.get("default_branch")
    repo_name = item.get("path_with_namespace") or item.get("name_with_namespace") or str(project_id)

    readme, extra, paths = collect_gitlab_text_and_paths(project_id, default_branch)
    blob = build_blob(repo_name, item.get("description") or "", item.get("topics") or [], readme, extra)
    title_blob = normalize_repo_name(repo_name)
    heuristic = score_text(blob, taxonomy, min_total=min_heuristic_score, title_blob=title_blob)

    return {
        "platform": "gitlab",
        "full_name": repo_name,
        "url": item["web_url"],
        "description": item.get("description") or "",
        "stars": item.get("star_count", 0),
        "language": None,
        "updated_at": item.get("last_activity_at"),
        "license": None,
        "topics": item.get("topics") or [],
        "readme_excerpt": readme,
        "extra_excerpt": extra,
        "readme_word_count": count_words(readme),
        "has_code": repo_has_code(paths),
        "repo_paths_sample": paths[:200],
        "is_fork": bool(item.get("forked_from_project")),
        "heuristic_strong_particle_hits": heuristic.strong_particle_hits,
        "heuristic_particle_hits": heuristic.particle_hits,
        "heuristic_support_hits": heuristic.support_hits,
        "heuristic_ai_hits": heuristic.ai_hits,
        "heuristic_negative_hits": heuristic.negative_hits,
        "heuristic_generic_radiotherapy_hits": heuristic.generic_radiotherapy_hits,
        "heuristic_title_strong_particle_hits": heuristic.title_strong_particle_hits,
        "heuristic_title_ai_hits": heuristic.title_ai_hits,
        "heuristic_total_score": heuristic.total_score,
        "heuristic_has_strong_particle_anchor": heuristic.has_strong_particle_anchor,
        "heuristic_passes": heuristic.passes,
        "heuristic_reasons": heuristic.reasons,
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


def load_manual_seed_repos() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    yaml_cfg = load_yaml("config/manual_seed_repos.yml")
    for repo in yaml_cfg.get("repos", []):
        if repo.get("url"):
            rows.append({
                "url": repo["url"].strip(),
                "always_include": bool(repo.get("always_include", False)),
                "platform": repo.get("platform", "manual"),
                "full_name": repo.get("full_name", ""),
                "description": repo.get("description", ""),
                "language": repo.get("language"),
                "topics": repo.get("topics", []) or [],
                "note": repo.get("note", ""),
                "tags": repo.get("tags", []) or [],
                "stars": int(repo.get("stars", 0) or 0),
                "updated_at": repo.get("updated_at"),
                "license": repo.get("license"),
                "readme_excerpt": repo.get("readme_excerpt", ""),
                "has_code": bool(repo.get("has_code", True)),
            })

    csv_path = Path("data/manual_seed_repos.csv")
    if csv_path.exists():
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                url = (row.get("url") or "").strip()
                if not url:
                    continue
                tags = [x.strip() for x in (row.get("tags") or "").split(";") if x.strip()]
                topics = [x.strip() for x in (row.get("topics") or "").split(";") if x.strip()]
                always_include = str(row.get("always_include", "")).strip().lower() in {"1", "true", "yes", "y"}
                has_code = str(row.get("has_code", "true")).strip().lower() in {"1", "true", "yes", "y"}

                rows.append({
                    "url": url,
                    "always_include": always_include,
                    "platform": (row.get("platform") or "manual").strip(),
                    "full_name": (row.get("full_name") or "").strip(),
                    "description": (row.get("description") or "").strip(),
                    "language": (row.get("language") or "").strip() or None,
                    "topics": topics,
                    "note": (row.get("note") or "").strip(),
                    "tags": tags,
                    "stars": int((row.get("stars") or "0").strip() or 0),
                    "updated_at": (row.get("updated_at") or "").strip() or None,
                    "license": (row.get("license") or "").strip() or None,
                    "readme_excerpt": (row.get("readme_excerpt") or "").strip(),
                    "has_code": has_code,
                })

    deduped: dict[str, dict[str, Any]] = {}
    for row in rows:
        deduped[row["url"]] = row
    return list(deduped.values())


def build_manual_metadata_record(seed: dict[str, Any], taxonomy: dict[str, Any], min_heuristic_score: int) -> dict[str, Any] | None:
    if not seed.get("url"):
        return None

    full_name = seed.get("full_name") or seed["url"]
    description = seed.get("description") or ""
    topics = seed.get("topics") or []
    readme_excerpt = seed.get("readme_excerpt") or ""
    extra_excerpt = ""

    blob = build_blob(full_name, description, topics, readme_excerpt, extra_excerpt)
    title_blob = normalize_repo_name(full_name)
    heuristic = score_text(blob, taxonomy, min_total=min_heuristic_score, title_blob=title_blob)

    return {
        "platform": seed.get("platform", "manual"),
        "full_name": full_name,
        "url": seed["url"],
        "description": description,
        "stars": int(seed.get("stars", 0) or 0),
        "language": seed.get("language"),
        "updated_at": seed.get("updated_at"),
        "license": seed.get("license"),
        "topics": topics,
        "readme_excerpt": readme_excerpt,
        "extra_excerpt": extra_excerpt,
        "readme_word_count": count_words(readme_excerpt),
        "has_code": bool(seed.get("has_code", True)),
        "repo_paths_sample": [],
        "is_fork": False,
        "is_manual": True,
        "forced_include": bool(seed.get("always_include", False)),
        "manual_note": seed.get("note", ""),
        "manual_tags": seed.get("tags", []) or [],
        "heuristic_strong_particle_hits": heuristic.strong_particle_hits,
        "heuristic_particle_hits": heuristic.particle_hits,
        "heuristic_support_hits": heuristic.support_hits,
        "heuristic_ai_hits": heuristic.ai_hits,
        "heuristic_negative_hits": heuristic.negative_hits,
        "heuristic_generic_radiotherapy_hits": heuristic.generic_radiotherapy_hits,
        "heuristic_title_strong_particle_hits": heuristic.title_strong_particle_hits,
        "heuristic_title_ai_hits": heuristic.title_ai_hits,
        "heuristic_total_score": heuristic.total_score,
        "heuristic_has_strong_particle_anchor": heuristic.has_strong_particle_anchor,
        "heuristic_passes": heuristic.passes,
        "heuristic_reasons": heuristic.reasons,
    }


def build_manual_seed_record(seed: dict[str, Any], taxonomy: dict[str, Any], min_heuristic_score: int) -> dict[str, Any] | None:
    if seed.get("full_name") and seed.get("description"):
        return build_manual_metadata_record(seed, taxonomy, min_heuristic_score)

    LOGGER.warning(
        "Skipping manual seed without sufficient metadata: %s (need at least full_name and description)",
        seed.get("url", "<missing-url>"),
    )
    return None


def derive_gitlab_queries_from_main_queries(main_queries: list[str], taxonomy: dict[str, Any]) -> list[str]:
    strong_terms = taxonomy.get("strong_particle_therapy_terms", [])
    derived: list[str] = []

    for query in main_queries:
        lowered = query.lower()
        for term in strong_terms:
            if term.lower() in lowered:
                derived.append(term)

    seen = set()
    result = []
    for q in derived:
        if q not in seen:
            seen.add(q)
            result.append(q)
    return result


def discover_github_repositories(queries: list[str], taxonomy: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    scraper_cfg = settings.get("scraper", {})
    github_per_query = int(scraper_cfg.get("github_per_query", 25))
    sleep_seconds = float(scraper_cfg.get("polite_sleep_seconds", 0.35))
    min_heuristic_score = int(scraper_cfg.get("min_heuristic_score", 4))

    seen: dict[str, dict[str, Any]] = {}
    for query in queries:
        LOGGER.info("GitHub query: %s", query)
        try:
            github_items = search_github_repositories(query, per_page=github_per_query)
            LOGGER.info("GitHub returned %d items for query %r", len(github_items), query)

            for item in github_items:
                record = build_github_record(item, taxonomy, min_heuristic_score)
                current = seen.get(record["url"])
                if current is None or record["heuristic_total_score"] > current["heuristic_total_score"]:
                    seen[record["url"]] = record
                polite_sleep(sleep_seconds)

            time.sleep(max(1.5, sleep_seconds))
        except Exception as exc:
            LOGGER.warning("GitHub query failed for %r: %s", query, exc)

    return list(seen.values())


def discover_gitlab_repositories(queries: list[str], taxonomy: dict[str, Any], settings: dict[str, Any]) -> list[dict[str, Any]]:
    scraper_cfg = settings.get("scraper", {})
    gitlab_per_query = int(scraper_cfg.get("gitlab_per_query", 25))
    sleep_seconds = float(scraper_cfg.get("polite_sleep_seconds", 0.35))
    min_heuristic_score = int(scraper_cfg.get("min_heuristic_score", 4))

    seen: dict[str, dict[str, Any]] = {}
    for query in queries:
        LOGGER.info("GitLab query: %s", query)
        try:
            gitlab_items = search_gitlab_projects(query, per_page=gitlab_per_query)
            LOGGER.info("GitLab returned %d items for query %r", len(gitlab_items), query)

            for item in gitlab_items:
                record = build_gitlab_record(item, taxonomy, min_heuristic_score)
                current = seen.get(record["url"])
                if current is None or record["heuristic_total_score"] > current["heuristic_total_score"]:
                    seen[record["url"]] = record
                polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("GitLab query failed for %r: %s", query, exc)

    return list(seen.values())


def merge_and_sort_candidates(*candidate_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for group in candidate_groups:
        for row in group:
            current = seen.get(row["url"])
            if current is None or row["heuristic_total_score"] > current["heuristic_total_score"]:
                seen[row["url"]] = row

    return sorted(
        seen.values(),
        key=lambda row: (
            row.get("stars", 0),
            row["heuristic_total_score"],
            row["heuristic_strong_particle_hits"] + row["heuristic_title_strong_particle_hits"],
            row["heuristic_ai_hits"] + row["heuristic_title_ai_hits"],
        ),
        reverse=True,
    )


def passes_quality_filters(repo: dict[str, Any], settings: dict[str, Any]) -> bool:
    scraper_cfg = settings.get("scraper", {})
    require_code = bool(scraper_cfg.get("require_code", True))
    min_readme_words = int(scraper_cfg.get("min_readme_words", 100))
    bypass = bool(scraper_cfg.get("force_include_bypasses_quality_filters", True))

    if repo.get("forced_include", False) and bypass:
        return True

    if require_code and not repo.get("has_code", False):
        return False

    if repo.get("readme_word_count", 0) < min_readme_words:
        return False

    return True


def run() -> int:
    queries_cfg = load_yaml("config/queries.yml")
    gitlab_queries_cfg = load_yaml("config/gitlab_queries.yml")
    taxonomy = load_yaml("config/taxonomy.yml")
    overrides = load_yaml("config/manual_overrides.yml")
    settings = load_yaml("config/settings.yml")

    github_queries = queries_cfg.get("queries", [])
    if not github_queries:
        raise ValueError("config/queries.yml contains no queries.")

    gitlab_queries = gitlab_queries_cfg.get("queries", [])
    if not gitlab_queries:
        gitlab_queries = derive_gitlab_queries_from_main_queries(github_queries, taxonomy)

    scraper_cfg = settings.get("scraper", {})
    llm_cfg = settings.get("llm", {})

    min_heuristic_score = int(scraper_cfg.get("min_heuristic_score", 4))
    classify_sleep_seconds = float(scraper_cfg.get("classify_sleep_seconds", 1.25))
    max_llm_repos = int(llm_cfg.get("max_repos_per_run", 25))
    llm_enabled = bool(llm_cfg.get("enabled", False))
    use_gitlab = bool(scraper_cfg.get("use_gitlab", True))
    cache_classifications = bool(scraper_cfg.get("cache_classifications", True))
    llm_cfg["cache_classifications"] = cache_classifications

    github_candidates = discover_github_repositories(github_queries, taxonomy, settings)
    gitlab_candidates = discover_gitlab_repositories(gitlab_queries, taxonomy, settings) if use_gitlab else []

    manual_seed_rows = load_manual_seed_repos()
    manual_seed_candidates: list[dict[str, Any]] = []
    for seed in manual_seed_rows:
        record = build_manual_seed_record(seed, taxonomy, min_heuristic_score)
        if record:
            manual_seed_candidates.append(record)

    LOGGER.info("GitHub candidate count: %d", len(github_candidates))
    LOGGER.info("GitLab candidate count: %d", len(gitlab_candidates))
    LOGGER.info("Manual seed candidate count: %d", len(manual_seed_candidates))

    all_candidates = merge_and_sort_candidates(github_candidates, gitlab_candidates, manual_seed_candidates)
    all_candidates = apply_overrides(all_candidates, overrides)

    safe_write_json("data/all_candidates.json", all_candidates)

    prefiltered: list[dict[str, Any]] = []
    for repo in all_candidates:
        if repo.get("is_fork") and not repo.get("forced_include", False):
            continue

        blob = build_blob(
            repo.get("full_name", ""),
            repo.get("description", ""),
            repo.get("topics", []),
            repo.get("readme_excerpt", ""),
            repo.get("extra_excerpt", ""),
        )
        title_blob = normalize_repo_name(repo.get("full_name", ""))

        heuristic = score_text(blob, taxonomy, min_total=min_heuristic_score, title_blob=title_blob)

        repo["heuristic_strong_particle_hits"] = heuristic.strong_particle_hits
        repo["heuristic_particle_hits"] = heuristic.particle_hits
        repo["heuristic_support_hits"] = heuristic.support_hits
        repo["heuristic_ai_hits"] = heuristic.ai_hits
        repo["heuristic_negative_hits"] = heuristic.negative_hits
        repo["heuristic_generic_radiotherapy_hits"] = heuristic.generic_radiotherapy_hits
        repo["heuristic_title_strong_particle_hits"] = heuristic.title_strong_particle_hits
        repo["heuristic_title_ai_hits"] = heuristic.title_ai_hits
        repo["heuristic_total_score"] = heuristic.total_score
        repo["heuristic_has_strong_particle_anchor"] = heuristic.has_strong_particle_anchor
        repo["heuristic_passes"] = heuristic.passes
        repo["heuristic_reasons"] = heuristic.reasons

        if not passes_quality_filters(repo, settings):
            continue

        if passes_prefilter(heuristic) or repo.get("forced_include", False):
            prefiltered.append(repo)

    prefiltered = sorted(
        prefiltered,
        key=lambda row: (
            row.get("stars", 0),
            row["heuristic_total_score"],
            row["heuristic_strong_particle_hits"] + row["heuristic_title_strong_particle_hits"],
            row["heuristic_ai_hits"] + row["heuristic_title_ai_hits"],
        ),
        reverse=True,
    )

    if llm_enabled:
        prefiltered = prefiltered[:max_llm_repos]

    included: list[dict[str, Any]] = []
    for repo in prefiltered:
        classification = classify_repo(repo=repo, llm_cfg=llm_cfg, cache_path="data/classification_cache.json")

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
            row.get("stars", 0),
            row["classification"].get("confidence", 0),
            row["heuristic_total_score"],
        ),
        reverse=True,
    )

    safe_write_json("data/catalog.json", included)
    write_readme(included)
    write_site(included)

    LOGGER.info("GitHub queries used: %d", len(github_queries))
    LOGGER.info("GitLab queries used: %d", len(gitlab_queries))
    LOGGER.info("All candidates: %d", len(all_candidates))
    LOGGER.info("Prefiltered candidates: %d", len(prefiltered))
    LOGGER.info("Included repositories: %d", len(included))

    return 0
