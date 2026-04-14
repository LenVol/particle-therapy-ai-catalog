from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.classifier import classify_repo
from src.providers import (
    github_get_file,
    polite_sleep,
    search_github_repositories,
    search_gitlab_projects,
    gitlab_get_file,
)
from src.render_readme import write_readme
from src.render_site import write_site
from src.scoring import score_text, passes_prefilter


README_CANDIDATES = ["README.md", "README.rst", "README.txt", "readme.md"]
EXTRA_FILES = ["requirements.txt", "pyproject.toml", "environment.yml", "setup.py"]


def load_yaml(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def build_github_record(item: dict, cfg: dict) -> dict:
    full_name = item["full_name"]
    owner, repo = full_name.split("/", 1)

    readme = ""
    for candidate in README_CANDIDATES:
        readme = github_get_file(owner, repo, candidate)
        if readme:
            break

    extra = []
    for candidate in EXTRA_FILES:
        text = github_get_file(owner, repo, candidate)
        if text:
            extra.append(text[:4000])

    blob = " ".join([
        item.get("description") or "",
        " ".join(item.get("topics") or []),
        readme[:12000],
        " ".join(extra),
    ])

    heuristic = score_text(
        blob,
        cfg["particle_therapy_terms"],
        cfg["ai_terms"],
        cfg["negative_terms"],
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
        "readme_excerpt": readme[:12000],
        "heuristic_pt_score": heuristic.pt_score,
        "heuristic_ai_score": heuristic.ai_score,
        "heuristic_negative_score": heuristic.negative_score,
        "heuristic_total_score": heuristic.total_score,
    }


def apply_overrides(entries: list[dict], overrides: dict) -> list[dict]:
    excluded = set(overrides.get("exclude", []))
    forced = set(overrides.get("include", []))
    notes = overrides.get("notes", {})
    tags = overrides.get("tags", {})

    output = []
    for entry in entries:
        if entry["url"] in excluded:
            continue
        if entry["url"] in notes:
            entry["manual_note"] = notes[entry["url"]]
        if entry["url"] in tags:
            entry["manual_tags"] = tags[entry["url"]]
        if entry["url"] in forced:
            entry["forced_include"] = True
        output.append(entry)
    return output


def run() -> int:
    queries = load_yaml("config/queries.yml")["queries"]
    cfg = load_yaml("config/taxonomy.yml")
    overrides = load_yaml("config/manual_overrides.yml")

    seen = {}

    for query in queries:
        for item in search_github_repositories(query):
            repo = build_github_record(item, cfg)
            current = seen.get(repo["url"])
            if current is None or repo["heuristic_total_score"] > current["heuristic_total_score"]:
                seen[repo["url"]] = repo
            polite_sleep()

        # GitLab support can be added here in the same pattern.

    all_candidates = sorted(
        seen.values(),
        key=lambda x: (x["heuristic_total_score"], x["stars"]),
        reverse=True,
    )
    all_candidates = apply_overrides(all_candidates, overrides)

    included = []
    for repo in all_candidates:
        keep = passes_prefilter(
            score_text(
                " ".join([
                    repo["description"],
                    " ".join(repo["topics"]),
                    repo.get("readme_excerpt", ""),
                ]),
                cfg["particle_therapy_terms"],
                cfg["ai_terms"],
                cfg["negative_terms"],
            )
        ) or repo.get("forced_include", False)

        if not keep:
            continue

        cls = classify_repo(repo)
        if not cls.include and not repo.get("forced_include", False):
            continue

        repo["classification"] = {
            "include": cls.include,
            "confidence": cls.confidence,
            "summary": cls.summary,
            "particle_therapy_relevance": cls.particle_therapy_relevance,
            "ml_relevance": cls.ml_relevance,
            "categories": cls.categories,
            "reasons": cls.reasons,
            "warnings": cls.warnings,
            "likely_tool_type": cls.likely_tool_type,
        }
        included.append(repo)

    Path("data").mkdir(exist_ok=True)
    Path("data/all_candidates.json").write_text(json.dumps(all_candidates, indent=2), encoding="utf-8")
    Path("data/catalog.json").write_text(json.dumps(included, indent=2), encoding="utf-8")

    write_readme(included)
    write_site(included)
    return 0
