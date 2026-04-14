from __future__ import annotations

import base64
import os
import time
from typing import Any

import requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "particle-therapy-ai-catalog/1.0"})


def _request_json(method: str, url: str, *, headers=None, params=None, json_body=None) -> Any:
    response = SESSION.request(
        method=method,
        url=url,
        headers=headers,
        params=params,
        json=json_body,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


def gitlab_headers() -> dict[str, str]:
    headers = {}
    if GITLAB_TOKEN:
        headers["PRIVATE-TOKEN"] = GITLAB_TOKEN
    return headers


def search_github_repositories(query: str, per_page: int = 25) -> list[dict[str, Any]]:
    return _request_json(
        "GET",
        "https://api.github.com/search/repositories",
        headers=github_headers(),
        params={"q": query, "sort": "updated", "order": "desc", "per_page": per_page},
    ).get("items", [])


def github_get_file(owner: str, repo: str, path: str) -> str:
    try:
        data = _request_json(
            "GET",
            f"https://api.github.com/repos/{owner}/{repo}/contents/{path}",
            headers=github_headers(),
        )
    except Exception:
        return ""
    if data.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def search_gitlab_projects(query: str, per_page: int = 25) -> list[dict[str, Any]]:
    return _request_json(
        "GET",
        "https://gitlab.com/api/v4/search",
        headers=gitlab_headers(),
        params={"scope": "projects", "search": query, "per_page": per_page},
    )


def gitlab_get_file(project_id: int, path: str, ref: str) -> str:
    encoded = requests.utils.quote(path, safe="")
    try:
        data = _request_json(
            "GET",
            f"https://gitlab.com/api/v4/projects/{project_id}/repository/files/{encoded}",
            headers=gitlab_headers(),
            params={"ref": ref},
        )
    except Exception:
        return ""
    if data.get("encoding") != "base64":
        return ""
    try:
        return base64.b64decode(data["content"]).decode("utf-8", errors="ignore")
    except Exception:
        return ""

def polite_sleep(seconds: float = 0.35) -> None:
    time.sleep(seconds)
