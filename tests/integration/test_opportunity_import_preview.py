"""Synthetic fixtures only: preview must leave the original SQLite state intact."""
import csv
import io
import sqlite3

import pytest

from tests.integration.test_api_opportunities import context, csv_text, login, row
from src.domain.models.opportunity import CategoryConfig, CostAssumptions
from src.infrastructure.persistence.sqlite_connection import sqlite_connection

BASE = "/api/opportunities"


def database_state(path):
    with sqlite_connection(path) as conn:
        return list(conn.iterdump())


def test_preview_simulates_real_import_without_persisting_rows_costs_or_audit(context):
    service,client,path = context
    service.import_csv(csv_text(row()))
    service.update_costs(1,CostAssumptions(expected_sale_price="100",purchase_cost="20",shipping_cost="0",platform_fee="0",fulfillment_cost="0",expected_loss="0"))
    content = csv_text(row(),row("2",price="0",want_count="0"),row("2",price="0",want_count="0"),
                       row(price="80",observed_at="2026-01-01T00:00:00Z",purchase_cost="99"),row("3",price="-1"))
    login(client)
    before = database_state(path)
    first = client.post(BASE+"/import/preview",json={"content":content})
    assert first.status_code == 200
    preview = first.json()
    assert preview["preview"]
    assert (preview["accepted"],preview["inserted"],preview["new_snapshots"],preview["rejected"]) == (4,1,2,1)
    assert preview["older_observations"] == 1
    assert preview["source_counts"] == {"fixture":4}
    assert preview["unknown_profit_rows"] == 2
    assert preview["sample"][1]["price"] == "0"
    assert "price" not in preview["missing_counts"]
    assert client.post(BASE+"/import/preview",json={"content":content}).json() == preview
    assert database_state(path) == before
    imported = client.post(BASE+"/import",json={"content":content}).json()
    for field in ("accepted","inserted","new_snapshots","duplicates","rejected","errors"):
        assert imported[field] == preview[field]
    assert service.repository.detail(1,"physical")["costs"]["purchase_cost"] == "20"


def test_preview_capacity_matches_import_and_does_not_reserve_slots(context,monkeypatch):
    service,client,path = context
    from src.services import opportunity_service
    monkeypatch.setattr(opportunity_service,"MAX_ITEMS",1)
    content = csv_text(row(),row("2"),row())
    login(client)
    before = database_state(path)
    preview = client.post(BASE+"/import/preview",json={"content":content}).json()
    assert (preview["accepted"],preview["inserted"],preview["rejected"]) == (2,1,1)
    assert database_state(path) == before
    actual = service.import_csv(content)
    assert actual["inserted"] == preview["inserted"]
    assert actual["errors"] == preview["errors"]


@pytest.mark.parametrize("path,method,payload",[("/import/preview","post",{"content":"x"}),("/import/template","get",None)])
def test_preview_and_template_require_original_auth(context,path,method,payload):
    _,client,_ = context
    assert getattr(client,method)(BASE+path,**({"json":payload} if payload else {})).status_code == 401


def test_header_only_templates_are_importable_and_never_create_fake_items(context):
    service,client,path = context
    login(client)
    before = database_state(path)
    for kind in ("basic","costs"):
        response = client.get(BASE+"/import/template",params={"kind":kind})
        assert response.status_code == 200 and "text/csv" in response.headers["content-type"]
        reader = csv.DictReader(io.StringIO(response.text.lstrip("\ufeff")))
        assert {"source","source_item_id","title","observed_at"}.issubset(reader.fieldnames)
        assert list(reader) == []
        assert ("purchase_cost" in reader.fieldnames) == (kind == "costs")
        preview = service.import_csv(response.text,preview=True)
        assert preview["accepted"] == preview["inserted"] == preview["total_rows"] == 0
    assert database_state(path) == before
    assert client.get(BASE+"/import/template",params={"kind":"unknown"}).status_code == 422


