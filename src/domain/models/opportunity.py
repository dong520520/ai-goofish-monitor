"""Offline opportunity contracts. Unknown measurements and costs remain null."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

Strategy = Literal["physical", "virtual", "resale", "blue_ocean"]
Money = Annotated[Decimal, Field(ge=0, le=1_000_000_000, max_digits=12, decimal_places=2)]


class CostAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    expected_sale_price: Money | None = None
    purchase_cost: Money | None = None
    shipping_cost: Money | None = None
    platform_fee: Money | None = None
    fulfillment_cost: Money | None = None
    expected_loss: Money | None = None
    resale_reference: Money | None = None
    evidence_note: str = Field("", max_length=2000)
    supplier_evidence: str = Field("", max_length=1000)
    resale_evidence: str = Field("", max_length=1000)
    rights_evidence: str = Field("", max_length=1000)
    platform_evidence: str = Field("", max_length=1000)
    delivery_evidence: str = Field("", max_length=1000)
    authenticity_evidence: str = Field("", max_length=1000)
    differentiation_evidence: str = Field("", max_length=1000)


class OpportunityItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=80)
    source_item_id: str = Field(min_length=1, max_length=200)
    url: HttpUrl | None = None
    title: str = Field(min_length=1, max_length=500)
    price: Money | None = None
    currency: str = Field("CNY", pattern=r"^[A-Z]{3}$")
    category: str = Field("未分类", min_length=1, max_length=100)
    seller_id: str | None = Field(None, max_length=200)
    observed_at: datetime
    listing_created_at: datetime | None = None
    want_count: int | None = Field(None, ge=0, le=1_000_000_000)
    view_count: int | None = Field(None, ge=0, le=1_000_000_000)
    condition: str | None = Field(None, max_length=200)
    source_confidence: float = Field(0.5, ge=0, le=1, allow_inf_nan=False)
    raw_metadata: dict = Field(default_factory=dict)

    @field_validator("observed_at", "listing_created_at")
    @classmethod
    def require_timezone(cls, value):
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("时间必须包含时区；首次观察不等于发布时间")
        if value > datetime.now(timezone.utc):
            raise ValueError("观测/发布时间不能在未来")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def chronological(self):
        if self.listing_created_at and self.listing_created_at > self.observed_at:
            raise ValueError("发布时间不能晚于观察时间")
        return self


DIMENSIONS = ("demand", "profit", "competition", "fulfillment", "risk", "differentiation")
DEFAULT_WEIGHTS = {
    "physical": [25, 25, 20, 15, 10, 5],
    "virtual": [25, 20, 15, 15, 20, 5],
    "resale": [20, 30, 15, 15, 15, 5],
    "blue_ocean": [30, 15, 25, 10, 10, 10],
}


class ScoreRequest(BaseModel):
    strategy: Strategy = "physical"
    weights: dict[str, float] | None = None

    @field_validator("weights")
    @classmethod
    def validate_weights(cls, value):
        import math
        if value is not None and (
            set(value) != set(DIMENSIONS)
            or any(not math.isfinite(v) or v < 0 for v in value.values())
            or abs(sum(value.values()) - 100) > 0.001
        ):
            raise ValueError("六个维度权重必须非负、有限且总和为 100")
        return value


class CategoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    parent: str | None = Field(None, max_length=100)
    keywords: list[Annotated[str, Field(min_length=1, max_length=80)]] = Field(default_factory=list, max_length=30)


class DiscoveryRequest(BaseModel):
    budget: int = Field(10, ge=1, le=50)
    breadth_ratio: float = Field(0.4, ge=0, le=1, allow_inf_nan=False)
