from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ISSUE_BODY = os.environ.get("ISSUE_BODY", "")
ISSUE_URL = os.environ.get("ISSUE_URL", "")
ISSUE_NUMBER = os.environ.get("ISSUE_NUMBER", "")
ISSUE_TITLE = os.environ.get("ISSUE_TITLE", "")


def extract_field(body: str, label: str) -> str:
    pattern = rf"### {re.escape(label)}\s*\n\n(.*?)(?=\n\n### |\Z)"
    match = re.search(pattern, body, flags=re.DOTALL)
    if not match:
        return ""
    value = match.group(1).strip()
    value = re.sub(r"^_No response_$", "", value).strip()
    return value


def split_semicolon(value: str) -> list[str]:
    return [x.strip() for x in re.split(r"[;\n,]+", value or "") if x.strip()]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"repos": []}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"repos": []}


def save_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=1000),
        encoding="utf-8",
    )


def main() -> int:
    item_type = extract_field(ISSUE_BODY, "Item type")
    url = extract_field(ISSUE_BODY, "Public URL")
    name = extract_field(ISSUE_BODY, "Name / title")
    description = extract_field(ISSUE_BODY, "Short description")
    platform = extract_field(ISSUE_BODY, "Platform / source") or "manual"
    language = extract_field(ISSUE_BODY, "Language, if code/model") or None
    topics = split_semicolon(extract_field(ISSUE_BODY, "Topics / keywords"))
    note = extract_field(ISSUE_BODY, "Curator note")

    if not url or not name or not description:
        raise ValueError("Missing required issue fields.")

    if item_type == "paper":
        out = Path("config/manual_paper_submissions.yml")
        data = load_yaml(out)
        data.setdefault("papers", [])
        if not any(x.get("url") == url for x in data["papers"]):
            data["papers"].append(
                {
                    "url": url,
                    "title": name,
                    "description": description,
                    "source": platform,
                    "topics": topics,
                    "note": note,
                    "submitted_via": ISSUE_URL,
                    "submitted_issue": ISSUE_NUMBER,
                }
            )
        save_yaml(out, data)
        return 0

    out = Path("config/manual_seed_repos.yml")
    data = load_yaml(out)
    data.setdefault("repos", [])

    if not any(x.get("url") == url for x in data["repos"]):
        data["repos"].append(
            {
                "url": url,
                "always_include": True,
                "platform": platform,
                "full_name": name,
                "description": description,
                "language": language,
                "topics": topics,
                "note": note or f"Submitted through website issue form. {ISSUE_URL}",
                "tags": ["community submission", item_type],
                "has_code": item_type == "tool",
            }
        )

    save_yaml(out, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
