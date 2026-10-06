"""
Shared test fixtures.
All helpers needed by unit tests — no Docker required.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pytest

# Add repo root and services to path
_root = os.path.dirname(os.path.dirname(__file__))
for _p in [_root, os.path.join(_root, "services")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)


# ── Basic model constructors ─────────────────────────────────────────────────

def make_book(**kwargs):
    from output.schemas import BookRecord
    defaults = {
        "id": "b1",
        "frame_ref": "test-sweep/frames/f1.jpg",
        "status": "identified",
        "title": "Test Book",
        "author": "Test Author",
        "isbn": "9780000000000",
        "id_confidence": 0.85,
    }
    defaults.update(kwargs)
    return BookRecord(**defaults)


def make_item(**kwargs):
    from output.schemas import ItemRecord
    defaults = {
        "id": "i1",
        "category": "lamp",
        "frame_ref": "test-sweep/frames/f1.jpg",
        "status": "priced",
    }
    defaults.update(kwargs)
    return ItemRecord(**defaults)


def make_price(amount: float = 15.99):
    from output.schemas import PriceRecord
    return PriceRecord(
        amount=amount,
        source="AbeBooks",
        url="https://www.abebooks.co.uk/test-listing",
        retrieved_at="2024-10-06T10:00:00Z",
    )


def make_used_value(amount: float = 5.50):
    from output.schemas import UsedValueRecord
    return UsedValueRecord(
        amount=amount,
        source="AbeBooks",
        url="https://www.abebooks.co.uk/test-used",
        retrieved_at="2024-10-06T10:00:00Z",
        condition_assumed="Good",
    )


def make_test_packet(
    books=None,
    items=None,
    sweep_id: str = "test-sweep-0000000000000001",
):
    """Creates a minimal valid ClaimPacket for tests."""
    from output.compute_totals import compute_totals
    from output.schemas import ClaimPacket, RoomGeometry, SweepInfo
    books = books or []
    items = items or []
    return ClaimPacket(
        sweep=SweepInfo(
            id=sweep_id,
            captured_at="2024-10-06T10:00:00Z",
            device="pytest",
            duration_s=120,
            country="GB",
            currency="GBP",
        ),
        room=RoomGeometry(
            length_m=4.0,
            width_m=3.5,
            height_m=2.4,
            floor_area_m2=14.0,
            wall_area_m2=38.4,
            scale_method="test",
            confidence=0.8,
        ),
        books=books,
        items=items,
        totals=compute_totals(books, items),
        review_queue=[],
    )


def make_detection(cx: float = 0.5, cy: float = 0.5, conf: float = 0.8):
    from services.vision.detector import SpineDetection
    fw, fh = 1280, 720
    return SpineDetection(
        x1=(cx - 0.03) * fw,
        y1=(cy - 0.15) * fh,
        x2=(cx + 0.03) * fw,
        y2=(cy + 0.15) * fh,
        confidence=conf,
        bbox_width=0.06 * fw,
        bbox_height=0.30 * fh,
    )


# ── Image fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def bookshelf_image() -> np.ndarray:
    """Synthetic bookshelf image — coloured rectangles simulating spines."""
    import cv2
    img = np.zeros((720, 1280, 3), dtype=np.uint8)
    img[:] = (45, 35, 25)
    colors = [(200, 100, 50), (50, 150, 200), (100, 200, 100), (200, 200, 50)]
    for i, color in enumerate(colors * 4):
        x = 80 + i * 70
        if x + 50 > 1280:
            break
        cv2.rectangle(img, (x, 100), (x + 45, 400), color, -1)
        cv2.putText(img, f"Book{i+1}", (x + 2, 260), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
    return img


@pytest.fixture
def spine_crop() -> np.ndarray:
    """Synthetic single spine crop for OCR tests."""
    import cv2
    crop = np.zeros((200, 50, 3), dtype=np.uint8)
    crop[:] = (80, 120, 200)
    cv2.putText(crop, "TITLE", (3, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.putText(crop, "AUTHOR", (3, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1)
    return crop
