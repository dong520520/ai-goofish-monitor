"""Compare observed values only; missing/disappeared listings are never sales."""
from decimal import Decimal


def observation_history(rows, total_observations):
    # Same-time revisions are one instant. Preserve their count and conflict warning.
    by_time = {}
    revisions = {}
    for row in rows:
        stamp = row["observed_at"]
        revisions[stamp] = revisions.get(stamp, 0) + 1
        by_time[stamp] = row
    points, previous = [], None
    for stamp, row in sorted(by_time.items()):
        data = row["data"]
        point = {"observation_id": row["id"], "observed_at": stamp, "price": data.get("price"),
                 "want_count": data.get("want_count"), "view_count": data.get("view_count"),
                 "seller_id": data.get("seller_id"), "title": data["title"], "condition": data.get("condition"),
                 "currency": data["currency"], "revision_count": revisions[stamp], "changes": {}, "warnings": []}
        if revisions[stamp] > 1:
            point["warnings"].append("同一时刻存在修订，采用最后保存版本，不视为新的时间点")
        if previous:
            if data["title"] != previous["title"] or data.get("condition") != previous["condition"]:
                point["warnings"].append("标题或成色变化，请人工核验报价可比性")
            for field in ("price", "want_count", "view_count"):
                old, new = previous[field], point[field]
                delta = None if old is None or new is None else Decimal(str(new))-Decimal(str(old))
                point["changes"][field] = float(delta) if delta is not None else None
                if field != "price" and delta is not None and delta < 0:
                    point["warnings"].append(f"{field}计数下降，可能重置或修正，不能解释为负销量")
        else:
            point["changes"] = dict.fromkeys(("price", "want_count", "view_count"))
        points.append(point)
        previous = point
    first, last = (points[0], points[-1]) if points else (None, None)
    price_delta = None
    if len(points) > 1 and first["price"] is not None and last["price"] is not None:
        price_delta = float(Decimal(str(last["price"]))-Decimal(str(first["price"])))
    return {"points": points, "distinct_times": len(points), "total_observations": total_observations,
            "truncated": total_observations > len(rows), "baseline_only": len(points) <= 1,
            "price_delta": price_delta, "sales_count": None,
            "note": "仅比较窗口内已观察报价与兴趣计数；没有扫描完整性依据，不生成消失、上新或成交事件"}
