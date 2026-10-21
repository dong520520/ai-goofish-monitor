"""Bounded local SQLite projection. No network, browser, or collector invocation."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from src.domain.models.opportunity import OpportunityItem
from src.infrastructure.persistence.opportunity_repository import OpportunityRepository, json_text
from src.infrastructure.persistence.sqlite_connection import sqlite_connection

PREFIX = "opportunity_sync:"
SOURCES = ("result_items", "price_snapshots")
BATCH_SIZE = 100
MAX_ITEMS = 10000


def _get(conn, key, default=None):
    row = conn.execute("SELECT value FROM app_metadata WHERE key=?", (PREFIX+key,)).fetchone()
    return row[0] if row else default


def _set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO app_metadata VALUES (?,?)", (PREFIX+key, str(value)))


def _count(value):
    if value is None or str(value).strip() in ("", "NaN", "-", "暂无"):
        return None
    if not re.fullmatch(r"[0-9]+", str(value).strip()):
        return None
    number = int(value)
    return number if number <= 1_000_000_000 else None


def _stable_id(value):
    text = str(value or "").strip()
    return text if re.fullmatch(r"[1-9][0-9]{0,199}", text) else None


def adapt_monitor_row(origin, row):
    """Only whitelist observed public item fields. Raw response/cookies are not copied."""
    record = json.loads(row["raw_json"]) if origin == "result_items" else {}
    if not isinstance(record, dict):
        raise ValueError("原监控记录不是对象")
    product = record.get("商品信息")
    seller = record.get("卖家信息")
    product = {} if product is None else product
    seller = {} if seller is None else seller
    extra = json.loads(row.get("opportunity_metadata_json", "{}")) if origin == "price_snapshots" else product
    if not all(isinstance(v, dict) for v in (product, seller, extra)):
        raise ValueError("原监控商品/卖家/快照字段不是对象")
    item_id = _stable_id(row["item_id"])
    if item_id is None:
        raise ValueError("缺少真实数字商品ID，不能将昵称、URL或占位符用于身份去重")
    raw_time = row["crawl_time"] if origin == "result_items" else row["snapshot_time"]
    stamp = datetime.fromisoformat(raw_time)
    assumed_timezone = stamp.tzinfo is None
    if assumed_timezone:
        stamp = stamp.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return OpportunityItem(source="goofish", source_item_id=item_id, title=row["title"] or "",
        url=row["link"] or None, price=row["price"], observed_at=stamp,
        seller_id=_stable_id(seller.get("卖家ID") or extra.get("卖家ID")),
        want_count=_count(extra.get("“想要”人数")), view_count=_count(extra.get("浏览量")),
        condition=extra.get("成色") or None, source_confidence=.6,
        raw_metadata={"adapter": "monitor_sync", "table": origin, "row_id": row["id"],
            "time_basis": "legacy naive timestamp interpreted Asia/Shanghai" if assumed_timezone else "explicit timezone",
            "unverified_publish_text": row["publish_time"], "scan_completeness": "unknown"})


class OpportunitySyncService:
    def __init__(self, repository=None):
        self.repository = repository or OpportunityRepository()

    def status(self):
        with sqlite_connection(self.repository.db_path) as conn:
            cursors = {source: int(_get(conn, source, "0")) for source in SOURCES}
            pending = {source: conn.execute(f"SELECT COUNT(*) FROM {source} WHERE id>?", (cursors[source],)).fetchone()[0] for source in SOURCES}
            rejections = [dict(r) for r in conn.execute("SELECT * FROM opportunity_sync_rejections ORDER BY rejected_at DESC,row_id DESC LIMIT 20")]
            return {"enabled": _get(conn, "enabled", "1") == "1", "cursors": cursors, "pending": pending,
                "last_run_at": _get(conn, "last_run_at"), "last_error": _get(conn, "last_error"),
                "rejected_count": conn.execute("SELECT COUNT(*) FROM opportunity_sync_rejections").fetchone()[0],
                "rejections": rejections, "interval_seconds": 60, "batch_size_per_table": BATCH_SIZE, "external_calls": 0}

    def configure(self, enabled):
        with self.repository.transaction() as conn:
            _set(conn, "enabled", "1" if enabled else "0")
            if enabled:
                _set(conn, "last_error", "")
        return self.status()

    def run_batch(self, limit=BATCH_SIZE):
        if not 1 <= limit <= BATCH_SIZE:
            raise ValueError("每表同步批次须在1–100之间")
        result = dict(processed=0, inserted=0, new_snapshots=0, rejected=0, paused=False)
        categories = self.repository.categories()
        dirty = "0"
        try:
            with self.repository.transaction() as conn:
                if _get(conn, "enabled", "1") != "1":
                    return {**result, "paused": True}
                dirty = _get(conn, "needs_scoring", "0")
                for source in SOURCES:
                    cursor = int(_get(conn, source, "0"))
                    rows = conn.execute(f"SELECT * FROM {source} WHERE id>? ORDER BY id LIMIT ?", (cursor, limit)).fetchall()
                    for raw in rows:
                        row = dict(raw)
                        try:
                            item = adapt_monitor_row(source, row)
                            # Shared classification rule with CSV imports.
                            from src.services.opportunity_service import classify_item
                            classify_item(item, categories)
                            exists = conn.execute("SELECT 1 FROM opportunity_items WHERE source=? AND source_item_id=?", (item.source, item.source_item_id)).fetchone()
                            if not exists and conn.execute("SELECT COUNT(*) FROM opportunity_items").fetchone()[0] >= MAX_ITEMS:
                                # Capacity is backpressure, not a bad source row: don't advance past it.
                                _set(conn, "enabled", "0")
                                _set(conn, "last_error", "商品容量达到10000，同步已暂停；请人工处理后恢复")
                                result["paused"] = True
                                break
                            _, new, snapshot = self.repository.upsert(conn, item, None)
                            result["inserted"] += new
                            result["new_snapshots"] += snapshot
                        except (ValueError, TypeError, ValidationError) as exc:
                            reason = "; ".join(f"{'.'.join(map(str,e['loc']))}: {e['msg']}" for e in exc.errors()) if isinstance(exc, ValidationError) else str(exc)
                            conn.execute("INSERT OR REPLACE INTO opportunity_sync_rejections VALUES (?,?,?,?)",
                                (source, row["id"], reason[:500], datetime.now(timezone.utc).isoformat()))
                            result["rejected"] += 1
                        cursor = row["id"]
                        _set(conn, source, cursor)
                        result["processed"] += 1
                    if result["paused"]:
                        break
                _set(conn, "last_run_at", datetime.now(timezone.utc).isoformat())
                if result["new_snapshots"]:
                    dirty = str(conn.execute("SELECT MAX(id) FROM opportunity_observations").fetchone()[0])
                    _set(conn, "needs_scoring", dirty)
            if dirty != "0":
                from src.services.opportunity_service import OpportunityService
                OpportunityService(self.repository).rescore_all()
                with self.repository.transaction() as conn:
                    conn.execute("UPDATE app_metadata SET value='0' WHERE key=? AND value=?", (PREFIX+"needs_scoring", dirty))
            return result
        except Exception as exc:
            # Ingestion errors roll back; a scoring error leaves a durable dirty
            # marker so explicit resume retries scoring even with no new rows.
            with self.repository.transaction() as conn:
                _set(conn, "enabled", "0")
                _set(conn, "last_error", f"同步异常（{type(exc).__name__}），已暂停，需人工检查后恢复")
            raise
