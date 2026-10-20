import csv
import io
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import opportunities
from src.app import auth_status, logout
from src.domain.models.opportunity import CategoryConfig, DiscoveryRequest
from src.infrastructure.config.settings import settings
from src.infrastructure.persistence.opportunity_repository import OpportunityRepository
from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.opportunity_service import OpportunityService


@pytest.fixture
def context(tmp_path):
    path = str(tmp_path / "app.sqlite3")
    repo = OpportunityRepository(path)
    service = OpportunityService(repo)
    app = FastAPI()
    app.include_router(opportunities.router)
    app.post("/auth/status")(auth_status)
    app.post("/auth/logout")(logout)
    app.dependency_overrides[opportunities.get_service] = lambda: service
    return service, TestClient(app), path


def csv_text(*rows):
    fields = sorted(set().union(*(r.keys() for r in rows)))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader(); writer.writerows(rows)
    return out.getvalue()


def row(number="1", **changes):
    return dict(source="fixture", source_item_id=number, title="机械键盘 87键 白色", price="90", category="电脑外设",
        observed_at="2026-01-02T00:00:00Z", want_count="20", source_confidence="0.8") | changes


def login(client):
    response = client.post("/auth/status", json={"username": settings.web_username, "password": settings.web_password})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]


def test_demo_csv_sqlite_scoring_api_closed_loop_and_replay(context):
    service, client, path = context
    login(client)
    imported = client.post("/api/opportunities/demo").json()
    assert (imported["inserted"], imported["duplicates"], imported["rejected"]) == (40, 1, 1)
    assert client.post("/api/opportunities/demo").json()["new_snapshots"] == 0
    result = client.get("/api/opportunities", params={"limit": 100}).json()
    assert result["total"] == 40
    assert len(result["items"]) == 40
    scores = [i["score"]["score_total"] for i in result["items"]]
    assert scores == sorted(scores, reverse=True)
    assert all(i["score"]["is_demo"] and i["score"]["confidence_score"] <= 20 for i in result["items"])
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunity_observations").fetchone()[0] == 40
        assert conn.execute("SELECT COUNT(*) FROM opportunity_scores").fetchone()[0] == 160
        init_schema(conn); init_schema(conn)
    assert OpportunityService(OpportunityRepository(path)).repository.ranking()["total"] == 40


def test_auth_login_cookie_basic_and_tampered_cookie(context):
    _, client, _ = context
    assert client.get("/api/opportunities").status_code == 401
    assert "www-authenticate" not in client.get("/api/opportunities").headers
    assert client.post("/api/opportunities/demo").status_code == 401
    assert client.get("/api/opportunities", auth=(settings.web_username, settings.web_password)).status_code == 200
    client.cookies.set("opportunity_session", "9999999999.forged", path="/api/opportunities")
    assert client.get("/api/opportunities").status_code == 401
    client.cookies.clear()
    login(client)
    assert client.get("/api/opportunities").status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/api/opportunities").status_code == 401


def test_identity_not_title_dedupe_and_first_observation_not_listing(context):
    service, _, path = context
    report = service.import_csv(csv_text(row(), row("2", title="机械键盘 87键 黑色"), row()))
    assert report["inserted"] == 2 and report["new_snapshots"] == 2
    detail = service.repository.detail(1, "physical")
    assert detail["baseline_only"] and detail["listing_created_at"] is None
    assert detail["suspected_duplicates"][0]["id"] == 2
    service.import_csv(csv_text(row(observed_at="2026-01-01T00:00:00Z", price="80")))
    detail = service.repository.detail(1, "physical")
    assert detail["first_observed_at"].startswith("2026-01-01")
    assert detail["observed_at"].startswith("2026-01-02") and detail["price"] == "90"
    assert detail["observation_count"] == 2
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0] == 0