def test_preview_reports_missing_and_zero_differently_with_bounded_samples(context):
    service,_,path = context
    content = csv_text(row(price="",want_count=""),*(row(str(i),price="0",want_count="0",currency="USD") for i in range(2,23)))
    before = database_state(path)
    report = service.import_csv(content,preview=True)
    assert report["missing_counts"]["price"] == report["missing_counts"]["want_count"] == 1
    assert report["currency_counts"] == {"CNY":1,"USD":21}
    assert report["accepted"] == 22 and len(report["sample"]) == 20 and report["sample_truncated"]
    assert report["unknown_profit_rows"] == 22
    assert database_state(path) == before


@pytest.mark.parametrize("content",["source,title\na,b",'source,source_item_id,title,observed_at\nx,1,"unclosed',
                                   "source,source,source_item_id,title,observed_at\nx,x,1,t,t"])
def test_preview_rejects_invalid_structure(context,content):
    _,client,path = context
    login(client)
    before = database_state(path)
    assert client.post(BASE+"/import/preview",json={"content":content}).status_code == 400
    assert database_state(path) == before


def test_preview_size_row_bounds_and_invalid_metadata(context):
    service,client,path = context
    login(client)
    before = database_state(path)
    assert client.post(BASE+"/import/preview",json={"content":"x"*2_000_001}).status_code == 422
    assert client.post(BASE+"/import/preview",json={"content":csv_text(*(row(str(i)) for i in range(1001)))}).status_code == 400
    report = service.import_csv(csv_text(row(raw_metadata='{"value":NaN}')),preview=True)
    assert report["accepted"] == 0 and report["rejected"] == 1
    assert database_state(path) == before


def test_unexpected_preview_storage_failure_rolls_back_earlier_rows(context):
    service,_,path = context
    with sqlite_connection(path) as conn:
        conn.execute("CREATE TRIGGER synthetic_fail_preview BEFORE INSERT ON opportunity_items WHEN NEW.source_item_id='2' BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        conn.commit()
    before = database_state(path)
    with pytest.raises(sqlite3.IntegrityError):
        service.import_csv(csv_text(row(),row("2")),preview=True)
    assert database_state(path) == before


def test_normalized_classification_and_search_match_research_keywords(context):
    service,client,_ = context
    service.repository.save_category(CategoryConfig(name="USB外设",keywords=["usb 键盘"]))
    content = csv_text(row(title="ＵＳＢ   键盘87键",category="未分类"))
    preview = service.import_csv(content,preview=True)
    assert preview["category_counts"] == {"USB外设":1}
    service.import_csv(content)
    login(client)
    result = client.get(BASE,params={"q":"USB 键盘","category":"USB外设"}).json()
    assert result["total"] == 1


def test_candidate_pool_filters_status_pagination_export_and_demo_isolation(context):
    service,client,path = context
    service.import_csv(csv_text(*(row(str(i)) for i in range(1,5)),row("5",source="synthetic_demo")))
    for i in range(1,6):
        service.candidate(i,"physical")
    with sqlite_connection(path) as conn:
        for identifier,status in ((2,"running"),(3,"completed"),(4,"stopped")):
            conn.execute("UPDATE experiments SET status=? WHERE item_id=?",(status,identifier))
        conn.commit()
    login(client)
    assert client.get(BASE,params={"pool":"candidates"}).json()["total"] == 5
    assert client.get(BASE,params={"pool":"candidates","source_scope":"imported"}).json()["total"] == 4
    assert client.get(BASE,params={"pool":"candidate"}).json()["total"] == 2
    for status,identifier in (("running",2),("completed",3),("stopped",4)):
        result = client.get(BASE,params={"pool":status,"limit":1}).json()
        assert result["total"] == 1 and result["items"][0]["id"] == identifier
    exported = client.get(BASE+"/export",params={"pool":"stopped","source_scope":"imported"})
    exported_rows = list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))
    assert len(exported_rows) == 1
    assert exported_rows[0]["experiment_status"] == "stopped"
    assert client.get(BASE,params={"pool":"not_a_status"}).status_code == 422
    assert client.get(BASE+"/export",params={"pool":"not_a_status"}).status_code == 422
