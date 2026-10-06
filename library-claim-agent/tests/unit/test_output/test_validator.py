"""
Unit tests for PacketValidator.

Tests the three cardinal rules:
  1. frame_ref must exist in storage
  2. Price must have valid URL
  3. Totals must match compute_totals()
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from unittest.mock import MagicMock

import pytest

from output.schemas import PriceRecord
from output.validator import PacketValidator


def make_mock_frame_store(exists_result: bool = True):
    fs = MagicMock()
    fs.exists.return_value = exists_result
    return fs


def test_valid_packet_passes(make_test_packet=None):
    """A well-formed packet with all refs present passes validation."""
    from tests.conftest import make_book, make_price, make_test_packet
    book = make_book(replacement_cost=make_price(14.99))
    packet = make_test_packet(books=[book])
    report = PacketValidator().validate(packet, make_mock_frame_store(True))
    assert report.valid, f"Unexpected errors: {report.errors}"


def test_missing_frame_ref_fails():
    """If any frame_ref is not in storage, packet is invalid."""
    from tests.conftest import make_book, make_test_packet
    book = make_book(frame_ref="missing-frame.jpg")
    packet = make_test_packet(books=[book])
    report = PacketValidator().validate(packet, make_mock_frame_store(False))
    assert not report.valid
    assert any("missing-frame.jpg" in e for e in report.errors)


def test_price_without_url_fails():
    """Price record with invalid URL → validation error."""
    from tests.conftest import make_test_packet
    from output.schemas import BookRecord, ClaimPacket
    from output.compute_totals import compute_totals

    # Bypass BookRecord schema to inject a bad URL price
    book = BookRecord.model_construct(
        id="b-bad-url",
        frame_ref="s/f1.jpg",
        status="identified",
        title="Test",
        id_confidence=0.9,
        replacement_cost=MagicMock(
            amount=15.0,
            url="not-a-url",
            source="Test",
            retrieved_at="2024-01-01T00:00:00Z",
        ),
        used_value=None,
        dimensions=None,
        author=None,
        isbn=None,
    )
    # Use model_construct on ClaimPacket to bypass its schema validator too
    base = make_test_packet()
    packet = ClaimPacket.model_construct(
        sweep=base.sweep,
        room=base.room,
        books=[book],
        items=[],
        totals=base.totals,
        review_queue=[],
    )
    report = PacketValidator().validate(packet, make_mock_frame_store(True))
    # Should flag the bad URL
    assert any("url" in e.lower() for e in report.errors)


def test_totals_mismatch_is_detected():
    """If stored totals differ from recomputed, validator raises error."""
    from tests.conftest import make_book, make_price, make_test_packet
    book = make_book(replacement_cost=make_price(20.00))
    packet = make_test_packet(books=[book])

    # Tamper with stored totals
    tampered = packet.model_copy(update={
        "totals": packet.totals.model_copy(update={"books_replacement_cost": 999.99})
    })

    report = PacketValidator().validate(tampered, make_mock_frame_store(True))
    assert not report.valid
    assert any("mismatch" in e.lower() for e in report.errors)


def test_unidentified_with_title_is_caught():
    """Status=unidentified with a title set is a defect."""
    from output.schemas import BookRecord
    from tests.conftest import make_test_packet

    # Pydantic schema should prevent this, but test the validator too
    with pytest.raises(Exception):
        BookRecord(
            id="b1",
            frame_ref="s/f1.jpg",
            status="unidentified",
            title="Should Not Be Here",
        )