def test_csv_anomaly_lines_audited_without_zero_filling(context):
    service, _, path = context
    report = service.import_csv(csv_text(row(price="", want_count=""), row("2", price="-1"), row("3", price="NaN"), row("4", raw_metadata="invalid")))
    assert report["accepted"] == 1 and report["rejected"] == 3
    assert [r["line"] for r in report["errors"]] == [3, 4, 5]
    detail = service.repository.detail(1, "physical")
    assert detail["price"] is None and detail["want_count"] is None
    assert detail["score"]["profit"]["net_margin"] is None
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT rejected FROM opportunity_imports").fetchone()[0] == 3


@pytest.mark.parametrize("content", ["title\nabc", 'source,source_item_id,title,observed_at\nx,1,"unterminated', "source,source,source_item_id,title,observed_at\nx,x,1,a,b"])
def test_bad_csv_headers_and_syntax(context, content):
    _, client, _ = context
    login(client)
    assert client.post("/api/opportunities/import", json={"content": content}).status_code == 400


def test_limits_invalid_sort_and_modes(context):
    _, client, _ = context
    login(client)
    for params in ({"page": 0}, {"limit": 101}, {"sort": "DROP TABLE tasks"}, {"strategy": "other"}, {"min_confidence": "nan"}, {"min_margin": "nan"}):
        assert client.get("/api/opportunities", params=params).status_code == 422
    oversized = csv_text(*(row(str(i)) for i in range(1001)))
    assert client.post("/api/opportunities/import", json={"content": oversized}).status_code == 400
    assert client.post("/api/opportunities/discovery", json={"budget": 51}).status_code == 422


def test_strategy_filters_pagination_cost_edit_candidate_and_export(context):
    service, client, _ = context
    login(client)
    client.post("/api/opportunities/demo")
    scores = {}
    for mode in ("physical", "virtual", "resale", "blue_ocean"):
        page = client.get("/api/opportunities", params={"strategy": mode, "limit": 3, "page": 2}).json()
        assert len(page["items"]) == 3
        detail = client.get("/api/opportunities/1", params={"strategy": mode}).json()
        scores[mode] = detail["score"]["score_total"]
    assert len(set(scores.values())) >= 3
    assert client.get("/api/opportunities", params={"source_scope": "imported"}).json()["total"] == 0
    assert client.get("/api/opportunities", params={"min_confidence": 21}).json()["total"] == 0
    physical = client.get("/api/opportunities", params={"category": "数码家电", "q": "键盘"}).json()
    assert physical["total"] == 10
    assert client.get("/api/opportunities", params={"min_margin": 0, "limit": 100}).json()["total"] == 35
    c = dict(expected_sale_price="100", purchase_cost="20", shipping_cost="0", platform_fee="0", fulfillment_cost="0", expected_loss="0")
    assert client.put("/api/opportunities/1/costs", json=c).status_code == 200
    detail = client.get("/api/opportunities/1").json()
    assert detail["score"]["profit"]["net_profit"] == 80
    assert client.post("/api/opportunities/1/candidate", json={"strategy": "physical"}).status_code == 200
    assert client.post("/api/opportunities/1/candidate", json={"strategy": "resale"}).status_code == 200
    assert client.get("/api/opportunities/1").json()["experiment_status"] == "candidate"
    assert client.get("/api/opportunities/99999").status_code == 404
    assert client.put("/api/opportunities/99999/costs", json=c).status_code == 404
    exported = client.get("/api/opportunities/export", params={"q": "键盘"})
    assert exported.status_code == 200 and "text/csv" in exported.headers["content-type"]
    assert len(list(csv.DictReader(io.StringIO(exported.text.lstrip("\ufeff"))))) == 10


