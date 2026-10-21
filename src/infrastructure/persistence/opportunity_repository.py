"""Opportunity storage, sharing the application's SQLite file and pragmas."""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime, timezone

from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class OpportunityRepository:
    def __init__(self, db_path=None):
        self.db_path = db_path
        with sqlite_connection(db_path) as conn:
            init_schema(conn)

    @contextmanager
    def transaction(self):
        with sqlite_connection(self.db_path) as conn:
            with conn:
                conn.execute("BEGIN IMMEDIATE")
                yield conn

    def categories(self):
        with sqlite_connection(self.db_path) as conn:
            return [dict(name=r["name"], parent=r["parent"], keywords=json.loads(r["keywords_json"]))
                    for r in conn.execute("SELECT * FROM categories ORDER BY parent, name")]

    def save_category(self, config):
        with self.transaction() as conn:
            if config.parent == config.name:
                raise ValueError("类目不能引用自身")
            if config.parent:
                parent = conn.execute("SELECT parent FROM categories WHERE name=?", (config.parent,)).fetchone()
                if parent is None or parent["parent"] is not None:
                    raise ValueError("请选择现有一级类目作为父类目")
                if conn.execute("SELECT 1 FROM categories WHERE parent=?", (config.name,)).fetchone():
                    raise ValueError("含子类目的一级类目不能变为二级")
            conn.execute("INSERT INTO categories VALUES (?,?,?) ON CONFLICT(name) DO UPDATE SET parent=excluded.parent,keywords_json=excluded.keywords_json",
                         (config.name, config.parent, json_text(config.keywords)))
            conn.execute("DELETE FROM keyword_seeds WHERE category=? AND origin='user_seed' AND id NOT IN (SELECT keyword_id FROM discovery_jobs)", (config.name,))
            for word in dict.fromkeys(config.keywords):
                self.add_keyword(conn, config.name, word, "user_seed")

    @staticmethod
    def add_keyword(conn, category, keyword, origin):
        from src.domain.opportunity_market import normalize_keyword
        keyword = " ".join(keyword.split())[:80]
        normalized = normalize_keyword(keyword)
        if not normalized or any(normalize_keyword(r[0]) == normalized for r in conn.execute(
                "SELECT keyword FROM keyword_seeds WHERE category=?", (category,))):
            return
        if conn.execute("SELECT COUNT(*) FROM keyword_seeds").fetchone()[0] >= 5000:
            return
        conn.execute("INSERT OR IGNORE INTO keyword_seeds(category,keyword,origin,discovered_at) VALUES (?,?,?,?)",
                     (category, keyword[:80], origin, datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def upsert(conn, item, costs):
        payload = item.model_dump(mode="json")
        text = json_text(payload)
        stamp = payload["observed_at"]
        previous = conn.execute("SELECT * FROM opportunity_items WHERE source=? AND source_item_id=?", (item.source, item.source_item_id)).fetchone()
        if previous and previous["currency"] != item.currency:
            raise ValueError("同一商品币种发生变化，需人工确认")
        conn.execute("""INSERT INTO opportunity_items(source,source_item_id,category,title,currency,first_observed_at,observed_at,payload_json)
            VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source,source_item_id) DO NOTHING""",
            (item.source, item.source_item_id, item.category, item.title, item.currency, stamp, stamp, text))
        row = conn.execute("SELECT * FROM opportunity_items WHERE source=? AND source_item_id=?", (item.source, item.source_item_id)).fetchone()
        item_id = row["id"]
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
        new_snapshot = conn.execute("INSERT OR IGNORE INTO opportunity_observations(item_id,observed_at,payload_json,fingerprint) VALUES (?,?,?,?)",
                                   (item_id, stamp, text, fingerprint)).rowcount
        if stamp >= row["observed_at"]:
            conn.execute("UPDATE opportunity_items SET category=?,title=?,observed_at=?,payload_json=? WHERE id=?", (item.category, item.title, stamp, text, item_id))
            if costs is not None and new_snapshot:
                conn.execute("INSERT INTO cost_assumptions VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                             (item_id, costs.model_dump_json(), datetime.now(timezone.utc).isoformat()))
        if stamp < row["first_observed_at"]:
            conn.execute("UPDATE opportunity_items SET first_observed_at=? WHERE id=?", (stamp, item_id))
        return item_id, previous is None, bool(new_snapshot)

    @staticmethod
    def load_items(conn):
        rows = conn.execute("""SELECT i.*, c.payload_json AS costs_json FROM opportunity_items i
            LEFT JOIN cost_assumptions c ON c.item_id=i.id ORDER BY i.id""").fetchall()
        return [dict(row) for row in rows]

    def detail(self, item_id, strategy):
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("""SELECT i.*, s.payload_json AS score_json, c.payload_json AS costs_json,
                e.status AS experiment_status FROM opportunity_items i
                LEFT JOIN opportunity_scores s ON s.item_id=i.id AND s.strategy=?
                LEFT JOIN cost_assumptions c ON c.item_id=i.id LEFT JOIN experiments e ON e.item_id=i.id
                WHERE i.id=?""", (strategy, item_id)).fetchone()
            if row is None:
                return None
            result = self.decorate(row)
            observations = conn.execute("SELECT observed_at,payload_json FROM opportunity_observations WHERE item_id=? ORDER BY observed_at DESC,id DESC LIMIT 100", (item_id,)).fetchall()
            result["observations"] = [{"observed_at": r["observed_at"], "data": json.loads(r["payload_json"])} for r in observations]
            result["observation_count"] = conn.execute("SELECT COUNT(*) FROM opportunity_observations WHERE item_id=?", (item_id,)).fetchone()[0]
            result["baseline_only"] = conn.execute("SELECT COUNT(DISTINCT observed_at) FROM opportunity_observations WHERE item_id=?", (item_id,)).fetchone()[0] == 1
            # Traceable suspicion only. Different specifications are never merged.
            candidates = conn.execute("SELECT id,title,source_item_id FROM opportunity_items WHERE id<>? AND source=? AND category=? LIMIT 500", (item_id, row["source"], row["category"])).fetchall()
            from difflib import SequenceMatcher
            result["suspected_duplicates"] = [{**dict(r), "similarity": round(SequenceMatcher(None, r["title"], row["title"]).ratio(), 3), "basis": "标题相似；规格/成色未核验，未合并"}
                for r in candidates if SequenceMatcher(None, r["title"], row["title"]).ratio() >= .85][:20]
            return result

    @staticmethod
    def decorate(row):
        return {"id": row["id"], **json.loads(row["payload_json"]), "first_observed_at": row["first_observed_at"],
                "score": json.loads(row["score_json"]) if row["score_json"] else None,
                "costs": json.loads(row["costs_json"]) if row["costs_json"] else {}, "experiment_status": row["experiment_status"]}

    def ranking(self, *, strategy="physical", category="", q="", min_confidence=0, min_margin=None,
                source_scope="all", sort="score_total", page=1, limit=20, pool="all"):
        columns = {"score_total": "s.score_total", "confidence_score": "s.confidence_score", "net_margin": "s.net_margin", "observed_at": "i.observed_at"}
        conditions, params = ["s.strategy=?"], [strategy]
        if category:
            conditions.append("(i.category=? OR i.category IN (SELECT name FROM categories WHERE parent=?))")
            params.extend([category, category])
        if q:
            conditions.append("instr(normalize_keyword(i.title),normalize_keyword(?))>0")
            params.append(q)
        if pool != "all":
            status_clause = "" if pool == "candidates" else " AND candidate.status=?"
            conditions.append("EXISTS (SELECT 1 FROM experiments candidate WHERE candidate.item_id=i.id"+status_clause+")")
            if pool != "candidates":
                params.append(pool)
        conditions.append("s.confidence_score>=?")
        params.append(min_confidence)
        if min_margin is not None:
            conditions.append("s.net_margin>=?")
            params.append(min_margin)
        if source_scope != "all":
            conditions.append("i.source='synthetic_demo'" if source_scope == "demo" else "i.source<>'synthetic_demo'")
        where = " AND ".join(conditions)
        with sqlite_connection(self.db_path) as conn:
            from src.domain.opportunity_market import normalize_keyword
            conn.create_function("normalize_keyword",1,normalize_keyword,deterministic=True)
            total = conn.execute(f"SELECT COUNT(*) FROM opportunity_items i JOIN opportunity_scores s ON i.id=s.item_id WHERE {where}", params).fetchone()[0]
            rows = conn.execute(f"""SELECT i.*, s.payload_json AS score_json, c.payload_json AS costs_json,e.status AS experiment_status
                FROM opportunity_items i JOIN opportunity_scores s ON i.id=s.item_id
                LEFT JOIN cost_assumptions c ON c.item_id=i.id LEFT JOIN experiments e ON e.item_id=i.id
                WHERE {where} ORDER BY {columns[sort]} DESC,i.id ASC LIMIT ? OFFSET ?""", params + [limit, (page-1)*limit]).fetchall()
            return {"items": [self.decorate(row) for row in rows], "total": total, "page": page, "limit": limit}

    def history(self, item_id, limit=100):
        from src.domain.opportunity_history import observation_history
        with sqlite_connection(self.db_path) as conn:
            if not conn.execute("SELECT 1 FROM opportunity_items WHERE id=?", (item_id,)).fetchone():
                return None
            total = conn.execute("SELECT COUNT(*) FROM opportunity_observations WHERE item_id=?", (item_id,)).fetchone()[0]
            rows = conn.execute("SELECT id,observed_at,payload_json FROM opportunity_observations WHERE item_id=? ORDER BY observed_at DESC,id DESC LIMIT ?", (item_id, limit)).fetchall()
            return observation_history([{"id": r["id"], "observed_at": r["observed_at"], "data": json.loads(r["payload_json"])} for r in reversed(rows)], total)

    def sellers(self, *, source_scope="all", page=1, limit=20, watching_only=False):
        condition = ""
        if source_scope != "all":
            condition = " AND i.source='synthetic_demo'" if source_scope == "demo" else " AND i.source<>'synthetic_demo'"
        query = f"""WITH associations AS (
            SELECT i.source,json_extract(o.payload_json,'$.seller_id') AS seller_id,i.id,o.observed_at
            FROM opportunity_items i JOIN opportunity_observations o ON o.item_id=i.id
            WHERE json_extract(o.payload_json,'$.seller_id') IS NOT NULL
            AND json_extract(o.payload_json,'$.seller_id')<>'' {condition}
        ), sellers AS (
            SELECT source,seller_id,COUNT(DISTINCT id) AS observed_items,MIN(observed_at) AS first_observed_at,
                MAX(observed_at) AS last_observed_at FROM associations GROUP BY source,seller_id
        ) SELECT s.*,COALESCE(w.watching,0) AS watching,COALESCE(w.note,'') AS note FROM sellers s
            LEFT JOIN opportunity_seller_watches w ON w.source=s.source AND w.seller_id=s.seller_id"""
        if watching_only:
            query += " WHERE w.watching=1"
        with sqlite_connection(self.db_path) as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM ({query})").fetchone()[0]
            rows = conn.execute(query+" ORDER BY last_observed_at DESC,source,seller_id LIMIT ? OFFSET ?", (limit,(page-1)*limit)).fetchall()
            return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit,
                "note": "仅列出已观察到稳定ID的卖家及商品关联；不是店铺完整目录或当前在售数量，不发平台请求"}

    def seller_items(self, source, seller_id, *, page=1, limit=20):
        with sqlite_connection(self.db_path) as conn:
            params = (source,seller_id)
            query = """SELECT i.id,i.title,i.source,i.source_item_id,i.currency,
                MIN(o.observed_at) AS first_associated_at,MAX(o.observed_at) AS last_associated_at
                FROM opportunity_items i JOIN opportunity_observations o ON o.item_id=i.id
                WHERE i.source=? AND json_extract(o.payload_json,'$.seller_id')=? GROUP BY i.id"""
            total = conn.execute(f"SELECT COUNT(*) FROM ({query})",params).fetchone()[0]
            rows = conn.execute(query+" ORDER BY last_associated_at DESC,i.id LIMIT ? OFFSET ?", params+(limit,(page-1)*limit)).fetchall()
            return {"items": [dict(r) for r in rows], "total": total, "page": page, "limit": limit}

    def watch_seller(self, source, seller_id, watching, note):
        with self.transaction() as conn:
            if not conn.execute("""SELECT 1 FROM opportunity_items i JOIN opportunity_observations o ON i.id=o.item_id
                WHERE i.source=? AND json_extract(o.payload_json,'$.seller_id')=? LIMIT 1""", (source,seller_id)).fetchone():
                return False
            conn.execute("INSERT OR REPLACE INTO opportunity_seller_watches VALUES (?,?,?,?,?)",
                         (source,seller_id,int(watching),note,datetime.now(timezone.utc).isoformat()))
        return True
