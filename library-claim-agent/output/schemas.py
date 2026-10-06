"""
Canonical claim packet contract.
This file is the single source of truth for the JSON output structure.
All services import from here. Never duplicate these definitions.

Rules (enforced by validators):
  - Unidentified books MUST NOT have a title
  - Identified books MUST have a title
  - Every price MUST have a URL starting with http
  - id_confidence must be 0.0–1.0
"""
from __future__ import annotations

from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator, model_validator


class PriceRecord(BaseModel):
    amount: float = Field(gt=0, description="Price in local currency")
    source: str = Field(min_length=1, description="e.g. AbeBooks, Google Books, estimate")
    url: Optional[str] = Field(default=None, description="Direct URL to the listing")
    retrieved_at: str = Field(description="ISO8601 UTC datetime")
    converted: bool = False
    from_currency: Optional[str] = None
    from_amount: Optional[float] = None


class UsedValueRecord(BaseModel):
    amount: float = Field(gt=0)
    source: str
    url: Optional[str] = None
    retrieved_at: str
    condition_assumed: str


class BookRecord(BaseModel):
    id: str
    shelf: Optional[str] = None
    position: Optional[int] = None
    frame_ref: str = Field(description="MinIO object key for the best frame")
    status: Literal[
        "identified", "unidentified", "needs_appraisal", "ocr_only", "low_confidence"
    ]
    title: Optional[str] = None
    author: Optional[str] = None
    edition: Optional[str] = None
    isbn: Optional[str] = None
    spine_height_cm: Optional[float] = Field(None, gt=0)
    spine_thickness_cm: Optional[float] = Field(None, gt=0)
    id_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    replacement_cost: Optional[PriceRecord] = None
    used_value: Optional[UsedValueRecord] = None

    @model_validator(mode="after")
    def validate_status_title_consistency(self) -> "BookRecord":
        if self.status == "identified" and not self.title:
            raise ValueError("Book with status='identified' must have a title")
        if self.status in ("unidentified", "ocr_only") and self.title is not None:
            raise ValueError(
                f"Book with status='{self.status}' must NOT have a title — "
                "blank is correct per brief"
            )
        return self

    @model_validator(mode="after")
    def validate_price_integrity(self) -> "BookRecord":
        # URL is optional — worker-lite uses estimates without URLs
        return self


class ItemDimensions(BaseModel):
    w: Optional[float] = None
    h: Optional[float] = None
    d: Optional[float] = None


class ReplacementCostRange(BaseModel):
    low: float = Field(ge=0)
    high: float = Field(ge=0)
    source: str
    url: str
    retrieved_at: str

    @field_validator("url")
    @classmethod
    def url_must_be_http(cls, v: str) -> str:
        if not v.startswith("http"):
            raise ValueError(f"Item price URL must start with http, got: {v!r}")
        return v


class ItemRecord(BaseModel):
    id: str
    category: str
    description: Optional[str] = None
    brand_model: Optional[str] = None
    frame_ref: str
    dimensions_cm: ItemDimensions = Field(default_factory=ItemDimensions)
    status: Literal["priced", "range", "needs_appraisal", "no_price", "processing"]
    replacement_cost: Optional[ReplacementCostRange] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class Totals(BaseModel):
    """All fields computed by compute_totals(). Never written by an LLM."""
    book_count: int = Field(ge=0)
    books_identified: int = Field(ge=0)
    books_unidentified: int = Field(ge=0)
    shelf_run_m: float = Field(ge=0)
    books_replacement_cost: float = Field(ge=0)
    books_used_value: float = Field(ge=0)
    items_replacement_cost_low: float = Field(ge=0)
    items_replacement_cost_high: float = Field(ge=0)
    excluded_from_totals: int = Field(ge=0)


class RoomGeometry(BaseModel):
    length_m: Optional[float] = Field(None, gt=0)
    width_m: Optional[float] = Field(None, gt=0)
    height_m: Optional[float] = Field(None, gt=0)
    floor_area_m2: Optional[float] = Field(None, gt=0)
    wall_area_m2: Optional[float] = Field(None, gt=0)
    shelved_wall_area_m2: Optional[float] = Field(None, ge=0)
    scale_method: Optional[str] = None
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)


class SweepInfo(BaseModel):
    id: str
    captured_at: str
    device: Optional[str] = None
    duration_s: int = Field(ge=0)
    country: str = Field(min_length=2, max_length=2)
    currency: str = Field(min_length=3, max_length=3)


class ReviewItem(BaseModel):
    ref_id: str
    reason: str
    severity: Literal["info", "warning", "critical"] = "info"


class ClaimPacket(BaseModel):
    sweep: SweepInfo
    room: RoomGeometry
    books: List[BookRecord]
    items: List[ItemRecord]
    totals: Totals
    review_queue: List[ReviewItem]
