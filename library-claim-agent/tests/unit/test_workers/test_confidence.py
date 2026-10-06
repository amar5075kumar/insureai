"""
Unit tests for book identification confidence scoring.

The brief says: "Confident wrong answers are penalised harder than blanks."
These tests verify that our gating is correctly conservative.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

import pytest

from workers.book_id.confidence import BookMetadata, final_status, score_matches


def make_metadata(title: str, author: str = None, isbn: str = None) -> BookMetadata:
    return BookMetadata(title=title, author=author, isbn=isbn, edition=None, first_publish_year=None)


# ── final_status gating ──────────────────────────────────────────────────────

def test_high_confidence_is_identified():
    assert final_status(0.90, 0.90) == "identified"


def test_medium_confidence_is_low_confidence():
    status = final_status(0.60, 0.75)
    assert status == "low_confidence"
    # low_confidence → review queue; title NOT set in packet


def test_low_confidence_is_unidentified():
    assert final_status(0.35, 0.60) == "unidentified"
    # blank is CORRECT — do not guess


def test_boundary_at_70_percent():
    # Combined = 0.70 exactly → identified
    assert final_status(0.875, 0.80) == "identified"  # 0.875 * 0.80 = 0.70


def test_just_below_70_is_low_confidence():
    # Combined = 0.699 → low_confidence (not identified)
    assert final_status(0.87, 0.80) == "low_confidence"  # 0.87 * 0.80 = 0.696


# ── score_matches ────────────────────────────────────────────────────────────

def test_exact_title_match_scores_high():
    candidates = [make_metadata("Thinking Fast and Slow", "Daniel Kahneman", "9780374275631")]
    # When no author is in the OCR text, score is capped at 0.75 (title × 0.75 discount)
    # When author is also present, score > 0.85
    _, score_title_only = score_matches("Thinking Fast and Slow", candidates)
    assert score_title_only > 0.70  # Passes confidence threshold without author

    _, score_with_author = score_matches("Thinking Fast and Slow Kahneman", candidates)
    assert score_with_author > 0.85  # Full match with author signal


def test_author_prominent_spine_still_matches():
    """
    Common case: author name appears large on spine, title is small.
    OCR may read 'KAHNEMAN' more clearly than the title.
    Should still find the book.
    """
    candidates = [make_metadata("Thinking Fast and Slow", "Daniel Kahneman")]
    _, score_author = score_matches("KAHNEMAN THINKING FAST", candidates)
    _, score_title = score_matches("Thinking Fast Slow Kahneman", candidates)
    # Both should score reasonably (>0.5 combined with decent OCR conf)
    assert score_author > 0.4
    assert score_title > 0.6


def test_completely_wrong_candidate_scores_low():
    """Should never produce 'identified' for a completely wrong match."""
    candidates = [make_metadata("Moby Dick", "Herman Melville")]
    _, score = score_matches("Harry Potter Philosopher Stone Rowling", candidates)
    status = final_status(score, 0.85)
    assert status in ("unidentified", "low_confidence")


def test_empty_candidates_returns_none():
    best, score = score_matches("some text", [])
    assert best is None
    assert score == 0.0


def test_isbn_boost():
    candidates = [make_metadata("Outliers", "Malcolm Gladwell", "9780316017923")]
    # OCR includes partial ISBN
    _, score_with_isbn = score_matches("Outliers 9780316", candidates)
    _, score_without_isbn = score_matches("Outliers", candidates)
    assert score_with_isbn >= score_without_isbn


def test_partial_title_scores_reasonably():
    candidates = [make_metadata("The Name of the Rose", "Umberto Eco")]
    _, score = score_matches("Name of the Rose", candidates)
    assert score > 0.70
