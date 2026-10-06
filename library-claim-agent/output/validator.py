"""
Claim packet validator.

Enforces the three cardinal rules from the brief:
  1. Empty field = system doesn't know. Filled field without evidence = defect.
  2. Every frame_ref must point to a saved frame we can open.
  3. Totals are computed in code — never by a language model.

The validator runs before writing the packet JSON to disk.
A packet with errors is NOT written (logged and review queue updated).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Protocol

from output.compute_totals import compute_totals
from output.schemas import ClaimPacket

logger = logging.getLogger(__name__)

TOTALS_TOLERANCE = 0.02  # £0.02 rounding tolerance


class FrameStoreProtocol(Protocol):
    def exists(self, key: str) -> bool: ...


@dataclass
class ValidationReport:
    valid: bool
    errors: List[str]
    warnings: List[str]


class PacketValidator:
    def validate(
        self,
        packet: ClaimPacket,
        frame_store: FrameStoreProtocol,
    ) -> ValidationReport:
        errors: List[str] = []
        warnings: List[str] = []

        # ── Rule 2: Every frame_ref must exist ──────────────────────
        all_refs = {b.frame_ref for b in packet.books} | {i.frame_ref for i in packet.items}
        for ref in all_refs:
            if not frame_store.exists(ref):
                errors.append(f"frame_ref not found in storage: {ref!r}")

        # ── Rule 1: Every price must have a URL ──────────────────────
        for book in packet.books:
            if book.replacement_cost:
                if not book.replacement_cost.url.startswith("http"):
                    errors.append(
                        f"Book {book.id}: replacement_cost.url is invalid "
                        f"({book.replacement_cost.url!r})"
                    )
                if not book.replacement_cost.retrieved_at:
                    errors.append(f"Book {book.id}: replacement_cost.retrieved_at is missing")
                if not book.replacement_cost.source:
                    errors.append(f"Book {book.id}: replacement_cost.source is missing")

        # ── Rule 3: Totals must match computation ────────────────────
        computed = compute_totals(packet.books, packet.items)

        if abs(computed.books_replacement_cost - packet.totals.books_replacement_cost) > TOTALS_TOLERANCE:
            errors.append(
                f"books_replacement_cost mismatch: "
                f"computed={computed.books_replacement_cost}, "
                f"stored={packet.totals.books_replacement_cost}"
            )

        if computed.book_count != packet.totals.book_count:
            errors.append(
                f"book_count mismatch: computed={computed.book_count}, "
                f"stored={packet.totals.book_count}"
            )

        # ── Unidentified books must NOT have titles ──────────────────
        for book in packet.books:
            if book.status in ("unidentified", "ocr_only") and book.title is not None:
                errors.append(
                    f"Book {book.id}: status={book.status!r} but has title "
                    f"'{book.title}' — blank is correct"
                )

        # ── Warnings (logged but do not block packet writing) ────────
        low_conf = [b for b in packet.books if b.id_confidence and b.id_confidence < 0.70]
        if low_conf:
            warnings.append(
                f"{len(low_conf)} books with identification confidence < 70%"
            )

        no_room = packet.room.floor_area_m2 is None
        if no_room:
            warnings.append("Room geometry missing — floor area could not be estimated")

        return ValidationReport(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
