"""
Book identification confidence scoring.

Key rule from the brief:
  "Do not guess titles for unreadable spines to raise your identification rate.
   Confident wrong answers are penalised harder than blanks."

The final_status() function implements the gating logic that ensures this rule
is honoured. The thresholds are set conservatively — it is better to mark a
book "unidentified" than to confidently misidentify it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from thefuzz import fuzz


@dataclass
class BookMetadata:
    title: str
    author: Optional[str]
    isbn: Optional[str]
    edition: Optional[str]
    first_publish_year: Optional[int]


def score_matches(
    ocr_text: str,
    candidates: List[BookMetadata],
) -> tuple[Optional[BookMetadata], float]:
    """
    Score OCR text against a list of candidate book metadata.
    Returns (best_match, score) where score is 0.0–1.0.

    Uses token_set_ratio (handles word reordering) which is robust against:
    - Author name appearing where title should be
    - Partial spine text
    - Minor OCR errors
    """
    if not candidates:
        return None, 0.0

    q = ocr_text.lower().strip()
    best: Optional[BookMetadata] = None
    best_score = 0.0

    for candidate in candidates:
        # Title match
        title_score = fuzz.token_set_ratio(q, candidate.title.lower()) / 100.0

        # Author match (weighted less — OCR text may not contain author)
        author_score = 0.0
        if candidate.author:
            author_score = fuzz.token_set_ratio(q, candidate.author.lower()) / 100.0

        # Combined: weight title more heavily
        if author_score > 0.3:
            score = title_score * 0.60 + author_score * 0.40
        else:
            # No reliable author signal — discount slightly
            score = title_score * 0.75

        # Boost if partial ISBN visible in OCR text
        if candidate.isbn and len(candidate.isbn) >= 5:
            if candidate.isbn[:5] in ocr_text or candidate.isbn[-5:] in ocr_text:
                score = min(score + 0.10, 1.0)

        if score > best_score:
            best_score = score
            best = candidate

    return best, best_score


def final_status(match_score: float, ocr_confidence: float) -> str:
    """
    Determines book status from combined match + OCR confidence.

    Thresholds (conservative by design):
      combined ≥ 0.70 → "identified"        (title is set in packet)
      combined 0.45–0.70 → "low_confidence"  (review queue; title NOT set)
      combined < 0.45 → "unidentified"       (blank is correct)

    The 0.70 threshold ensures we don't boost identification rate at the
    expense of accuracy. The brief scores confident wrong answers at 0 for the
    identification metric AND adds a penalty.
    """
    # Round to avoid float precision issues (0.60 * 0.75 = 0.4499... not 0.45)
    combined = round(match_score * ocr_confidence, 6)

    if combined >= 0.70:
        return "identified"
    elif combined >= 0.45:
        return "low_confidence"   # Added to review queue; no title in packet
    else:
        return "unidentified"     # Blank — leave the field null
