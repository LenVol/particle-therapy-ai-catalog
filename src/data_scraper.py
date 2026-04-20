from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
import yaml
from huggingface_hub import HfApi

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ZENODO_API_BASE = "https://zenodo.org/api"
USER_AGENT = "particle-therapy-ai-catalog-data/1.0"
REQUEST_TIMEOUT = 30

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})
HF_API = HfApi()


@dataclass
class DatasetRecord:
    kind: str                 # "dataset" | "record"
    source: str               # "huggingface" | "zenodo"
    title: str
    url: str
    summary: str
    tags: list[str]
    license: str | None
    updated_at: str | None
    downloads: int | None
    likes: int | None
    doi: str | None
    creators: list[str]
    record_type: str | None
    heuristic_particle_hits: int
    heuristic_ai_hits: int
    heuristic_total_score: int
    heuristic_reasons: list[str]


@dataclass
class ToolRecord:
    kind: str                 # "tool"
    source: str               # "huggingface"
    full_name: str
    url: str
    description: str
    stars: int
    language: str | None
    updated_at: str | None
    license: str | None
    topics: list[str]
    classification: dict[str, Any]


PARTICLE_TERMS = [
    "particle therapy",
    "proton therapy",
    "proton radiotherapy",
    "hadron therapy",
    "ion beam therapy",
    "carbon ion therapy",
    "carbon-ion therapy",
    "heavy ion therapy",
    "proton beam therapy",
    "particle radiotherapy",
    "adaptive proton therapy",
    "range verification",
    "let",
    "rbe",
    "impt",
    "pencil beam",
]

AI_TERMS = [
    "deep learning",
    "machine learning",
    "artificial intelligence",
    "neural network",
    "cnn",
    "transformer",
    "pytorch",
    "tensorflow",
    "segmentation",
    "classification",
    "regression",
    "foundation model",
    "model",
]

NEGATIVE_TERMS = [
    "policy",
    "governance",
    "review",
    "survey",
]


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


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def count_words(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text or ""))


def count_hits(text: str, terms: list[str]) -> int:
    blob = normalize(text)
    return sum(1 for term in terms if normalize(term) in blob)


def score_blob(blob: str, min_total: int = 1, require_ai: bool = False) -> tuple[int, int, int, list[str], bool]:
    particle_hits = count_hits(blob, PARTICLE_TERMS)
    ai_hits = count_hits(blob, AI_TERMS)
    negative_hits = count_hits(blob, NEGATIVE_TERMS)

    total = particle_hits * 4 + ai_hits * 2 - negative_hits * 3

    reasons: list[str] = []
    if particle_hits:
        reasons.append(f"Matched {particle_hits} particle-therapy term(s).")
    if ai_hits:
        reasons.append(f"Matched {ai_hits} AI/ML term(s).")
    if negative_hits:
        reasons.append(f"Matched {negative_hits} negative term(s).")

    passes = particle_hits >= 1 and total >= min_total and (ai_hits >= 1 if require_ai else True)
    return particle_hits, ai_hits, total, reasons, passes


def polite_sleep(seconds: float) -> None:
    time.sleep(seconds)


def request_json(url: str, *, params: dict[str, Any] | None = None) -> Any:
    response = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


# -------------------------
# Hugging Face datasets
# -------------------------

