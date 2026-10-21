"""Supplier quotes and seven-day ledger on the existing application database."""
import csv
import hashlib
import io
import json
from datetime import date, datetime, timedelta, timezone

from pydantic import ValidationError

from src.domain.models.opportunity import CostAssumptions, OpportunityItem
from src.domain.models.opportunity_business import SupplierQuote, ExperimentEntry
from src.domain.opportunity_experiment import experiment_review, realized_profit
from src.domain.opportunity_scoring import BLOCK_WORDS
from src.infrastructure.persistence.opportunity_repository import json_text
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.opportunity_research_service import safe_csv


def stamp():
    return datetime.now(timezone.utc).isoformat()


class OpportunityBusinessService:
    def __init__(self, service):
        self.service = service
        self.repository = service.repository

    def quote_template(self, item_id=None):
        """Prepare an inquiry, without turning an observed offer into a supplier quote."""
        fields = list(SupplierQuote.model_fields)
        rows = []
        if item_id is not None:
            with sqlite_connection(self.repository.db_path) as conn:
                row = conn.execute("SELECT payload_json FROM opportunity_items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                raise LookupError("商品不存在")
            item = OpportunityItem.model_validate_json(row[0])
            known = {"product": item.title, "currency": item.currency, "condition": item.condition or ""}
            for field in ("model", "sku", "specification"):
                value = item.raw_metadata.get(field)
                if isinstance(value, str) and 0 < len(value.strip()) <= 200:
                    known[field] = value.strip()
            rows.append([known.get(field, "") for field in fields])
        return safe_csv(fields, rows)

    def import_quotes(self, content):
        if len(content.encode("utf-8")) > 2_000_000:
            raise ValueError("CSV 最大2MB")
        try:
            reader = csv.DictReader(io.StringIO(content.lstrip("\ufeff")), strict=True)
            fields = reader.fieldnames or []
            required = {k for k,v in SupplierQuote.model_fields.items() if v.is_required()}
            if len(set(fields)) != len(fields) or not required.issubset(fields) or set(fields)-SupplierQuote.model_fields.keys():
                raise ValueError("报价CSV表头缺少必需字段、含重复列或未知列")
            rows = []
            for line, row in enumerate(reader,2):
                if len(rows) >= 1000:
                    raise ValueError("单次最多1000行")
                rows.append((line,row))
        except csv.Error as exc:
            raise ValueError("报价CSV语法错误") from exc
        accepted, inserted, errors = 0,0,[]
        with self.repository.transaction() as conn:
            total = conn.execute("SELECT COUNT(*) FROM opportunity_supplier_quotes").fetchone()[0]
            for line, row in rows:
                try:
                    if None in row:
                        raise ValueError("列数超过表头")
                    quote = SupplierQuote.model_validate({k:v for k,v in row.items() if v is not None and v.strip()})
                    payload = quote.model_dump_json()
                    fingerprint = hashlib.sha256(payload.encode()).hexdigest()
                    exists = conn.execute("SELECT id FROM opportunity_supplier_quotes WHERE source=? AND quote_id=? AND fingerprint=?", (quote.source,quote.quote_id,fingerprint)).fetchone()
                    if not exists:
                        if total >= 10000:
                            raise ValueError("最多保存10000条报价版本")
                        conn.execute("INSERT INTO opportunity_supplier_quotes(source,quote_id,fingerprint,payload_json,imported_at) VALUES (?,?,?,?,?)",
                                     (quote.source,quote.quote_id,fingerprint,payload,stamp()))
                        inserted += 1
                        total += 1
                    accepted += 1
                except (ValueError, ValidationError, TypeError) as exc:
                    reason = "; ".join(f"{'.'.join(map(str,e['loc']))}: {e['msg']}" for e in exc.errors()) if isinstance(exc,ValidationError) else str(exc)
                    errors.append({"line":line,"reason":reason[:500]})
            conn.execute("INSERT INTO opportunity_imports(imported_at,origin,accepted,rejected,errors_json) VALUES (?,?,?,?,?)",
                         (stamp(),"supplier_quotes",accepted,len(errors),json_text(errors)))
        return {"accepted":accepted,"inserted":inserted,"duplicates":accepted-inserted,"rejected":len(errors),"errors":errors,
                "note":"人工提供报价，未自动验证；同一报价的新版本独立保存，不覆盖已确认关联"}

    def quotes(self, *, source_scope="imported", page=1, limit=50):
        clause = "" if source_scope == "all" else " WHERE source='synthetic_demo'" if source_scope == "demo" else " WHERE source<>'synthetic_demo'"
        with sqlite_connection(self.repository.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM opportunity_supplier_quotes"+clause).fetchone()[0]
            rows = conn.execute("SELECT * FROM opportunity_supplier_quotes"+clause+" ORDER BY id DESC LIMIT ? OFFSET ?", (limit,(page-1)*limit)).fetchall()
        return {"items":[{"id":r["id"],"imported_at":r["imported_at"],**json.loads(r["payload_json"])} for r in rows], "total":total,"page":page,"limit":limit}

    def link_quote(self, item_id, quote_id, confirmation):
        with self.repository.transaction() as conn:
            row = conn.execute("SELECT payload_json FROM opportunity_items WHERE id=?",(item_id,)).fetchone()
            quote_row = conn.execute("SELECT payload_json FROM opportunity_supplier_quotes WHERE id=?",(quote_id,)).fetchone()
            if row is None or quote_row is None:
                raise LookupError("商品或报价不存在")
            item = OpportunityItem.model_validate_json(row[0])
            quote = SupplierQuote.model_validate_json(quote_row[0])
            if item.currency != quote.currency:
                raise ValueError("报价与商品币种不一致，不自动换汇")
            if (item.source == "synthetic_demo") != (quote.source == "synthetic_demo"):
                raise ValueError("合成报价与真实商品不得交叉关联")
            for field in ("model","sku","specification"):
                actual = item.raw_metadata.get(field)
                if actual is not None and str(actual) != str(getattr(quote,field)):
                    raise ValueError(f"明确的{field}不一致，请核实商品身份")
            if item.condition and item.condition != quote.condition:
                raise ValueError("成色不一致，请核实商品身份")
            previous = conn.execute("SELECT payload_json FROM cost_assumptions WHERE item_id=?",(item_id,)).fetchone()
            costs = CostAssumptions.model_validate_json(previous[0]) if previous else CostAssumptions()
            costs.purchase_cost = quote.purchase_cost
            costs.shipping_cost = quote.shipping_cost
            costs.supplier_evidence = f"人工报价 {quote.source}/{quote.quote_id} @ {quote.quoted_at.isoformat()}；SKU={quote.sku}；{confirmation.identity_note}；未独立核实"[:1000]
            conn.execute("INSERT INTO cost_assumptions VALUES (?,?,?) ON CONFLICT(item_id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",(item_id,costs.model_dump_json(),stamp()))
            conn.execute("INSERT OR REPLACE INTO opportunity_quote_links VALUES (?,?,?,?,?)",(item_id,quote_id,confirmation.identity_note,stamp(),costs.model_dump_json()))
        self.service.rescore_all()
        return {"saved":True,"note":"报价已人工关联并写入原成本假设；未知费用仍需补充，MOQ不等于单次采购授权"}

    def configure_experiment(self, item_id, config):
        with self.repository.transaction() as conn:
            if not conn.execute("SELECT 1 FROM experiments WHERE item_id=?",(item_id,)).fetchone():
                raise ValueError("请先纳入候选池")
            previous = conn.execute("SELECT start_date FROM opportunity_experiment_settings WHERE item_id=?",(item_id,)).fetchone()
            if previous and previous[0] != config.start_date.isoformat() and conn.execute("SELECT 1 FROM opportunity_experiment_entries WHERE item_id=?",(item_id,)).fetchone():
                raise ValueError("已有经营记录，不可改变实验窗口")
            conn.execute("INSERT INTO opportunity_experiment_settings VALUES (?,?,?,?) ON CONFLICT(item_id) DO UPDATE SET start_date=excluded.start_date,stop_reason=excluded.stop_reason,updated_at=excluded.updated_at",
                         (item_id,config.start_date.isoformat(),config.stop_reason,stamp()))
            conn.execute("UPDATE experiments SET status=? WHERE item_id=?",(config.status,item_id))
        return {"saved":True}

    def record_entry(self, item_id, entry):
        with self.repository.transaction() as conn:
            config = conn.execute("SELECT start_date FROM opportunity_experiment_settings WHERE item_id=?",(item_id,)).fetchone()
            if not config:
                raise ValueError("请先设置七天实验")
            start = date.fromisoformat(config[0])
            if not start <= entry.day <= start+timedelta(days=6):
                raise ValueError("记录必须处于所选七天窗口")
            conn.execute("INSERT INTO opportunity_experiment_entries VALUES (?,?,?,?) ON CONFLICT(item_id,day) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at",
                         (item_id,entry.day.isoformat(),entry.model_dump_json(),stamp()))
        return {"saved":True, "profit":realized_profit(entry)}

    def dossier(self, item_id):
        with sqlite_connection(self.repository.db_path) as conn:
            item_row = conn.execute("SELECT payload_json FROM opportunity_items WHERE id=?",(item_id,)).fetchone()
            if not item_row:
                raise LookupError("商品不存在")
            item = OpportunityItem.model_validate_json(item_row[0])
            link = conn.execute("SELECT l.*,q.payload_json AS quote_json FROM opportunity_quote_links l JOIN opportunity_supplier_quotes q ON q.id=l.quote_id WHERE l.item_id=?",(item_id,)).fetchone()
            costs_row = conn.execute("SELECT payload_json FROM cost_assumptions WHERE item_id=?",(item_id,)).fetchone()
            costs = CostAssumptions.model_validate_json(costs_row[0]) if costs_row else CostAssumptions()
            linked = None
            if link:
                quote = SupplierQuote.model_validate_json(link["quote_json"])
                applied = CostAssumptions.model_validate_json(link["applied_costs_json"])
                linked = {"quote_id":link["quote_id"],"quote":quote.model_dump(mode="json"),"confirmation_note":link["confirmation_note"],"linked_at":link["linked_at"],
                    "current_costs_match_quote":all(getattr(costs,k)==getattr(applied,k) for k in ("purchase_cost","shipping_cost","supplier_evidence")),
                    "minimum_purchase_outlay":str(quote.purchase_cost*quote.moq) if quote.purchase_cost is not None and quote.moq is not None else None}
            config = conn.execute("SELECT s.*,e.status FROM opportunity_experiment_settings s JOIN experiments e ON e.item_id=s.item_id WHERE s.item_id=?",(item_id,)).fetchone()
            entries = [ExperimentEntry.model_validate_json(r[0]) for r in conn.execute("SELECT payload_json FROM opportunity_experiment_entries WHERE item_id=? ORDER BY day LIMIT 7",(item_id,))]
        review = experiment_review(date.fromisoformat(config["start_date"]),config["status"],entries,config["stop_reason"]) if config else None
        if review and any(word in item.title for word in BLOCK_WORDS):
            review["decision"] = "stop"
            review["reasons"].append("疑似不可售/侵权商品，经营净收益不能解除风险否决")
        return {"item_id":item_id,"currency":item.currency,"is_demo":item.source=="synthetic_demo","linked_quote":linked,
                "config":dict(config) if config else None,
                "entries":[{"data":e.model_dump(mode="json"),"profit":realized_profit(e)} for e in entries],
                "review":review}

    def export_ledger(self, item_id):
        data = self.dossier(item_id)
        fields = list(ExperimentEntry.model_fields) + ["currency","net_profit","net_margin"]
        return safe_csv(fields, [[e["data"][k] for k in ExperimentEntry.model_fields]+[data["currency"],e["profit"]["net_profit"],e["profit"]["net_margin"]] for e in data["entries"]])
