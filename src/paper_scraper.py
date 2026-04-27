from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
import yaml

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ARXIV_API = "https://export.arxiv.org/api/query"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CROSSREF_API = "https://api.crossref.org/works"

USER_AGENT = "particle-therapy-ai-catalog-papers/1.0 (mailto:maintainer@example.com)"
REQUEST_TIMEOUT = 30

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})

PARTICLE_TERMS = [
    "particle therapy",
    "proton therapy",
    "proton radiotherapy",
    "hadron therapy",
    "ion beam therapy",
    "carbon ion therapy",
    "carbon-ion therapy",
    "proton beam therapy",
    "adaptive proton therapy",
    "range verification",
    "let",
    "rbe",
    "impt",
    "pencil beam",
    "proton",
    "hadron",
    "carbon ion",
]

AI_TERMS = [
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "neural network",
    "cnn",
    "transformer",
    "segmentation",
    "classification",
    "regression",
    "outcome prediction",
    "dose prediction",
    "model",
]

NEGATIVE_TERMS = [
    "review",
    "survey",
    "editorial",
]


@dataclass
class PaperRecord:
    kind: str                    # "paper"
    source: str                  # "arxiv" | "europepmc" | "crossref"
    title: str
    url: str
    abstract: str
    authors: list[str]
    journal: str | None
    published_at: str | None
    doi: str | None
    is_preprint: bool
    paper_type: str | None
    heuristic_particle_hits: int
    heuristic_ai_hits: int
    heuristic_total_score: int
    heuristic_reasons: list[str]


def load_yaml(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    with open(file_path, "r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        try:
            return obj.isoformat()
        except Exception:
            pass
    return str(obj)


def safe_write_json(path: str | Path, payload: Any) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=_json_default),
        encoding="utf-8",
    )


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


def score_blob(blob: str, min_total: int = 1) -> tuple[int, int, int, list[str], bool]:
    particle_hits = count_hits(blob, PARTICLE_TERMS)
    ai_hits = count_hits(blob, AI_TERMS)
    negative_hits = count_hits(blob, NEGATIVE_TERMS)

    total = particle_hits * 4 + ai_hits * 3 - negative_hits * 2

    reasons: list[str] = []
    if particle_hits:
        reasons.append(f"Matched {particle_hits} particle-therapy term(s).")
    if ai_hits:
        reasons.append(f"Matched {ai_hits} AI/ML term(s).")
    if negative_hits:
        reasons.append(f"Matched {negative_hits} review/editorial term(s).")

    passes = particle_hits >= 1 and total >= min_total
    return particle_hits, ai_hits, total, reasons, passes


def polite_sleep(seconds: float) -> None:
    time.sleep(seconds)


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


# -------------------------
# arXiv
# -------------------------

