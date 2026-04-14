from __future__ import annotations

import json
from pathlib import Path


def write_site(entries: list[dict]) -> None:
    site_dir = Path("site")
    site_dir.mkdir(exist_ok=True)

    (site_dir / "catalog.json").write_text(
        json.dumps(entries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
