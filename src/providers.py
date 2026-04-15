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
    """
    Generic JSON request helper with basic retry and rate-limit handling.

    Handles:
    - GitHub primary rate limits via x-ratelimit-reset
    - retry-after headers
    - burst/secondary-limit-like 403/429 responses with backoff
    """
    max_attempts = 6
    last_response: requests.Response | None = None

    for attempt in range(max_attempts):
        response = SESSION.request(
            method=method,
            url=url,
            headers=headers,
            params=params,
            json=json_body,
            timeout=REQUEST_TIMEOUT,
        )
        last_response = response

        if response.status_code < 400:
            return response.json()

        if response.status_code in (403, 429):
            remaining = response.headers.get("x-ratelimit-remaining")
            reset_at = response.headers.get("x-ratelimit-reset")
            retry_after = response.headers.get("retry-after")

            if remaining == "0" and reset_at:
                try:
                    sleep_for = max(1, int(reset_at) - int(time.time()) + 1)
                except ValueError:
                    sleep_for = 5
                time.sleep(sleep_for)
                continue

            if retry_after:
                try:
                    sleep_for = max(1, int(float(retry_after)))
                except ValueError:
                    sleep_for = 5
                time.sleep(sleep_for)
                continue

            time.sleep(min(60, 2 ** attempt))
            continue

        response.raise_for_status()

    if last_response is not None:
        last_response.raise_for_status()

    raise RuntimeError(f"Request failed without a response: {method} {url}")


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
    data = _request_json(
        "GET",
        "https://api.github.com/search/repositories",
        headers=github_headers(),
        params={
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": per_page,
        },
    )
    return data.get("items", [])


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
        "https://gitlab.com/api/v4/projects",
        headers=gitlab_headers(),
        params={
            "search": query,
            "simple": True,
            "order_by": "last_activity_at",
            "sort": "desc",
            "per_page": per_page,
        },
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