def search_arxiv(query: str, limit: int) -> list[PaperRecord]:
    params = {
        "search_query": query,
        "start": 0,
        "max_results": limit,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    response = SESSION.get(ARXIV_API, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }

    records: list[PaperRecord] = []
    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        published = entry.findtext("atom:published", default=None, namespaces=ns)
        paper_url = entry.findtext("atom:id", default="", namespaces=ns)

        authors = []
        for author in entry.findall("atom:author", ns):
            name = author.findtext("atom:name", default="", namespaces=ns)
            if name:
                authors.append(name)

        blob = " ".join([title, abstract])
        p_hits, a_hits, total, reasons, passes = score_blob(blob)

        if not passes:
            continue

        records.append(
            PaperRecord(
                kind="paper",
                source="arxiv",
                title=title,
                url=paper_url,
                abstract=abstract,
                authors=authors,
                journal=None,
                published_at=published,
                doi=None,
                is_preprint=True,
                paper_type="preprint",
                heuristic_particle_hits=p_hits,
                heuristic_ai_hits=a_hits,
                heuristic_total_score=total,
                heuristic_reasons=reasons,
            )
        )

    return records


# -------------------------
# Europe PMC
# -------------------------

def search_europepmc(query: str, limit: int, include_reviews: bool) -> list[PaperRecord]:
    params = {
        "query": query,
        "format": "json",
        "pageSize": limit,
        "sort": "DATE_DESC",
        "resultType": "core",
    }

    data = SESSION.get(EUROPEPMC_API, params=params, timeout=REQUEST_TIMEOUT).json()
    items = data.get("resultList", {}).get("result", [])

    records: list[PaperRecord] = []
    for item in items:
        title = item.get("title", "") or ""
        abstract = item.get("abstractText", "") or ""
        authors = []
        if item.get("authorString"):
            authors = [x.strip() for x in item["authorString"].split(",") if x.strip()]

        pub_type = item.get("pubType")
        if not include_reviews and pub_type and "review" in pub_type.lower():
            continue

        paper_url = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
        if isinstance(paper_url, list) and paper_url:
            url = paper_url[0].get("url")
        else:
            url = item.get("doi") and f"https://doi.org/{item['doi']}"
            if not url:
                src = item.get("source")
                ext_id = item.get("id")
                url = f"https://europepmc.org/article/{src}/{ext_id}" if src and ext_id else ""

        blob = " ".join([title, abstract, item.get("journalTitle", "") or ""])
        p_hits, a_hits, total, reasons, passes = score_blob(blob)
        if not passes:
            continue

        records.append(
            PaperRecord(
                kind="paper",
                source="europepmc",
                title=title,
                url=url,
                abstract=abstract,
                authors=authors,
                journal=item.get("journalTitle"),
                published_at=item.get("firstPublicationDate") or item.get("pubYear"),
                doi=item.get("doi"),
                is_preprint=(item.get("pubType") or "").lower() == "preprint",
                paper_type=item.get("pubType"),
                heuristic_particle_hits=p_hits,
                heuristic_ai_hits=a_hits,
                heuristic_total_score=total,
                heuristic_reasons=reasons,
            )
        )

    return records


# -------------------------
# Crossref
# -------------------------

def search_crossref(query: str, limit: int, include_reviews: bool) -> list[PaperRecord]:
    params = {
        "query.bibliographic": query,
        "rows": limit,
        "sort": "published",
        "order": "desc",
    }

    response = SESSION.get(CROSSREF_API, params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    items = response.json().get("message", {}).get("items", [])

    records: list[PaperRecord] = []
    for item in items:
        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        abstract = strip_html(item.get("abstract") or "")
        journal_list = item.get("container-title") or []
        journal = journal_list[0] if journal_list else None
        doi = item.get("DOI")
        item_type = item.get("type")

        if not include_reviews and item_type and "review" in item_type.lower():
            continue

        authors = []
        for a in item.get("author", []) or []:
            given = a.get("given", "")
            family = a.get("family", "")
            name = " ".join(x for x in [given, family] if x).strip()
            if name:
                authors.append(name)

        url = f"https://doi.org/{doi}" if doi else (item.get("URL") or "")
        date_parts = (
            item.get("published-print", {}).get("date-parts")
            or item.get("published-online", {}).get("date-parts")
            or item.get("created", {}).get("date-parts")
            or []
        )
        published_at = None
        if date_parts and date_parts[0]:
            published_at = "-".join(str(x) for x in date_parts[0])

        blob = " ".join([title, abstract, journal or ""])
        p_hits, a_hits, total, reasons, passes = score_blob(blob)
        if not passes:
            continue

        records.append(
            PaperRecord(
                kind="paper",
                source="crossref",
                title=title,
                url=url,
                abstract=abstract,
                authors=authors,
                journal=journal,
                published_at=published_at,
                doi=doi,
                is_preprint=False,
                paper_type=item_type,
                heuristic_particle_hits=p_hits,
                heuristic_ai_hits=a_hits,
                heuristic_total_score=total,
                heuristic_reasons=reasons,
            )
        )

    return records


def dedupe_papers(records: list[PaperRecord]) -> list[PaperRecord]:
    seen: dict[str, PaperRecord] = {}
    for record in records:
        key = record.doi or normalize(record.title)
        current = seen.get(key)
        if current is None or record.heuristic_total_score > current.heuristic_total_score:
            seen[key] = record

    return sorted(
        seen.values(),
        key=lambda r: (
            r.published_at or "",
            r.heuristic_total_score,
            r.source,
        ),
        reverse=True,
    )


def run_paper_scraper() -> int:
    queries_cfg = load_yaml("config/paper_queries.yml")
    settings = load_yaml("config/paper_settings.yml")

    cfg = settings.get("paper_scraper", {})
    arxiv_limit = int(cfg.get("arxiv_limit_per_query", 25))
    europepmc_limit = int(cfg.get("europepmc_limit_per_query", 25))
    crossref_limit = int(cfg.get("crossref_limit_per_query", 25))
    sleep_seconds = float(cfg.get("polite_sleep_seconds", 0.4))
    min_score = int(cfg.get("min_heuristic_score", 1))
    min_abstract_words = int(cfg.get("min_abstract_words", 20))
    include_preprints = bool(cfg.get("include_preprints", True))
    include_journal_articles = bool(cfg.get("include_journal_articles", True))
    include_reviews = bool(cfg.get("include_reviews", False))

    arxiv_queries = queries_cfg.get("arxiv_queries", [])
    europepmc_queries = queries_cfg.get("europepmc_queries", [])
    crossref_queries = queries_cfg.get("crossref_queries", [])

    candidates: list[PaperRecord] = []

    if include_preprints:
        for query in arxiv_queries:
            LOGGER.info("arXiv query: %s", query)
            try:
                items = search_arxiv(query, arxiv_limit)
                for item in items:
                    if count_words(item.abstract) >= min_abstract_words:
                        candidates.append(item)
                polite_sleep(sleep_seconds)
            except Exception as exc:
                LOGGER.warning("arXiv query failed for %r: %s", query, exc)

    for query in europepmc_queries:
        LOGGER.info("Europe PMC query: %s", query)
        try:
            items = search_europepmc(query, europepmc_limit, include_reviews=include_reviews)
            for item in items:
                if count_words(item.abstract) >= min_abstract_words:
                    if include_journal_articles or item.is_preprint:
                        candidates.append(item)
            polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("Europe PMC query failed for %r: %s", query, exc)

    if include_journal_articles:
        for query in crossref_queries:
            LOGGER.info("Crossref query: %s", query)
            try:
                items = search_crossref(query, crossref_limit, include_reviews=include_reviews)
                for item in items:
                    if count_words(item.abstract) >= min_abstract_words:
                        candidates.append(item)
                polite_sleep(sleep_seconds)
            except Exception as exc:
                LOGGER.warning("Crossref query failed for %r: %s", query, exc)

    deduped = dedupe_papers(candidates)

    # keep explicit score floor after source-specific parsing
    kept = [x for x in deduped if x.heuristic_total_score >= min_score]

    safe_write_json("data/all_paper_candidates.json", [asdict(x) for x in candidates])
    safe_write_json("data/papers.json", [asdict(x) for x in kept])

    LOGGER.info("Paper candidates: %d", len(candidates))
    LOGGER.info("Paper items kept: %d", len(kept))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_paper_scraper())
