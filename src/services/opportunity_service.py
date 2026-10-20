"""CSV / existing monitor adapters, offline discovery and deterministic ranking."""
from __future__ import annotations

import csv
import io
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from src.domain.models.opportunity import CostAssumptions, OpportunityItem, DEFAULT_WEIGHTS
from src.domain.opportunity_scoring import score_opportunity
from src.infrastructure.persistence.opportunity_repository import OpportunityRepository, json_text
from src.infrastructure.persistence.sqlite_connection import sqlite_connection

REQUIRED_COLUMNS = {"source", "source_item_id", "title", "observed_at"}
MAX_ROWS = 1000
MAX_ITEMS = 10000


def _reject_json_constant(value):
    raise ValueError("raw_metadata 包含非有限数字：" + value)


def parse_csv(content):
    if len(content.encode("utf-8")) > 2_000_000:
        raise ValueError("CSV 最大 2 MB")
    try:
        reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)) or not REQUIRED_COLUMNS.issubset(columns):
            raise ValueError("CSV 表头需包含且不重复：source,source_item_id,title,observed_at")
        rows = []
        for number, row in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise ValueError("单次最多 1000 行；请分批导入")
            rows.append((number, row))
        return rows
    except csv.Error as exc:
        raise ValueError("CSV 格式错误：" + str(exc)) from exc