def test_configurable_categories_keywords_queue_and_custom_weights(context):
    service, client, _ = context
    login(client)
    category = {"name": "户外照明", "parent": "兴趣运动", "keywords": ["露营灯"]}
    assert client.put("/api/opportunities/categories", json=category).status_code == 200
    service.import_csv(csv_text(row(category="未分类", title="露营灯 USB便携")))
    assert service.repository.detail(1, "physical")["category"] == "户外照明"
    expanded = client.post("/api/opportunities/keywords/expand").json()
    assert expanded["added"] > 0
    assert client.post("/api/opportunities/keywords/expand").json()["added"] == 0
    keywords = client.get("/api/opportunities/keywords").json()
    assert any("observed_title:item:1" in k["origin"] for k in keywords)
    queue = client.post("/api/opportunities/discovery", json={"budget": 10}).json()
    assert len(queue["jobs"]) == 10 and queue["external_calls"] == 0
    assert sum(j["lane"] == "breadth" for j in queue["jobs"]) == 4
    assert all(j["status"] == "pending_manual" for j in queue["jobs"])
    for _ in range(6):
        result = service.queue(DiscoveryRequest(budget=50))
    assert len(result["jobs"]) <= 200
    assert client.put("/api/opportunities/categories", json={"name": "坏类目", "parent": "不存在"}).status_code == 400
    weights = dict(demand=100, profit=0, competition=0, fulfillment=0, risk=0, differentiation=0)
    assert client.post("/api/opportunities/score", json={"strategy": "physical", "weights": weights}).status_code == 200
    # A later ranking refresh preserves configured weights.
    detail = client.get("/api/opportunities/1").json()
    assert detail["score"]["score_total"] == detail["score"]["dimensions"]["demand"]["score"]


def test_existing_monitor_and_price_snapshot_adapter_no_network(context):
    service, client, path = context
    with sqlite_connection(path) as conn:
        conn.execute("""INSERT INTO result_items(result_filename,keyword,task_name,crawl_time,price,item_id,title,link_unique_key,is_recommended,keyword_hit_count,raw_json)
            VALUES ('test.jsonl','键盘','test','2026-01-01T08:00:00',80,'123','机械键盘','item:123',0,0,'{}')""")
        conn.execute("""INSERT INTO price_snapshots(keyword_slug,keyword,task_name,snapshot_time,snapshot_day,run_id,item_id,title,price,tags_json)
            VALUES ('keyboard','键盘','test','2026-01-02T08:00:00','2026-01-02','run1','123','机械键盘',75,'[]')""")
        conn.commit()
    login(client)
    assert client.post("/api/opportunities/import-existing").json()["inserted"] == 1
    detail = client.get("/api/opportunities/1").json()
    assert detail["source"] == "goofish" and detail["price"] == "75.0"
    assert detail["observation_count"] == 2
    assert detail["listing_created_at"] is None and detail["seller_id"] is None
    assert client.post("/api/opportunities/import-existing").json()["new_snapshots"] == 0


def test_csv_formula_export_and_cross_source_currency_isolation(context):
    service, client, _ = context
    service.import_csv(csv_text(row(title="=HYPERLINK(1)"), row("2", source="synthetic_demo", price="999"), row("3", currency="USD", price="2")))
    detail = service.repository.detail(1, "physical")
    assert detail["score"]["market"]["sample_count"] == 1
    login(client)
    export = client.get("/api/opportunities/export").text
    assert "'=HYPERLINK(1)" in export


def test_replaying_csv_preserves_manual_cost_edits(context):
    service, client, _ = context
    content = csv_text(row(expected_sale_price="200", purchase_cost="100"))
    service.import_csv(content)
    login(client)
    assert client.put("/api/opportunities/1/costs", json={"purchase_cost": "90"}).status_code == 200
    assert service.import_csv(content)["new_snapshots"] == 0
    assert service.repository.detail(1, "physical")["costs"]["purchase_cost"] == "90"


def test_nonfinite_metadata_is_rejected_without_partial_storage(context):
    service, _, path = context
    result = service.import_csv(csv_text(row(raw_metadata='{"bad":NaN}')))
    assert result["rejected"] == 1
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunity_items").fetchone()[0] == 0
