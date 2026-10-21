"""Bounded offline research using the original repository and SQLite file."""
import csv
import io
import json
from collections import defaultdict

from src.domain.models.opportunity import OpportunityItem
from src.domain.opportunity_market import build_cohorts, normalize_keyword
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


def safe_csv(fields, rows):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(fields)
    for row in rows:
        writer.writerow(["'"+v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in row])
    return "\ufeff"+out.getvalue()


class OpportunityResearchService:
    def __init__(self, repository):
        self.repository = repository

    def evidence(self, *, category="", keyword="", source_scope="imported", limit=100):
        categories = self.repository.categories()
        names = {c["name"] for c in categories if c["name"] == category or c["parent"] == category}
        normalized = normalize_keyword(keyword)
        members = []
        coverage = {c["name"]: 0 for c in categories if (c["keywords"] or c["parent"]) and (not category or c["name"] in names)}
        with sqlite_connection(self.repository.db_path) as conn:
            # Same 10,000-item bound as the original import path. Never read observations as extra products.
            records = conn.execute("SELECT id,payload_json FROM opportunity_items ORDER BY id LIMIT 10001").fetchall()
            for row in records[:10000]:
                item = OpportunityItem.model_validate_json(row["payload_json"])
                if source_scope == "imported" and item.source == "synthetic_demo" or source_scope == "demo" and item.source != "synthetic_demo":
                    continue
                if category and item.category not in names or normalized and normalized not in normalize_keyword(item.title):
                    continue
                members.append((row["id"], item))
                coverage[item.category] = coverage.get(item.category, 0)+1
            lineage = []
            titles = defaultdict(list)
            for identifier, item in members:
                titles[item.category].append((identifier, normalize_keyword(item.title)))
            for k in conn.execute("SELECT * FROM keyword_seeds ORDER BY id LIMIT 5000"):
                if category and k["category"] not in names:
                    continue
                if normalized and normalized != normalize_keyword(k["keyword"]):
                    continue
                word = normalize_keyword(k["keyword"])
                matches = [identifier for identifier, title in titles[k["category"]] if word in title]
                if matches or normalized:
                    lineage.append({**dict(k), "item_ids": matches[:100], "matched_count": len(matches)})
        cohorts = build_cohorts(members)
        cohorts.sort(key=lambda c: (-c["confidence_score"], -c["sample_count"], c["source"], c["category"], c["currency"], c["condition"] or ""))
        return {"cohorts": cohorts[:limit], "total_cohorts": len(cohorts), "truncated": len(cohorts)>limit,
                "input_truncated": len(records)>10000, "source_scope": source_scope, "keyword": keyword,
                "category_coverage": [{"category": name, "sample_count": count} for name, count in sorted(coverage.items())],
                "lineage": lineage[:100], "lineage_truncated": len(lineage)>100,
                "external_calls": 0, "note": "离线市场证据与商品评分独立；来源、币种、成色及明确型号/规格分别分析，合成数据隔离。"}

    def export(self, **options):
        data = self.evidence(**options, limit=10000)
        fields = ["source", "category", "currency", "condition", "model", "sku", "specification", "sample_count", "priced_count", "p25", "p50", "p75", "distinct_sellers", "seller_coverage", "want_coverage", "view_coverage", "confidence_score", "observed_from", "observed_to", "missing", "item_ids", "basis"]
        return safe_csv(fields, [[json.dumps(c[k], ensure_ascii=False) if isinstance(c[k], list) else c[k] for k in fields] for c in data["cohorts"]])
