from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass
class HeuristicResult:
    strong_particle_hits: int
    particle_hits: int
    support_hits: int
    ai_hits: int
    negative_hits: int
    generic_radiotherapy_hits: int
    title_strong_particle_hits: int
    title_ai_hits: int
    total_score: int
    has_strong_particle_anchor: bool
    passes: bool
    reasons: list[str]


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()

def count_hits(text: str, terms: list[str]) -> int:
    blob = normalize(text)
    return sum(1 for term in terms if normalize(term) in blob)


def score_text(
    blob: str,
    taxonomy: dict[str, Any],
    min_total: int = 4,
    title_blob: str = "",
) -> HeuristicResult:
    strong_terms = taxonomy.get("strong_particle_therapy_terms", [])
    particle_terms = taxonomy.get("particle_therapy_terms", [])
    support_terms = taxonomy.get("support_terms", [])
    ai_terms = taxonomy.get("ai_terms", [])
    negative_terms = taxonomy.get("negative_terms", [])
    generic_radiotherapy_terms = taxonomy.get("generic_radiotherapy_terms", [])

    strong_particle_hits = count_hits(blob, strong_terms)
    particle_hits = count_hits(blob, particle_terms)
    support_hits = count_hits(blob, support_terms)
    ai_hits = count_hits(blob, ai_terms)
    negative_hits = count_hits(blob, negative_terms)
    generic_radiotherapy_hits = count_hits(blob, generic_radiotherapy_terms)

    title_strong_particle_hits = count_hits(title_blob, strong_terms) if title_blob else 0
    title_ai_hits = count_hits(title_blob, ai_terms) if title_blob else 0

    has_strong_particle_anchor = (strong_particle_hits > 0) or (title_strong_particle_hits > 0)

    total_score = 0
    total_score += strong_particle_hits * 5
    total_score += particle_hits * 2
    total_score += support_hits * 1
    total_score += ai_hits * 3
    total_score += title_strong_particle_hits * 4
    total_score += title_ai_hits * 2
    total_score -= negative_hits * 4

    #if generic_radiotherapy_hits > 0 and not has_strong_particle_anchor:
    #    total_score -= 5

    reasons: list[str] = []
    if strong_particle_hits:
        reasons.append(f"Matched {strong_particle_hits} strong particle-therapy term(s) in metadata/content.")
    if title_strong_particle_hits:
        reasons.append(f"Matched {title_strong_particle_hits} strong particle-therapy term(s) in repository name.")
    if particle_hits:
        reasons.append(f"Matched {particle_hits} particle-therapy term(s).")
    if support_hits:
        reasons.append(f"Matched {support_hits} support term(s).")
    if ai_hits:
        reasons.append(f"Matched {ai_hits} AI/ML term(s) in metadata/content.")
    if title_ai_hits:
        reasons.append(f"Matched {title_ai_hits} AI/ML term(s) in repository name.")
    if negative_hits:
        reasons.append(f"Matched {negative_hits} negative term(s).")
    if generic_radiotherapy_hits and not has_strong_particle_anchor:
        reasons.append("Generic radiotherapy terms found without a strong particle-therapy anchor.")

    passes = (
        has_strong_particle_anchor
        #and ((ai_hits + title_ai_hits) >= 1)
        and total_score >= min_total
    )

    return HeuristicResult(
        strong_particle_hits=strong_particle_hits,
        particle_hits=particle_hits,
        support_hits=support_hits,
        ai_hits=ai_hits,
        negative_hits=negative_hits,
        generic_radiotherapy_hits=generic_radiotherapy_hits,
        title_strong_particle_hits=title_strong_particle_hits,
        title_ai_hits=title_ai_hits,
        total_score=total_score,
        has_strong_particle_anchor=has_strong_particle_anchor,
        passes=passes,
        reasons=reasons,
    )


def passes_prefilter(result: HeuristicResult) -> bool:
    return result.passes
