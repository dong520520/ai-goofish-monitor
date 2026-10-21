"""Observed cohort evidence, separate from the existing six-axis item score.

Quantile/missing-data concepts are independently implemented; no unlicensed
upstream code is imported. Counts describe local samples, never market totals.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import unicodedata


def normalize_keyword(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def comparable_key(item):
    metadata = item.raw_metadata
    # Only explicit scalar identity evidence; titles never establish a model/SKU.
    identity = tuple(str(metadata.get(k) or "").strip() if isinstance(metadata.get(k), (str, int)) else ""
                     for k in ("model", "sku", "specification"))
    return (item.source, item.category, item.currency, item.condition or "", *identity)


def quantile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    position = Decimal(len(values) - 1) * Decimal(fraction)
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return str((values[low] + (values[high] - values[low]) * (position-low)).quantize(Decimal("0.01")))


def cohort_evidence(members, *, now=None):
    now = now or datetime.now(timezone.utc)
    items = [item for _, item in members]
    first = items[0]
    prices = [i.price for i in items if i.price is not None]
    wants = sum(i.want_count is not None for i in items)
    views = sum(i.view_count is not None for i in items)
    sellers = {i.seller_id for i in items if i.seller_id}
    seller_known = sum(bool(i.seller_id) for i in items)
    key = comparable_key(first)
    n = len(items)
    missing = []
    for field, count in (("price", len(prices)), ("want_count", wants), ("view_count", views), ("seller_id", seller_known)):
        if count < n:
            missing.append(f"{field}: {n-count}/{n} 未知")
    if not key[3]:
        missing.append("condition 未知，成色可比性未确认")
    if not any(key[4:]):
        missing.append("model/sku/specification 未知，型号规格可比性未确认")
    if n < 5:
        missing.append("样本不足5件，需补充证据")
    coverage = (len(prices) + wants + views + seller_known) / (4*n)
    freshness = sum(1 if (now-i.observed_at).days < 8 else .7 if (now-i.observed_at).days < 31 else .4 for i in items)/n
    confidence = round(100 * min(1, n/5) * coverage * freshness *
                       (sum(i.source_confidence for i in items)/n) * (1 if all(key[3:4]) and any(key[4:]) else .5), 2)
    if first.source == "synthetic_demo":
        confidence = min(20, confidence)
    return {"source": key[0], "category": key[1], "currency": key[2], "condition": key[3] or None,
            "model": key[4] or None, "sku": key[5] or None, "specification": key[6] or None,
            "sample_count": n, "priced_count": len(prices), "distinct_sellers": len(sellers) if seller_known else None,
            "seller_coverage": round(seller_known/n, 3), "want_coverage": round(wants/n, 3),
            "view_coverage": round(views/n, 3), "p25": quantile(prices, ".25"), "p50": quantile(prices, ".5"),
            "p75": quantile(prices, ".75"), "observed_from": min(i.observed_at for i in items).isoformat(),
            "observed_to": max(i.observed_at for i in items).isoformat(), "confidence_score": confidence,
            "missing": missing, "item_ids": [identifier for identifier, _ in members[:100]],
            "item_ids_truncated": n > 100, "is_demo": first.source == "synthetic_demo",
            "basis": "最新观测报价样本；非成交价、销量、全市场规模或新上架量；未知规格分组仍需人工核验"}


def build_cohorts(members):
    groups = defaultdict(list)
    for identifier, item in members:
        groups[comparable_key(item)].append((identifier, item))
    return [cohort_evidence(group) for _, group in sorted(groups.items())]
