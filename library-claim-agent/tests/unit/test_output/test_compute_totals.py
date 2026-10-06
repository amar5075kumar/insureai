"""
Unit tests for compute_totals().

These tests enforce the core invariant:
  compute_totals() is the ONLY source of totals fields.
  No LLM, no approximation.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

import pytest

from output.compute_totals import compute_totals
from output.schemas import BookRecord, ItemRecord, PriceRecord, ReplacementCostRange, UsedValueRecord


def make_book(**kwargs) -> BookRecord:
    defaults = {
        "id": "b1",
        "frame_ref": "sweep/frames/f1.jpg",
        "status": "identified",
        "title": "Test Book",       # identified books require a title
        "author": "Test Author",
    }
    defaults.update(kwargs)
    return BookRecord(**defaults)


def make_item(**kwargs) -> ItemRecord:
    defaults = {
        "id": "i1",
        "category": "lamp",
        "frame_ref": "sweep/frames/f1.jpg",
        "status": "priced",
    }
    defaults.update(kwargs)
    return ItemRecord(**defaults)


def make_price(amount: float = 15.99) -> PriceRecord:
    return PriceRecord(
        amount=amount,
        source="AbeBooks",
        url="https://abebooks.co.uk/test",
        retrieved_at="2024-10-06T10:00:00Z",
    )


def make_used(amount: float = 5.00) -> UsedValueRecord:
    return UsedValueRecord(
        amount=amount,
        source="AbeBooks",
        url="https://abebooks.co.uk/test-used",
        retrieved_at="2024-10-06T10:00:00Z",
        condition_assumed="Good",
    )


# ── Basic arithmetic ─────────────────────────────────────────────────────────

def test_empty_returns_zeros():
    t = compute_totals([], [])
    assert t.book_count == 0
    assert t.books_identified == 0
    assert t.books_unidentified == 0
    assert t.shelf_run_m == 0.0
    assert t.books_replacement_cost == 0.0
    assert t.excluded_from_totals == 0


def test_single_identified_book_with_price():
    book = make_book(
        replacement_cost=make_price(14.99),
        used_value=make_used(4.50),
        spine_thickness_cm=2.0,
    )
    t = compute_totals([book], [])
    assert t.book_count == 1
    assert t.books_identified == 1
    assert t.books_replacement_cost == 14.99
    assert t.books_used_value == 4.50
    assert abs(t.shelf_run_m - 0.020) < 0.001


def test_totals_are_deterministic():
    """Same input → exact same output every time."""
    books = [
        make_book(id=f"b{i}", replacement_cost=make_price(10.0 + i))
        for i in range(5)
    ]
    t1 = compute_totals(books, [])
    t2 = compute_totals(books, [])
    assert t1 == t2


def test_unidentified_books_excluded_from_cost():
    books = [
        make_book(id="b1", status="identified", replacement_cost=make_price(20.0)),
        make_book(id="b2", status="unidentified", title=None),
    ]
    t = compute_totals(books, [])
    assert t.book_count == 2
    assert t.books_identified == 1
    assert t.books_unidentified == 1
    assert t.books_replacement_cost == 20.0  # Only identified book counted


def test_needs_appraisal_excluded_from_cost():
    book = make_book(status="needs_appraisal", replacement_cost=None)
    t = compute_totals([book], [])
    assert t.books_replacement_cost == 0.0


def test_identified_without_price_is_excluded_from_totals():
    book = make_book(status="identified", replacement_cost=None)  # No price
    t = compute_totals([book], [])
    assert t.books_replacement_cost == 0.0
    assert t.excluded_from_totals == 1


def test_shelf_run_sums_all_books():
    books = [
        make_book(id="b1", spine_thickness_cm=3.0),
        make_book(id="b2", status="unidentified", title=None, spine_thickness_cm=2.0),
    ]
    t = compute_totals(books, [])
    assert abs(t.shelf_run_m - 0.05) < 0.001


def test_item_cost_range():
    item = make_item(
        replacement_cost=ReplacementCostRange(
            low=120.0,
            high=180.0,
            source="Google Shopping",
            url="https://shopping.google.com/test",
            retrieved_at="2024-10-06T10:00:00Z",
        )
    )
    t = compute_totals([], [item])
    assert t.items_replacement_cost_low == 120.0
    assert t.items_replacement_cost_high == 180.0


# ── Schema integrity ─────────────────────────────────────────────────────────

def test_cannot_create_unidentified_with_title():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="must NOT have a title"):
        make_book(status="unidentified", title="Some Book")


def test_cannot_create_identified_without_title():
    from pydantic import ValidationError
    with pytest.raises(ValidationError, match="must have a title"):
        make_book(status="identified", title=None)


def test_price_url_must_be_http():
    from pydantic import ValidationError
    # Use a clearly non-HTTP URL (long enough to pass min_length but fails our validator)
    with pytest.raises(ValidationError, match="must start with http"):
        PriceRecord(
            amount=10.0,
            source="AbeBooks",
            url="ftp://example.com/book/listing",  # Not http — should fail our validator
            retrieved_at="2024-10-06T10:00:00Z",
        )
