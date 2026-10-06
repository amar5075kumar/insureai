"""
Deterministic claim packet totals computation.

THIS IS THE ONLY CODE THAT WRITES TOTALS FIELDS.
No LLM, no approximation. Pure arithmetic over the lines.

Any code outside this module that attempts to write to:
  totals.book_count, totals.books_replacement_cost, etc.
is a defect and must be removed.
"""
from __future__ import annotations

from typing import List

from output.schemas import BookRecord, ItemRecord, Totals


def compute_totals(books: List[BookRecord], items: List[ItemRecord]) -> Totals:
    """
    Compute all totals from the line items. Deterministic and pure.

    Rules:
    - Only 'identified' books with a non-None replacement_cost contribute to
      books_replacement_cost.
    - All books (identified + unidentified) contribute to book_count.
    - Shelf run = sum of all spine_thickness_cm / 100, regardless of status.
    - excluded_from_totals = identified books without price + unpriced items
      (not unidentified books — they're simply unidentified, not excluded).
    """
    book_count = len(books)
    books_identified = sum(1 for b in books if b.status == "identified")
    books_unidentified = sum(1 for b in books if b.status == "unidentified")

    # Shelf run: all books with a known thickness
    shelf_run_m = sum(
        (b.spine_thickness_cm or 0.0) / 100.0
        for b in books
    )

    # Priced books: identified AND have a replacement_cost
    priced_books = [
        b for b in books
        if b.status == "identified" and b.replacement_cost is not None
    ]
    unpriced_identified = [
        b for b in books
        if b.status == "identified" and b.replacement_cost is None
    ]

    books_replacement_cost = sum(b.replacement_cost.amount for b in priced_books)
    books_used_value = sum(
        b.used_value.amount
        for b in priced_books
        if b.used_value is not None
    )

    # Items
    priced_items = [i for i in items if i.replacement_cost is not None]
    unpriced_items = [
        i for i in items
        if i.replacement_cost is None and i.status not in ("processing", "needs_appraisal")
    ]

    items_replacement_cost_low = sum(i.replacement_cost.low for i in priced_items)
    items_replacement_cost_high = sum(i.replacement_cost.high for i in priced_items)

    excluded_from_totals = len(unpriced_identified) + len(unpriced_items)

    return Totals(
        book_count=book_count,
        books_identified=books_identified,
        books_unidentified=books_unidentified,
        shelf_run_m=round(shelf_run_m, 3),
        books_replacement_cost=round(books_replacement_cost, 2),
        books_used_value=round(books_used_value, 2),
        items_replacement_cost_low=round(items_replacement_cost_low, 2),
        items_replacement_cost_high=round(items_replacement_cost_high, 2),
        excluded_from_totals=excluded_from_totals,
    )