def search_huggingface_datasets(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Use the official huggingface_hub client instead of raw /api/datasets.
    """
    items: list[dict[str, Any]] = []
    try:
        results = HF_API.list_datasets(
            search=query,
            sort="downloads",
            direction=-1,
            limit=limit,
            full=True,
        )
        for ds in results:
            items.append({
                "id": getattr(ds, "id", None),
                "downloads": getattr(ds, "downloads", None),
                "likes": getattr(ds, "likes", None),
                "lastModified": getattr(ds, "last_modified", None),
                "tags": list(getattr(ds, "tags", []) or []),
                "cardData": getattr(ds, "card_data", None) or {},
                "description": getattr(ds, "description", None),
            })
    except Exception as exc:
        LOGGER.warning("Hugging Face dataset client search failed for %r: %s", query, exc)
    return items


def build_huggingface_dataset_record(
    item: dict[str, Any],
    min_heuristic_score: int,
    min_description_words: int,
) -> DatasetRecord | None:
    dataset_id = item.get("id") or item.get("_id") or ""
    if not dataset_id:
        return None

    card_data = item.get("cardData") or {}
    summary = (
        card_data.get("summary")
        or item.get("description")
        or card_data.get("description")
        or ""
    )
    tags = item.get("tags") or []
    title = dataset_id

    blob = " ".join([
        title,
        summary,
        " ".join(tags),
        json.dumps(card_data, ensure_ascii=False),
    ])

    particle_hits, ai_hits, total, reasons, passes = score_blob(
        blob,
        min_total=min_heuristic_score,
        require_ai=False,
    )
    if not passes:
        return None
    if count_words(summary) < min_description_words:
        return None

    return DatasetRecord(
        kind="dataset",
        source="huggingface",
        title=title,
        url=f"https://huggingface.co/datasets/{dataset_id}",
        summary=summary,
        tags=tags[:20],
        license=card_data.get("license") or item.get("license"),
        updated_at=item.get("lastModified"),
        downloads=item.get("downloads") if isinstance(item.get("downloads"), int) else None,
        likes=item.get("likes") if isinstance(item.get("likes"), int) else None,
        doi=None,
        creators=[],
        record_type="dataset",
        heuristic_particle_hits=particle_hits,
        heuristic_ai_hits=ai_hits,
        heuristic_total_score=total,
        heuristic_reasons=reasons,
    )


# -------------------------
# Hugging Face models -> tools
# -------------------------

def search_huggingface_models(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Use the official huggingface_hub client instead of raw /api/models.
    """
    items: list[dict[str, Any]] = []
    try:
        results = HF_API.list_models(
            search=query,
            sort="downloads",
            direction=-1,
            limit=limit,
            full=True,
        )
        for model in results:
            items.append({
                "id": getattr(model, "id", None),
                "downloads": getattr(model, "downloads", None),
                "likes": getattr(model, "likes", None),
                "lastModified": getattr(model, "last_modified", None),
                "tags": list(getattr(model, "tags", []) or []),
                "cardData": getattr(model, "card_data", None) or {},
                "pipeline_tag": getattr(model, "pipeline_tag", None),
                "library_name": getattr(model, "library_name", None),
            })
    except Exception as exc:
        LOGGER.warning("Hugging Face model client search failed for %r: %s", query, exc)
    return items


def build_huggingface_model_tool_record(
    item: dict[str, Any],
    min_heuristic_score: int,
    min_description_words: int,
) -> ToolRecord | None:
    model_id = item.get("id") or item.get("_id") or ""
    if not model_id:
        return None

    card_data = item.get("cardData") or {}
    summary = (
        card_data.get("summary")
        or card_data.get("description")
        or ""
    )
    tags = item.get("tags") or []
    pipeline_tag = item.get("pipeline_tag")
    library_name = item.get("library_name")

    blob = " ".join([
        model_id,
        summary,
        " ".join(tags),
        str(pipeline_tag or ""),
        str(library_name or ""),
        json.dumps(card_data, ensure_ascii=False),
    ])

    particle_hits, ai_hits, total, reasons, passes = score_blob(
        blob,
        min_total=min_heuristic_score,
        require_ai=False,
    )
    if not passes:
        return None
    if count_words(summary) < min_description_words:
        return None

    topics = list(tags[:20])
    if pipeline_tag and pipeline_tag not in topics:
        topics.append(pipeline_tag)
    if library_name and library_name not in topics:
        topics.append(library_name)

    return ToolRecord(
        kind="tool",
        source="huggingface",
        full_name=model_id,
        url=f"https://huggingface.co/{model_id}",
        description=summary,
        stars=item.get("likes") if isinstance(item.get("likes"), int) else 0,
        language=None,
        updated_at=item.get("lastModified"),
        license=card_data.get("license") or item.get("license"),
        topics=topics,
        classification={
            "include": True,
            "confidence": 0,
            "summary": summary or "Hugging Face model",
            "particle_therapy_relevance": None,
            "ml_relevance": None,
            "categories": [],
            "reasons": reasons,
            "warnings": [],
            "likely_tool_type": "model_training_code",
        },
    )


# -------------------------
# Zenodo records -> data & records
# -------------------------

def search_zenodo_records(query: str, limit: int) -> list[dict[str, Any]]:
    """
    Search published Zenodo records.
    Omit sort because previous explicit value caused 400.
    Limit anonymous size to 25.
    """
    data = request_json(
        f"{ZENODO_API_BASE}/records",
        params={
            "q": query,
            "size": min(limit, 25),
        },
    )
    return data.get("hits", {}).get("hits", [])


def build_zenodo_record(
    item: dict[str, Any],
    min_heuristic_score: int,
    min_description_words: int,
    accepted_record_types: set[str],
    require_ai_terms: bool,
) -> DatasetRecord | None:
    metadata = item.get("metadata") or {}

    title = metadata.get("title") or ""
    description = strip_html(metadata.get("description") or "")
    keywords = metadata.get("keywords") or []
    creators = [c.get("name", "") for c in metadata.get("creators", []) if c.get("name")]
    doi = metadata.get("doi") or item.get("doi")
    publication_date = metadata.get("publication_date")
    record_id = item.get("id")

    raw_type = ((metadata.get("resource_type") or {}).get("type") or "").lower() or "other"
    if accepted_record_types and raw_type not in accepted_record_types:
        return None

    blob = " ".join([
        title,
        description,
        " ".join(keywords),
        raw_type,
    ])

    particle_hits, ai_hits, total, reasons, passes = score_blob(
        blob,
        min_total=min_heuristic_score,
        require_ai=require_ai_terms,
    )
    if not passes:
        return None
    if count_words(description) < min_description_words:
        return None

    return DatasetRecord(
        kind="record",
        source="zenodo",
        title=title or f"Zenodo record {record_id}",
        url=f"https://zenodo.org/records/{record_id}",
        summary=description[:1200],
        tags=keywords[:20],
        license=((metadata.get("license") or {}).get("id") if isinstance(metadata.get("license"), dict) else metadata.get("license")),
        updated_at=publication_date,
        downloads=None,
        likes=None,
        doi=doi,
        creators=creators[:10],
        record_type=raw_type,
        heuristic_particle_hits=particle_hits,
        heuristic_ai_hits=ai_hits,
        heuristic_total_score=total,
        heuristic_reasons=reasons,
    )


def dedupe_dataset_records(records: list[DatasetRecord]) -> list[DatasetRecord]:
    seen: dict[str, DatasetRecord] = {}
    for record in records:
        current = seen.get(record.url)
        if current is None or record.heuristic_total_score > current.heuristic_total_score:
            seen[record.url] = record

    return sorted(
        seen.values(),
        key=lambda r: (
            (r.downloads or 0) + (r.likes or 0),
            r.heuristic_total_score,
            r.updated_at or "",
        ),
        reverse=True,
    )


def dedupe_tool_records(records: list[ToolRecord]) -> list[ToolRecord]:
    seen: dict[str, ToolRecord] = {}
    for record in records:
        current = seen.get(record.url)
        if current is None or record.stars > current.stars:
            seen[record.url] = record

    return sorted(
        seen.values(),
        key=lambda r: (r.stars, r.updated_at or "", r.full_name),
        reverse=True,
    )


def run_data_scraper() -> int:
    queries_cfg = load_yaml("config/data_queries.yml")
    settings = load_yaml("config/data_settings.yml")

    ds_cfg = settings.get("data_scraper", {})
    min_heuristic_score = int(ds_cfg.get("min_heuristic_score", 1))
    hf_limit = int(ds_cfg.get("huggingface_limit_per_query", 30))
    zenodo_limit = int(ds_cfg.get("zenodo_limit_per_query", 25))
    sleep_seconds = float(ds_cfg.get("polite_sleep_seconds", 0.5))
    min_description_words = int(ds_cfg.get("require_description_words", 5))
    accepted_record_types = set((ds_cfg.get("zenodo_accept_record_types", []) or []))
    require_ai_terms = bool(ds_cfg.get("zenodo_require_ai_terms", False))

    hf_model_queries = queries_cfg.get("huggingface_model_queries", [])
    hf_dataset_queries = queries_cfg.get("huggingface_dataset_queries", [])
    zenodo_queries = queries_cfg.get("zenodo_queries", [])

    dataset_candidates: list[DatasetRecord] = []
    tool_candidates: list[ToolRecord] = []

    for query in hf_model_queries:
        LOGGER.info("Hugging Face model query: %s", query)
        try:
            items = search_huggingface_models(query, hf_limit)
            LOGGER.info("Hugging Face models returned %d items for %r", len(items), query)
            for item in items:
                record = build_huggingface_model_tool_record(
                    item,
                    min_heuristic_score,
                    min_description_words,
                )
                if record:
                    tool_candidates.append(record)
                polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("Hugging Face model query failed for %r: %s", query, exc)

    for query in hf_dataset_queries:
        LOGGER.info("Hugging Face dataset query: %s", query)
        try:
            items = search_huggingface_datasets(query, hf_limit)
            LOGGER.info("Hugging Face datasets returned %d items for %r", len(items), query)
            for item in items:
                record = build_huggingface_dataset_record(
                    item,
                    min_heuristic_score,
                    min_description_words,
                )
                if record:
                    dataset_candidates.append(record)
                polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("Hugging Face dataset query failed for %r: %s", query, exc)

    for query in zenodo_queries:
        LOGGER.info("Zenodo query: %s", query)
        try:
            items = search_zenodo_records(query, zenodo_limit)
            LOGGER.info("Zenodo returned %d items for %r", len(items), query)
            for item in items:
                record = build_zenodo_record(
                    item,
                    min_heuristic_score,
                    min_description_words,
                    accepted_record_types,
                    require_ai_terms,
                )
                if record:
                    dataset_candidates.append(record)
                polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("Zenodo query failed for %r: %s", query, exc)

    kept_datasets = dedupe_dataset_records(dataset_candidates)
    kept_tools = dedupe_tool_records(tool_candidates)

    safe_write_json("data/all_dataset_candidates.json", [asdict(x) for x in dataset_candidates])
    safe_write_json("data/datasets.json", [asdict(x) for x in kept_datasets])
    safe_write_json("data/hf_model_tools.json", [asdict(x) for x in kept_tools])

    LOGGER.info("Dataset candidates: %d", len(dataset_candidates))
    LOGGER.info("Dataset/record items kept: %d", len(kept_datasets))
    LOGGER.info("HF model tool items kept: %d", len(kept_tools))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_data_scraper())
