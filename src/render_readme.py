from __future__ import annotations

from pathlib import Path


def write_readme(entries: list[dict]) -> None:
    lines = [
        "# AI/ML in Particle Therapy Repository Catalog",
        "",
        "Automatically discovered repositories relevant to both particle therapy and machine learning / AI.",
        "",
        f"Included repositories: **{len(entries)}**",
        "",
        "Live site: `https://YOUR_USERNAME.github.io/YOUR_REPO_NAME/`",
        "",
        "| Repository | Platform | Stars | Type | Categories | Summary |",
        "|---|---:|---:|---|---|---|",
    ]

    for item in entries:
        cls = item["classification"]
        categories = ", ".join(cls.get("categories", [])[:4])
        summary = (cls.get("summary") or "").replace("|", " ")
        lines.append(
            f"| [{item['full_name']}]({item['url']}) | {item['platform']} | {item['stars']} | "
            f"{cls.get('likely_tool_type', '')} | {categories} | {summary} |"
        )

    Path("README.md").write_text("\n".join(lines), encoding="utf-8")
