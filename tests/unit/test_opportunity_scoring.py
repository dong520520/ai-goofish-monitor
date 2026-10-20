from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.domain.models.opportunity import CostAssumptions, OpportunityItem, ScoreRequest
from src.domain.opportunity_scoring import profit_analysis, score_opportunity


def item(**changes):
    return OpportunityItem.model_validate(dict(source="fixture", source_item_id="1", title="机械键盘", price="80",
        category="电脑外设", observed_at="2026-01-01T08:00:00+08:00", source_confidence=.8) | changes)


def complete_costs(**changes):
    values = dict(expected_sale_price="150.10", purchase_cost="70.05", shipping_cost="8", platform_fee="2",
        fulfillment_cost="5", expected_loss="3", supplier_evidence="fixture quote", delivery_evidence="fixture delivery",
        evidence_note="fixture assumptions", differentiation_evidence="fixture differentiation")
    return CostAssumptions(**(values | changes))


MARKET = {"sample_count": 8, "price_low": 80, "price_high": 120}
NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


def test_profit_uses_exact_decimal_and_all_six_terms():
    result = profit_analysis(complete_costs())
    assert result["net_profit"] == 62.05
    assert result["net_margin"] == 41.34


@pytest.mark.parametrize("field", ["expected_sale_price", "purchase_cost", "shipping_cost", "platform_fee", "fulfillment_cost", "expected_loss"])
def test_unknown_cost_never_becomes_zero(field):
    result = profit_analysis(complete_costs(**{field: None}))
    assert result["net_profit"] is None and result["net_margin"] is None
    assert result["missing"] == [field]


def test_zero_is_valid_but_zero_sale_has_no_margin():
    c = CostAssumptions(**dict.fromkeys(["expected_sale_price", "purchase_cost", "shipping_cost", "platform_fee", "fulfillment_cost", "expected_loss"], 0))
    assert profit_analysis(c)["net_profit"] == 0
    assert profit_analysis(c)["net_margin"] is None


@pytest.mark.parametrize("mode", ["physical", "virtual", "resale", "blue_ocean"])
def test_score_deterministic_explainable_and_weighted(mode):
    a = score_opportunity(item(want_count=30), complete_costs(), mode, MARKET, now=NOW)
    b = score_opportunity(item(want_count=30), complete_costs(), mode, MARKET, now=NOW)
    assert a == b
    assert a["score_total"] == round(sum(d["score"]*d["weight"]/100 for d in a["dimensions"].values()), 2)
    assert sum(d["weight"] for d in a["dimensions"].values()) == 100
    assert all(0 <= d["score"] <= 100 and d["evidence"] for d in a["dimensions"].values())


def test_confidence_is_independent_from_score_and_decays_with_age():
    good = item(want_count=30)
    low = good.model_copy(update={"source_confidence": .1})
    a = score_opportunity(good, complete_costs(), "physical", MARKET, now=NOW)
    b = score_opportunity(low, complete_costs(), "physical", MARKET, now=NOW)
    old = score_opportunity(good, complete_costs(), "physical", MARKET, now=datetime(2026, 3, 1, tzinfo=timezone.utc))
    assert a["score_total"] == b["score_total"]
    assert a["confidence_score"] > b["confidence_score"]
    assert old["confidence_score"] < a["confidence_score"]


def test_missing_demand_and_small_sample_do_not_score_high():
    result = score_opportunity(item(), CostAssumptions(), "blue_ocean", {"sample_count": 1}, now=NOW)
    assert result["dimensions"]["demand"]["score"] == 0
    assert result["dimensions"]["competition"]["score"] == 0
    assert result["score_total"] < 20 and result["confidence_score"] < 50
    assert result["recommendation"] == "blocked"


def test_virtual_rights_resale_authenticity_and_hard_veto():
    virtual = score_opportunity(item(), complete_costs(), "virtual", MARKET, now=NOW)
    resale = score_opportunity(item(), complete_costs(), "resale", MARKET, now=NOW)
    assert "rights_evidence" in virtual["missing"]
    assert "authenticity_evidence" in resale["missing"]
    bad = item().model_copy(update={"title": "破解软件 共享账号"})
    result = score_opportunity(bad, complete_costs(), "virtual", MARKET, now=NOW)
    assert result["dimensions"]["risk"]["score"] == 0 and result["recommendation"] == "blocked"


def test_loss_and_synthetic_never_priority_recommendations():
    bad = score_opportunity(item(), complete_costs(purchase_cost=200), "physical", MARKET, now=NOW)
    demo = score_opportunity(item().model_copy(update={"source": "synthetic_demo"}), complete_costs(), "physical", MARKET, now=NOW)
    assert bad["profit"]["net_profit"] < 0 and bad["recommendation"] == "blocked"
    assert demo["confidence_score"] <= 20 and demo["is_demo"]
    assert demo["recommendation"] != "priority_validation"


@pytest.mark.parametrize("change", [{"price": "NaN"}, {"price": "-1"}, {"observed_at": "2026-01-01T00:00:00"}, {"url": "javascript:alert(1)"}, {"observed_at": "2099-01-01T00:00:00Z"}, {"listing_created_at": "2026-01-02T00:00:00Z"}])
def test_invalid_values_rejected(change):
    values = item().model_dump() | change
    with pytest.raises(ValidationError):
        OpportunityItem.model_validate(values)


def test_weights_reject_nan_wrong_sum_and_unknown_fields():
    for weights in ({"demand": 100}, dict.fromkeys(["demand", "profit", "competition", "fulfillment", "risk", "differentiation"], 100), {"demand": float("nan")}):
        with pytest.raises(ValidationError):
            ScoreRequest(weights=weights)
