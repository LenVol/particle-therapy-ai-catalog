from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class HeuristicResult:
    pt_score: int
    ai_score: int
    negative_score: int
    total_score: int


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def count_hits(text: str, terms: list[str]) -> int:
    blob = normalize(text)
    return sum(1 for term in terms if term.lower() in blob)


def score_text(blob: str, pt_terms: list[str], ai_terms: list[str], negative_terms: list[str]) -> HeuristicResult:
    pt = count_hits(blob, pt_terms)
    ai = count_hits(blob, ai_terms)
    neg = count_hits(blob, negative_terms)
    total = pt * 3 + ai * 2 - neg * 3
    return HeuristicResult(pt, ai, neg, total)


def passes_prefilter(result: HeuristicResult, min_total: int = 4) -> bool:
    return result.pt_score >= 1 and result.ai_score >= 1 and result.total_score >= min_total