class OpportunityService:
    def __init__(self, repository=None):
        self.repository = repository or OpportunityRepository()

    def import_csv(self, content, *, origin="csv"):
        rows = parse_csv(content)
        categories = self.repository.categories()
        known = {c["name"] for c in categories}
        accepted, inserted, snapshots, errors = 0, 0, 0, []
        with self.repository.transaction() as conn:
            if conn.execute("SELECT COUNT(*) FROM opportunity_items").fetchone()[0] + len(rows) > MAX_ITEMS:
                # Allow replay at capacity; check actual inserts below.
                at_capacity = True
            else:
                at_capacity = False
            for line, row in rows:
                try:
                    if None in row:
                        raise ValueError("列数超过表头，请用双引号转义逗号")
                    unknown = set(row) - set(OpportunityItem.model_fields) - set(CostAssumptions.model_fields)
                    if unknown:
                        raise ValueError("未知字段：" + ",".join(sorted(unknown)))
                    payload = {k: v for k, v in row.items() if k in OpportunityItem.model_fields and v is not None and v.strip()}
                    if "raw_metadata" in payload:
                        payload["raw_metadata"] = json.loads(payload["raw_metadata"], parse_constant=_reject_json_constant)
                    item = OpportunityItem.model_validate(payload)
                    if item.category == "未分类":
                        matches = [(max(len(k) for k in cat["keywords"] if k.casefold() in item.title.casefold()), cat["name"])
                                   for cat in categories if any(k.casefold() in item.title.casefold() for k in cat["keywords"])]
                        if matches:
                            item.category = sorted(matches, key=lambda r: (-r[0], r[1]))[0][1]
                    if item.category not in known:
                        raise ValueError("未知类目，请先在类目配置中添加：" + item.category)
                    cost_fields = {k: v for k, v in row.items() if k in CostAssumptions.model_fields and v is not None and v.strip()}
                    costs = CostAssumptions.model_validate(cost_fields) if cost_fields else None
                    if at_capacity and conn.execute("SELECT COUNT(*) FROM opportunity_items").fetchone()[0] >= MAX_ITEMS:
                        exists = conn.execute("SELECT 1 FROM opportunity_items WHERE source=? AND source_item_id=?", (item.source, item.source_item_id)).fetchone()
                        if not exists:
                            raise ValueError("P0 最多保存 10000 件商品，请归档后再导入")
                    _, new, snapshot = self.repository.upsert(conn, item, costs)
                    accepted += 1
                    inserted += new
                    snapshots += snapshot
                except (ValueError, ValidationError, TypeError) as exc:
                    # Do not echo user rows or potentially sensitive imported values.
                    reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
                    errors.append({"line": line, "reason": reason[:500]})
            conn.execute("INSERT INTO opportunity_imports(imported_at,origin,accepted,rejected,errors_json) VALUES (?,?,?,?,?)",
                         (datetime.now(timezone.utc).isoformat(), origin, accepted, len(errors), json_text(errors)))
        self.rescore_all()
        return {"accepted": accepted, "inserted": inserted, "duplicates": accepted-inserted,
                "new_snapshots": snapshots, "rejected": len(errors), "errors": errors,
                "note": "导入为观测基线；不生成上新或成交事件"}

    def rescore_all(self, strategy=None, weights=None):
        strategies = [strategy] if strategy else list(DEFAULT_WEIGHTS)
        with self.repository.transaction() as conn:
            records = self.repository.load_items(conn)
            groups = defaultdict(list)
            for row in records:
                item = OpportunityItem.model_validate_json(row["payload_json"])
                groups[(item.source, item.category, item.currency)].append(item)
            now = datetime.now(timezone.utc)
            for row in records:
                item = OpportunityItem.model_validate_json(row["payload_json"])
                costs = CostAssumptions.model_validate_json(row["costs_json"]) if row["costs_json"] else CostAssumptions()
                sample = groups[(item.source, item.category, item.currency)]
                prices = [float(x.price) for x in sample if x.price is not None and x.price > 0]
                market = {"sample_count": len(sample), "price_low": min(prices) if prices else None,
                          "price_high": max(prices) if prices else None, "currency": item.currency,
                          "source": item.source, "basis": "本地同类目报价；非可比成色成交估价"}
                for mode in strategies:
                    if weights is None:
                        saved = conn.execute("SELECT value FROM app_metadata WHERE key=?", ("opportunity_weights:"+mode,)).fetchone()
                        selected_weights = json.loads(saved[0]) if saved else None
                    else:
                        selected_weights = weights
                        conn.execute("INSERT OR REPLACE INTO app_metadata VALUES (?,?)", ("opportunity_weights:"+mode, json_text(weights)))
                    score = score_opportunity(item, costs, mode, market, selected_weights, now=now)
                    conn.execute("INSERT OR REPLACE INTO opportunity_scores VALUES (?,?,?,?,?,?)",
                        (row["id"], mode, score["score_total"], score["confidence_score"], score["profit"]["net_margin"], json_text(score)))
        return {"scored_items": len(records), "strategies": strategies}

    def update_costs(self, item_id, costs):
        with self.repository.transaction() as conn:
            if not conn.execute("SELECT 1 FROM opportunity_items WHERE id=?", (item_id,)).fetchone():
                return False
            conn.execute("INSERT OR REPLACE INTO cost_assumptions VALUES (?,?,?)", (item_id, costs.model_dump_json(), datetime.now(timezone.utc).isoformat()))
        self.rescore_all()
        return True

    def candidate(self, item_id, strategy):
        with self.repository.transaction() as conn:
            if not conn.execute("SELECT 1 FROM opportunity_items WHERE id=?", (item_id,)).fetchone():
                return False
            conn.execute("INSERT INTO experiments(item_id,strategy,created_at) VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET strategy=excluded.strategy",
                         (item_id, strategy, datetime.now(timezone.utc).isoformat()))
        return True

    def import_existing(self, limit=500):
        """Read existing result_items / price_snapshots, no network or second scraper."""
        from zoneinfo import ZoneInfo
        from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
        bootstrap_sqlite_storage(self.repository.db_path)
        rows = []
        with sqlite_connection(self.repository.db_path) as conn:
            existing = conn.execute("SELECT * FROM result_items ORDER BY crawl_time DESC,id DESC LIMIT ?", (limit,)).fetchall()
            for r in existing:
                # Nicknames are not stable seller IDs; publish_time may be relative text.
                rows.append({"source": "goofish", "source_item_id": r["item_id"] or "", "title": r["title"] or "",
                    "url": r["link"] or "", "price": r["price"] if r["price"] is not None else "", "observed_at": self._local_time(r["crawl_time"], ZoneInfo("Asia/Shanghai")),
                    "source_confidence": .6, "raw_metadata": json_text({"adapter": "existing_result_items", "result_id": r["id"], "unverified_publish_text": r["publish_time"], "time_basis": "legacy naive timestamps interpreted Asia/Shanghai"})})
            remaining = max(0, limit-len(rows))
            for r in conn.execute("SELECT * FROM price_snapshots ORDER BY snapshot_time DESC,id DESC LIMIT ?", (remaining,)):
                rows.append({"source": "goofish", "source_item_id": r["item_id"], "title": r["title"] or "", "url": r["link"] or "",
                    "price": r["price"], "observed_at": self._local_time(r["snapshot_time"], ZoneInfo("Asia/Shanghai")), "source_confidence": .6,
                    "raw_metadata": json_text({"adapter": "existing_price_snapshots", "snapshot_id": r["id"], "unverified_publish_text": r["publish_time"]})})
        out = io.StringIO()
        fields = sorted(set().union(*(r.keys() for r in rows))) if rows else sorted(REQUIRED_COLUMNS)
        writer = csv.DictWriter(out, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
        return self.import_csv(out.getvalue(), origin="existing_sqlite")

    @staticmethod
    def _local_time(value, tz):
        try:
            stamp = datetime.fromisoformat(value)
            return stamp.replace(tzinfo=tz).isoformat() if stamp.tzinfo is None else stamp.isoformat()
        except (TypeError, ValueError):
            return value or ""

    def demo(self):
        return self.import_csv((Path(__file__).resolve().parents[1]/"resources"/"opportunity_demo.csv").read_text(encoding="utf-8-sig"), origin="synthetic_demo")

    def expand_keywords(self):
        with self.repository.transaction() as conn:
            seeds = conn.execute("""SELECT k.* FROM keyword_seeds k JOIN categories c ON c.name=k.category
                WHERE k.origin IN ('default_seed','user_seed') AND EXISTS (
                SELECT 1 FROM json_each(c.keywords_json) WHERE value=k.keyword) ORDER BY k.id LIMIT 200""").fetchall()
            items = conn.execute("SELECT id,title,category FROM opportunity_items ORDER BY id DESC LIMIT 500").fetchall()
            before = conn.execute("SELECT COUNT(*) FROM keyword_seeds").fetchone()[0]
            for seed in seeds:
                for suffix in ("配件", "便携", "替换"):
                    self.repository.add_keyword(conn, seed["category"], seed["keyword"]+" "+suffix, f"rule:seed:{seed['id']}")
                for item in items:
                    if item["category"] == seed["category"] and seed["keyword"].casefold() in item["title"].casefold():
                        # Preserve title/specification evidence rather than claim unseen search demand.
                        phrase = re.sub(r"\s+", " ", item["title"]).strip()[:80]
                        self.repository.add_keyword(conn, item["category"], phrase, f"observed_title:item:{item['id']};seed:{seed['id']}")
            after = conn.execute("SELECT COUNT(*) FROM keyword_seeds").fetchone()[0]
        return {"added": after-before, "total": after, "note": "离线候选词，未验证搜索量，不触发采集"}

    def keywords(self):
        with sqlite_connection(self.repository.db_path) as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM keyword_seeds ORDER BY id DESC LIMIT 200")]

    def imports(self):
        with sqlite_connection(self.repository.db_path) as conn:
            return [{**dict(r), "errors": json.loads(r["errors_json"])} for r in conn.execute(
                "SELECT * FROM opportunity_imports ORDER BY id DESC LIMIT 50")]

    def queue(self, request=None):
        with self.repository.transaction() as conn:
            if request:
                pending = conn.execute("SELECT COUNT(*) FROM discovery_jobs WHERE status='pending_manual'").fetchone()[0]
                slots = min(request.budget, max(0, 200-pending))
                breadth = round(slots * request.breadth_ratio)
                for lane, count, seed_clause in (("breadth", breadth, "IN"), ("depth", slots-breadth, "NOT IN")):
                    seeds = conn.execute(f"""SELECT k.id FROM keyword_seeds k WHERE k.origin {seed_clause} ('default_seed','user_seed')
                        AND k.id NOT IN (SELECT keyword_id FROM discovery_jobs) ORDER BY k.id LIMIT ?""", (count,)).fetchall()
                    for seed in seeds:
                        conn.execute("INSERT OR IGNORE INTO discovery_jobs(keyword_id,lane,created_at) VALUES (?,?,?)", (seed["id"], lane, datetime.now(timezone.utc).isoformat()))
                conn.execute("INSERT OR REPLACE INTO app_metadata VALUES ('opportunity_discovery_ratio',?)", (str(request.breadth_ratio),))
            ratio = conn.execute("SELECT value FROM app_metadata WHERE key='opportunity_discovery_ratio'").fetchone()
            jobs = [dict(r) for r in conn.execute("SELECT j.*,k.keyword,k.category FROM discovery_jobs j JOIN keyword_seeds k ON k.id=j.keyword_id ORDER BY j.id DESC LIMIT 200")]
            return {"jobs": jobs, "breadth_ratio": float(ratio[0]) if ratio else .4,
                    "external_calls": 0, "note": "仅人工待办队列；执行器未启用，无外部请求。默认广度40%/深挖60%。"}


def export_csv(result):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["source", "source_item_id", "title", "category", "currency", "price", "observed_at", "strategy", "score_total", "confidence_score", "net_profit", "net_margin", "blockers"])
    for item in result["items"]:
        score = item["score"]
        cells = [item["source"], item["source_item_id"], item["title"], item["category"], item["currency"], item["price"], item["observed_at"], score["strategy"], score["score_total"], score["confidence_score"], score["profit"]["net_profit"], score["profit"]["net_margin"], "；".join(score["blockers"])]
        # Prevent spreadsheet formulas when untrusted titles are opened in Excel.
        writer.writerow(["'"+v if isinstance(v, str) and v.lstrip().startswith(("=", "+", "-", "@")) else v for v in cells])
    return "\ufeff"+out.getvalue()
