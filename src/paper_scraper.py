from __future__ import annotations

import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import requests
import yaml

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ARXIV_API = "https://export.arxiv.org/api/query"
EUROPEPMC_API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
CROSSREF_API = "https://api.crossref.org/works"

USER_AGENT = "particle-therapy-ai-catalog-papers/1.0"
REQUEST_TIMEOUT = 90

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})


@dataclass
class PaperRecord:
    kind: str
    source: str
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


STRONG_PARTICLE_TERMS = [
    "particle therapy",
    "proton therapy",
    "proton radiotherapy",
    "proton beam therapy",
    "hadron therapy",
    "ion beam therapy",
    "carbon ion therapy",
    "carbon-ion therapy",
    "heavy ion therapy",
    "particle radiotherapy",
    "adaptive proton therapy",
    "intensity modulated proton therapy",
    "impt",
]

CONTEXT_PARTICLE_TERMS = [
    "range verification",
    "pencil beam scanning",
    "linear energy transfer",
    "relative biological effectiveness",
]

AI_TERMS = [
    "machine learning",
    "deep learning",
    "artificial intelligence",
    "neural network",
    "convolutional neural network",
    "cnn",
    "transformer",
    "auto-segmentation",
    "dose prediction",
    "outcome prediction",
    "radiomics",
]

NEGATIVE_TERMS = [
    "couple therapy",
    "infertility",
    "sexual satisfaction",
    "psychological",
    "counseling",
    "nursing",
    "policy",
    "editorial",
    "letter to the editor",
]


def load_yaml(path: str) -> dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {}
    return yaml.safe_load(file_path.read_text(encoding="utf-8")) or {}


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


def has_phrase(text: str, phrase: str) -> bool:
    blob = normalize(text)
    phrase_norm = normalize(phrase)
    return re.search(rf"\b{re.escape(phrase_norm)}\b", blob) is not None


def count_phrase_hits(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if has_phrase(text, term))


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text or "")


def polite_sleep(seconds: float) -> None:
    time.sleep(seconds)

def request_with_retries(
    url: str,
    *,
    params: dict[str, Any],
    timeout: int = REQUEST_TIMEOUT,
    attempts: int = 5,
    base_sleep: float = 10.0,
) -> requests.Response:
    last_exc: Exception | None = None
    retry_statuses = {429, 502, 503, 504}

    for attempt in range(attempts):
        try:
            response = SESSION.get(url, params=params, timeout=timeout)

            if response.status_code in retry_statuses:
                sleep_for = base_sleep * (attempt + 1)
                LOGGER.warning(
                    "Retryable HTTP %s, retrying in %.1fs [%d/%d]",
                    response.status_code,
                    sleep_for,
                    attempt + 1,
                    attempts,
                )
                time.sleep(sleep_for)
                continue

            response.raise_for_status()
            return response

        except requests.RequestException as exc:
            last_exc = exc
            sleep_for = base_sleep * (attempt + 1)
            LOGGER.warning(
                "Request failed, retrying in %.1fs [%d/%d]: %s",
                sleep_for,
                attempt + 1,
                attempts,
                exc,
            )
            time.sleep(sleep_for)

    if last_exc:
        raise last_exc

    raise RuntimeError(f"Request failed after {attempts} attempts: {url}")

def score_blob(blob: str, min_total: int) -> tuple[int, int, int, list[str], bool]:
    strong_particle_hits = count_phrase_hits(blob, STRONG_PARTICLE_TERMS)
    context_particle_hits = count_phrase_hits(blob, CONTEXT_PARTICLE_TERMS)
    ai_hits = count_phrase_hits(blob, AI_TERMS)
    negative_hits = count_phrase_hits(blob, NEGATIVE_TERMS)

    total = (
        strong_particle_hits * 8
        + context_particle_hits * 2
        + ai_hits * 5
        - negative_hits * 20
    )

    reasons: list[str] = []
    if strong_particle_hits:
        reasons.append(f"Matched {strong_particle_hits} strong particle-therapy phrase(s).")
    if context_particle_hits:
        reasons.append(f"Matched {context_particle_hits} contextual particle-therapy phrase(s).")
    if ai_hits:
        reasons.append(f"Matched {ai_hits} AI/ML phrase(s).")
    if negative_hits:
        reasons.append(f"Matched {negative_hits} negative phrase(s).")

    passes = (
        negative_hits == 0
        and strong_particle_hits >= 1
        and ai_hits >= 1
        and total >= min_total
    )

    return strong_particle_hits + context_particle_hits, ai_hits, total, reasons, passes


