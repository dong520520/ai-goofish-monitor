"""Explicit user-supplied supplier and own-business evidence."""
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.models.opportunity import Money, OpportunityItem


def business_today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


class SupplierQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    source: str = Field(min_length=1, max_length=80)
    quote_id: str = Field(min_length=1, max_length=200)
    supplier: str = Field(min_length=1, max_length=200)
    product: str = Field(min_length=1, max_length=500)
    sku: str = Field(min_length=1, max_length=200)
    specification: str = Field(min_length=1, max_length=200)
    model: str | None = Field(None, max_length=200)
    condition: str = Field(min_length=1, max_length=200)
    currency: str = Field("CNY", pattern=r"^[A-Z]{3}$")
    quoted_at: datetime
    purchase_cost: Money | None = None
    shipping_cost: Money | None = None
    lead_days: int | None = Field(None, ge=0, le=3650)
    moq: int | None = Field(None, ge=1, le=1_000_000)
    source_confidence: float = Field(.5, ge=0, le=1, allow_inf_nan=False)
    evidence_note: str = Field(min_length=1, max_length=2000)
    verification_note: str = Field("", max_length=2000)

    _time = field_validator("quoted_at")(OpportunityItem.require_timezone.__func__)


class QuoteConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    confirmed: Literal[True]
    identity_note: str = Field(min_length=5, max_length=1000)


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    start_date: date
    status: Literal["running", "completed", "stopped"] = "running"
    stop_reason: str = Field("", max_length=1000)

    @model_validator(mode="after")
    def validate_window(self):
        if self.start_date > business_today():
            raise ValueError("实验开始日期不能在未来")
        if self.status == "stopped" and not self.stop_reason:
            raise ValueError("停止实验须填写原因")
        if self.status == "completed" and (business_today()-self.start_date).days < 6:
            raise ValueError("七天窗口尚未结束")
        return self


class ExperimentEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    day: date
    exposure: int | None = Field(None, ge=0, le=1_000_000_000)
    inquiries: int | None = Field(None, ge=0, le=1_000_000_000)
    orders: int | None = Field(None, ge=0, le=1_000_000_000)
    refunds: int | None = Field(None, ge=0, le=1_000_000_000)
    revenue: Money | None = None
    refund_amount: Money | None = None
    purchase_cost: Money | None = None
    shipping_cost: Money | None = None
    platform_fee: Money | None = None
    fulfillment_cost: Money | None = None
    actual_loss: Money | None = None
    evidence_note: str = Field(min_length=1, max_length=2000)

    @field_validator("day")
    @classmethod
    def not_future(cls, value):
        if value > business_today():
            raise ValueError("仅记录已发生的经营结果")
        return value
