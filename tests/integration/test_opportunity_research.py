"""P2A uses synthetic local fixtures exclusively; no external traffic."""
import csv
import io

import pytest

from tests.integration.test_api_opportunities import context, csv_text, login, row
from src.domain.models.opportunity import CategoryConfig, DiscoveryRequest
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.opportunity_research_service import OpportunityResearchService


def test_cohorts_isolate_currency_source_condition_and_model(context):
    service, client, _ = context
    service.import_csv(csv_text(row(price="10", condition="新", raw_metadata='{"model":"K1"}'),
        row("2", price="20", condition="新", raw_metadata='{"model":"K1"}'),
        row("3", price="999", condition="旧", raw_metadata='{"model":"K1"}'),
        row("4", price="999", condition="新", raw_metadata='{"model":"K2"}'),
        row("5", price="999", currency="USD", condition="新", raw_metadata='{"model":"K1"}'),
        row("6", price="999", source="synthetic_demo", condition="新", raw_metadata='{"model":"K1"}')))
    login(client)
    result = client.get("/api/opportunities/research").json()
    assert len(result["cohorts"]) == 4
    cohort = next(c for c in result["cohorts"] if c["sample_count"] == 2)
    assert (cohort["p25"], cohort["p50"], cohort["p75"]) == ("12.50", "15.00", "17.50")
    assert cohort["distinct_sellers"] is None
    assert cohort["item_ids"] == [1, 2]
    assert client.get("/api/opportunities/research", params={"source_scope":"demo"}).json()["total_cohorts"] == 1


def test_unknown_zero_seller_coverage_duplicate_and_old_observation(context):
    service, _, _ = context
    data = csv_text(row(price="", want_count="", seller_id=""), row("2", price="0", want_count="0", seller_id="stable-1"))
    service.import_csv(data)
    assert service.import_csv(data)["new_snapshots"] == 0
    service.import_csv(csv_text(row("2", price="999", observed_at="2026-01-01T00:00:00Z")))
    c = OpportunityResearchService(service.repository).evidence()["cohorts"][0]
    assert c["sample_count"] == 2 and c["priced_count"] == 1
    assert c["p50"] == "0.00" and c["want_coverage"] == .5
    assert c["distinct_sellers"] == 1 and c["seller_coverage"] == .5
    # Latest snapshot missing seller does not inherit historical seller IDs.
    service.import_csv(csv_text(row("2", observed_at="2026-01-03T00:00:00Z", price="0")))
    assert OpportunityResearchService(service.repository).evidence()["cohorts"][0]["distinct_sellers"] is None


def test_category_fairness_quota_and_identical_plan_idempotence(context):
    service, _, _ = context
    service.expand_keywords()
    request = DiscoveryRequest(budget=20)
    result = service.queue(request)
    assert len(result["jobs"]) == 20
    assert len(result["category_coverage"]) >= 17  # every configured leaf before extra slots
    assert sum(j["lane"] == "breadth" for j in result["jobs"]) == 8
    assert service.queue(request)["jobs"] == result["jobs"]
    assert result["external_calls"] == 0


def test_normalized_keywords_and_seed_to_title_lineage(context):
    service, client, path = context
    for word in ("USB 键盘", "ＵＳＢ  键盘", "usb 键盘"):
        service.repository.save_category(CategoryConfig(name="电脑外设", keywords=[word]))
    with sqlite_connection(path) as conn:
        from src.infrastructure.persistence.opportunity_repository import OpportunityRepository
        for word in ("USB 键盘", "ＵＳＢ  键盘", "usb 键盘"):
            OpportunityRepository.add_keyword(conn,"电脑外设",word,"user_seed")
        assert conn.execute("SELECT COUNT(*) FROM keyword_seeds WHERE lower(keyword) LIKE '%usb%'").fetchone()[0] == 1
        conn.commit()
    service.import_csv(csv_text(row(title="USB 键盘 87键")))
    service.expand_keywords()
    login(client)
    result = client.get("/api/opportunities/research", params={"keyword":"usb 键盘"}).json()
    assert result["cohorts"][0]["item_ids"] == [1]
    assert result["lineage"][0]["matched_count"] == 1
    service.repository.save_category(CategoryConfig(name="电脑外设",keywords=["ＵＳＢ  键盘"]))
    service.import_csv(csv_text(row("2",title="ＵＳＢ   键盘 104键")))
    service.expand_keywords()
    assert any("observed_title:item:2" in k["origin"] for k in service.keywords())


def test_evidence_export_formula_safety_and_bounds(context):
    service, client, _ = context
    service.import_csv(csv_text(row(source="=SOURCE()", condition="@bad", raw_metadata='{"model":"+bad"}')))
    login(client)
    result = client.get("/api/opportunities/research/export")
    cells = next(csv.DictReader(io.StringIO(result.text.lstrip("\ufeff"))))
    assert cells["source"] == "'=SOURCE()" and cells["condition"] == "'@bad" and cells["model"] == "'+bad"
    for params in ({"limit":101}, {"source_scope":"evil"}, {"keyword":"x"*201}):
        assert client.get("/api/opportunities/research",params=params).status_code == 422


@pytest.mark.parametrize("path", ["/research", "/research/export"])
def test_research_auth(context, path):
    _, client, _ = context
    assert client.get("/api/opportunities"+path).status_code == 401


def test_risk_blockers_remain_with_custom_weights_and_demo_isolation(context):
    service, client, _ = context
    service.demo()
    service.import_csv(csv_text(row(title="盗版键盘",want_count="9999999")))
    login(client)
    for strategy in ("physical","virtual","resale","blue_ocean"):
        weights = dict(demand=100,profit=0,competition=0,fulfillment=0,risk=0,differentiation=0)
        client.post("/api/opportunities/score",json={"strategy":strategy,"weights":weights})
        item = client.get("/api/opportunities/41",params={"strategy":strategy}).json()
        assert item["score"]["recommendation"] == "blocked"
        assert item["score"]["ranking_evidence"]["why_rejected"]
        assert item["score"]["market"]["sample_count"] == 1
    assert all(c["source"] != "synthetic_demo" for c in client.get("/api/opportunities/research").json()["cohorts"])