def is_review_like(record_type: str | None, title: str) -> bool:
    text = normalize(" ".join([record_type or "", title or ""]))
    return (
        "review" in text
        or "survey" in text
        or "editorial" in text
        or "letter to the editor" in text
    )


def passes_record_filters(
    title: str,
    abstract: str,
    record_type: str | None,
    include_reviews: bool,
    min_abstract_words: int,
) -> bool:
    if count_words(abstract) < min_abstract_words:
        return False

    if not include_reviews and is_review_like(record_type, title):
        return False

    return True


# -------------------------
# arXiv
# -------------------------

def search_arxiv(
    query: str,
    limit: int,
    min_score: int,
    include_reviews: bool,
    min_abstract_words: int,
) -> list[PaperRecord]:
    response = request_with_retries(
        ARXIV_API,
        params={
            "search_query": query,
            "start": 0,
            "max_results": min(limit, 5),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        attempts=5,
        base_sleep=15.0,
    )

    root = ET.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    records: list[PaperRecord] = []

    for entry in root.findall("atom:entry", ns):
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip()
        abstract = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip()
        published = entry.findtext("atom:published", default=None, namespaces=ns)
        url = entry.findtext("atom:id", default="", namespaces=ns)

        authors = [
            a.findtext("atom:name", default="", namespaces=ns)
            for a in entry.findall("atom:author", ns)
        ]
        authors = [a for a in authors if a]

        if not passes_record_filters(title, abstract, "preprint", include_reviews, min_abstract_words):
            continue

        blob = " ".join([title, abstract])
        p_hits, a_hits, total, reasons, passes = score_blob(blob, min_score)
        if not passes:
            continue

        records.append(
            PaperRecord(
                kind="paper",
                source="arxiv",
                title=title,
                url=url,
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

def search_europepmc(
    query: str,
    limit: int,
    min_score: int,
    include_reviews: bool,
    min_abstract_words: int,
) -> list[PaperRecord]:
    response = request_with_retries(
        EUROPEPMC_API,
        params={
            "query": query,
            "format": "json",
            "pageSize": limit,
            "sort": "DATE_DESC",
            "resultType": "core",
        },
        attempts=3,
        base_sleep=3.0,
    )

    items = response.json().get("resultList", {}).get("result", [])
    records: list[PaperRecord] = []

    for item in items:
        title = item.get("title", "") or ""
        abstract = strip_html(item.get("abstractText", "") or "")
        record_type = item.get("pubType")
        journal = item.get("journalTitle")
        doi = item.get("doi")

        if not passes_record_filters(title, abstract, record_type, include_reviews, min_abstract_words):
            continue

        authors = []
        if item.get("authorString"):
            authors = [x.strip() for x in item["authorString"].split(",") if x.strip()]

        url = ""
        full_urls = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
        if isinstance(full_urls, list) and full_urls:
            url = full_urls[0].get("url", "") or ""
        if not url and doi:
            url = f"https://doi.org/{doi}"
        if not url:
            src = item.get("source")
            ext_id = item.get("id")
            if src and ext_id:
                url = f"https://europepmc.org/article/{src}/{ext_id}"

        blob = " ".join([title, abstract, journal or "", record_type or ""])
        p_hits, a_hits, total, reasons, passes = score_blob(blob, min_score)
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
                journal=journal,
                published_at=item.get("firstPublicationDate") or item.get("pubYear"),
                doi=doi,
                is_preprint=(record_type or "").lower() == "preprint",
                paper_type=record_type,
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

def crossref_date(item: dict[str, Any]) -> str | None:
    parts = (
        item.get("published-print", {}).get("date-parts")
        or item.get("published-online", {}).get("date-parts")
        or item.get("published", {}).get("date-parts")
        or item.get("created", {}).get("date-parts")
        or []
    )
    if not parts or not parts[0]:
        return None
    return "-".join(str(x) for x in parts[0])


def search_crossref(
    query: str,
    limit: int,
    min_score: int,
    include_reviews: bool,
    min_abstract_words: int,
) -> list[PaperRecord]:
    response = request_with_retries(
        CROSSREF_API,
        params={
            "query.bibliographic": query,
            "rows": limit,
            "sort": "published",
            "order": "desc",
        },
        attempts=3,
        base_sleep=3.0,
    )

    items = response.json().get("message", {}).get("items", [])
    records: list[PaperRecord] = []

    for item in items:
        title = (item.get("title") or [""])[0]
        abstract = strip_html(item.get("abstract") or "")
        record_type = item.get("type")
        doi = item.get("DOI")

        journal = None
        if item.get("container-title"):
            journal = item["container-title"][0]

        if not passes_record_filters(title, abstract, record_type, include_reviews, min_abstract_words):
            continue

        authors: list[str] = []
        for author in item.get("author", []) or []:
            given = author.get("given", "")
            family = author.get("family", "")
            name = " ".join(x for x in [given, family] if x).strip()
            if name:
                authors.append(name)

        blob = " ".join([title, abstract, journal or "", record_type or ""])
        p_hits, a_hits, total, reasons, passes = score_blob(blob, min_score)
        if not passes:
            continue

        records.append(
            PaperRecord(
                kind="paper",
                source="crossref",
                title=title,
                url=f"https://doi.org/{doi}" if doi else item.get("URL", ""),
                abstract=abstract,
                authors=authors,
                journal=journal,
                published_at=crossref_date(item),
                doi=doi,
                is_preprint=False,
                paper_type=record_type,
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
        key = normalize(record.doi or record.title)
        if not key:
            continue

        current = seen.get(key)
        if current is None:
            seen[key] = record
            continue

        if record.heuristic_total_score > current.heuristic_total_score:
            seen[key] = record
        elif record.heuristic_total_score == current.heuristic_total_score and record.doi and not current.doi:
            seen[key] = record
        elif (
            record.heuristic_total_score == current.heuristic_total_score
            and current.source == "arxiv"
            and record.source in {"europepmc", "crossref"}
        ):
            seen[key] = record

    return sorted(
        seen.values(),
        key=lambda r: (
            r.published_at or "",
            r.heuristic_total_score,
        ),
        reverse=True,
    )


def run_paper_scraper() -> int:
    queries_cfg = load_yaml("config/paper_queries.yml")
    settings = load_yaml("config/paper_settings.yml")
    cfg = settings.get("paper_scraper", {})

    arxiv_limit = int(cfg.get("arxiv_limit_per_query", 10))
    europepmc_limit = int(cfg.get("europepmc_limit_per_query", 25))
    crossref_limit = int(cfg.get("crossref_limit_per_query", 25))
    sleep_seconds = float(cfg.get("polite_sleep_seconds", 3.2))
    min_score = int(cfg.get("min_heuristic_score", 13))
    min_abstract_words = int(cfg.get("min_abstract_words", 30))
    include_preprints = bool(cfg.get("include_preprints", True))
    include_journal_articles = bool(cfg.get("include_journal_articles", True))
    include_reviews = bool(cfg.get("include_reviews", False))

    candidates: list[PaperRecord] = []

    if include_preprints:
        for query in queries_cfg.get("arxiv_queries", []):
            LOGGER.info("arXiv query: %s", query)
            try:
                candidates.extend(
                    search_arxiv(
                        query,
                        arxiv_limit,
                        min_score,
                        include_reviews,
                        min_abstract_words,
                    )
                )
                polite_sleep(sleep_seconds)
            except Exception as exc:
                LOGGER.warning("arXiv query failed for %r: %s", query, exc)

    for query in queries_cfg.get("europepmc_queries", []):
        LOGGER.info("Europe PMC query: %s", query)
        try:
            candidates.extend(
                search_europepmc(
                    query,
                    europepmc_limit,
                    min_score,
                    include_reviews,
                    min_abstract_words,
                )
            )
            polite_sleep(sleep_seconds)
        except Exception as exc:
            LOGGER.warning("Europe PMC query failed for %r: %s", query, exc)

    if include_journal_articles:
        for query in queries_cfg.get("crossref_queries", []):
            LOGGER.info("Crossref query: %s", query)
            try:
                candidates.extend(
                    search_crossref(
                        query,
                        crossref_limit,
                        min_score,
                        include_reviews,
                        min_abstract_words,
                    )
                )
                polite_sleep(sleep_seconds)
            except Exception as exc:
                LOGGER.warning("Crossref query failed for %r: %s", query, exc)

    kept = dedupe_papers(candidates)

    safe_write_json("data/all_paper_candidates.json", [asdict(x) for x in candidates])
    safe_write_json("data/papers.json", [asdict(x) for x in kept])

    LOGGER.info("Paper candidates: %d", len(candidates))
    LOGGER.info("Paper items kept: %d", len(kept))

    for paper in kept[:10]:
        LOGGER.info(
            "KEPT: %s | score=%s | reasons=%s",
            paper.title,
            paper.heuristic_total_score,
            "; ".join(paper.heuristic_reasons),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(run_paper_scraper())
