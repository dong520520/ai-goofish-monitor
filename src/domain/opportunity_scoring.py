"""Deterministic heuristics; interest and sample density are never sales evidence."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from math import log1p

from src.domain.models.opportunity import CostAssumptions, DEFAULT_WEIGHTS, DIMENSIONS, OpportunityItem

COST_FIELDS = ("expected_sale_price", "purchase_cost", "shipping_cost", "platform_fee", "fulfillment_cost", "expected_loss")
BLOCK_WORDS = ("破解", "盗版", "盗录", "共享账号", "账号共享", "假证", "仿牌", "高仿", "枪支", "毒品")


def profit_analysis(costs: CostAssumptions) -> dict:
    missing = [key for key in COST_FIELDS if getattr(costs, key) is None]
    if missing:
        return {"net_profit": None, "net_margin": None, "missing": missing, "basis": "待补充成本；未估算未知费用"}
    sale = costs.expected_sale_price
    net = sale - sum((getattr(costs, key) for key in COST_FIELDS[1:]), Decimal(0))
    return {
        "net_profit": float(net),
        "net_margin": float((net / sale * 100).quantize(Decimal("0.01"))) if sale else None,
        "missing": [], "basis": "用户假设，非成交收益保证",
    }


def score_opportunity(item: OpportunityItem, costs: CostAssumptions, strategy: str,
                      market: dict, weights: dict | None = None, *, now=None) -> dict:
    weights = weights or dict(zip(DIMENSIONS, DEFAULT_WEIGHTS[strategy]))
    now = now or datetime.now(timezone.utc)
    missing, warnings, blockers = [], [], []
    profit = profit_analysis(costs)
    missing.extend(profit["missing"])
    interest = item.want_count
    demand = min(85, log1p(interest) / log1p(100) * 85) if interest is not None else 0
    if interest is None:
        missing.append("want_count")
    if item.view_count is None:
        missing.append("view_count")
    if item.listing_created_at is None:
        missing.append("listing_created_at")
    if not item.seller_id:
        missing.append("seller_id")
    if item.price is None or item.price <= 0:
        blockers.append("报价缺失或异常，需人工核验")
    matched = [word for word in BLOCK_WORDS if word in item.title]
    if matched:
        blockers.append("疑似不可售/侵权词：" + "、".join(matched))
    if not costs.supplier_evidence:
        blockers.append("货源/取得方式尚未核验")
        missing.append("supplier_evidence")
    if strategy == "virtual":
        for field, label in (("rights_evidence", "权利授权"), ("platform_evidence", "平台可售性"), ("delivery_evidence", "数字交付")):
            if not getattr(costs, field):
                blockers.append(label + "待人工核验")
                missing.append(field)
    if strategy == "resale":
        if costs.resale_reference is None or not costs.resale_evidence:
            blockers.append("缺少可追溯转售参考价")
            missing.append("resale_reference/evidence")
        elif costs.expected_sale_price is not None and costs.expected_sale_price > costs.resale_reference:
            warnings.append("预计售价高于用户提供的转售参考价")
        if not costs.authenticity_evidence:
            blockers.append("真实性/成色待核验")
            missing.append("authenticity_evidence")
    if not costs.delivery_evidence:
        missing.append("delivery_evidence")
    if not costs.evidence_note:
        missing.append("evidence_note")
    if not costs.differentiation_evidence:
        missing.append("differentiation_evidence")
    # Observed listing sample only; small samples cannot establish low competition.
    sample = market["sample_count"]
    competition = max(10, 80 - sample * 2) if sample >= 5 and item.category != "未分类" else 0
    if sample < 5:
        missing.append("competition_sample>=5")
    margin = profit["net_margin"]
    profit_score = min(100, max(0, margin * 2)) if margin is not None else 0
    if profit["net_profit"] is not None and profit["net_profit"] <= 0:
        blockers.append("按当前假设净利润不为正")
    if profit["missing"]:
        blockers.append("利润成本尚未补齐")
    risk_score = 0 if matched else max(0, 85 - 20 * len(blockers))
    dimensions = dict(zip(DIMENSIONS, [demand, profit_score, competition,
        80 if costs.delivery_evidence and costs.supplier_evidence else 0,
        risk_score, 70 if costs.differentiation_evidence else 0]))
    total = round(sum(dimensions[k] * weights[k] / 100 for k in DIMENSIONS), 2)
    coverage_fields = [item.price is not None, item.want_count is not None, item.view_count is not None,
        item.seller_id is not None, item.listing_created_at is not None,
        not profit["missing"], bool(costs.evidence_note), bool(costs.supplier_evidence),
        bool(costs.delivery_evidence), sample >= 5]
    if strategy == "virtual":
        coverage_fields.extend([bool(costs.rights_evidence), bool(costs.platform_evidence)])
    if strategy == "resale":
        coverage_fields.extend([costs.resale_reference is not None and bool(costs.resale_evidence), bool(costs.authenticity_evidence)])
    age = max(0, (now - item.observed_at).total_seconds() / 86400)
    freshness = 1 if age <= 7 else 0.7 if age <= 30 else 0.4
    confidence = round(100 * item.source_confidence * sum(coverage_fields) / len(coverage_fields) * freshness, 2)
    if age > 7:
        warnings.append("观测已超过 7 天，需更新样本")
    demo = item.source == "synthetic_demo"
    if demo:
        warnings.append("合成样例，所有数值及核验说明仅演示")
        confidence = min(confidence, 20)
    warnings.extend(["想要/浏览是兴趣信号，不是销量或成交量", "竞争及价格区间仅来自同来源、同币种、同类目的本地报价样本；不代表全平台", "成本与核验说明均为用户输入，尚未经独立验证"])
    if strategy == "blue_ocean":
        warnings.append("蓝海为探索假设；稀少样本不能证明需求旺盛")
    recommendation = "blocked" if blockers else "validate"
    if not blockers and not demo and total >= 75 and confidence >= 70:
        recommendation = "priority_validation"
    evidence = {
        "demand": f"想要数={interest if interest is not None else '未知'}；log(1+n)/log(101)×85，上限85；无真实成交数据",
        "profit": profit["basis"],
        "competition": f"本地同类目报价样本 {sample} 条；至少5条后 max(10,80-2n)，仅探索启发式",
        "fulfillment": "货源及履约证据齐全=80，否则0；需人工查验凭据",
        "risk": "疑似禁售词=0；否则 max(0,85-20×待核验/否决项数)",
        "differentiation": "用户填写差异化依据=70，否则0；尚未通过成交实验验证",
    }
    return {"strategy": strategy, "score_total": total, "confidence_score": confidence,
        "dimensions": {k: {"score": round(v, 2), "weight": weights[k], "evidence": evidence[k]} for k, v in dimensions.items()},
        "profit": profit, "market": market, "missing": sorted(set(missing)), "warnings": warnings,
        "blockers": blockers, "recommendation": recommendation, "is_demo": demo,
        "confidence_basis": {"source_confidence": item.source_confidence, "coverage": round(sum(coverage_fields)/len(coverage_fields), 3), "freshness_factor": freshness},
        "scoring_version": "p0-rules-v1", "scored_at": now.isoformat()}
