"""P2B synthetic fixtures: no supplier/platform requests or purchases."""
from datetime import timedelta

import pytest

from tests.integration.test_api_opportunities import context, csv_text, login, row
from src.domain.models.opportunity import CostAssumptions
from src.domain.models.opportunity_business import business_today
from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection

BASE = "/api/opportunities"


def quote(**changes):
    return dict(source="synthetic_fixture",quote_id="q1",supplier="合成供应商",product="合成键盘",sku="K1",specification="87键",condition="新",
                currency="CNY",quoted_at="2026-01-01T00:00:00Z",purchase_cost="40",shipping_cost="0",lead_days="0",moq="2",evidence_note="synthetic test only") | changes


def setup(context, **changes):
    service,client,path = context
    service.import_csv(csv_text(row(**changes)))
    login(client)
    return service,client,path


def import_quote(client, **changes):
    response = client.post(BASE+"/suppliers/import",json={"content":csv_text(quote(**changes))})
    assert response.status_code == 200
    return response.json()


def confirm(client, identifier=1):
    return client.put(BASE+f"/1/supplier/{identifier}",json={"confirmed":True,"identity_note":"人工核对型号、SKU、规格及成色一致"})


def test_quote_replay_revision_and_cost_provenance(context):
    service,client,path = setup(context,condition="新",raw_metadata='{"sku":"K1","specification":"87键"}')
    service.update_costs(1,CostAssumptions(expected_sale_price="100",platform_fee="0",fulfillment_cost="0",expected_loss="0"))
    assert import_quote(client)["inserted"] == 1
    assert import_quote(client)["inserted"] == 0
    assert confirm(client).status_code == 200
    assert client.get(BASE+"/1").json()["score"]["profit"]["net_profit"] == 60
    assert import_quote(client,purchase_cost="90")["inserted"] == 1
    dossier = client.get(BASE+"/1/business").json()
    assert dossier["linked_quote"]["quote"]["purchase_cost"] == "40"
    assert dossier["linked_quote"]["minimum_purchase_outlay"] == "80"
    assert dossier["linked_quote"]["current_costs_match_quote"]
    service.update_costs(1,CostAssumptions(purchase_cost="30"))
    assert not client.get(BASE+"/1/business").json()["linked_quote"]["current_costs_match_quote"]
    with sqlite_connection(path) as conn:
        init_schema(conn);init_schema(conn)
        assert conn.execute("SELECT COUNT(*) FROM opportunity_supplier_quotes").fetchone()[0] == 2


@pytest.mark.parametrize("changes", [{"currency":"USD"},{"sku":"other"},{"condition":"旧"},{"source":"synthetic_demo"}])
def test_quote_identity_conflicts_do_not_mutate_costs(context,changes):
    _,client,path = setup(context,condition="新",raw_metadata='{"sku":"K1"}')
    import_quote(client,**changes)
    assert confirm(client).status_code == 400
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunity_quote_links").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM cost_assumptions").fetchone()[0] == 0


def test_quote_requires_confirmation_unknown_costs_and_zero(context):
    _,client,_ = setup(context)
    import_quote(client,purchase_cost="",shipping_cost="0")
    assert client.put(BASE+"/1/supplier/1",json={"confirmed":False,"identity_note":"test note"}).status_code == 422
    assert confirm(client).status_code == 200
    item = client.get(BASE+"/1").json()
    assert item["costs"]["purchase_cost"] is None and item["costs"]["shipping_cost"] == "0"
    assert item["score"]["profit"]["net_profit"] is None
    assert confirm(client,999).status_code == 404


@pytest.mark.parametrize("changes", [{"quoted_at":"2026-01-01"},{"purchase_cost":"NaN"},{"shipping_cost":"-1"},{"moq":"0"},{"sku":""}])
def test_bad_quotes_audited_without_partial_storage(context,changes):
    _,client,path = setup(context)
    report = import_quote(client,**changes)
    assert report["rejected"] == 1
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunity_supplier_quotes").fetchone()[0] == 0
        assert conn.execute("SELECT rejected FROM opportunity_imports WHERE origin='supplier_quotes'").fetchone()[0] == 1


def test_supplier_csv_headers_sizes_and_query_bounds(context):
    _,client,_ = setup(context)
    for text in ("source,quote_id\nx,y",csv_text(*(quote(quote_id=str(i)) for i in range(1001))),"source,source\nx,x"):
        assert client.post(BASE+"/suppliers/import",json={"content":text}).status_code == 400
    assert client.get(BASE+"/suppliers",params={"limit":101}).status_code == 422
    assert client.post(BASE+"/suppliers/import",json={"content":"x"*2_000_001}).status_code == 422


def entry(day, **changes):
    return dict(day=day.isoformat(),exposure=None,inquiries=1,orders=1,refunds=0,revenue="100",refund_amount="0",purchase_cost="40",shipping_cost="5",platform_fee="0",fulfillment_cost="0",actual_loss="0",evidence_note="synthetic own-business fixture") | changes


def test_seven_day_review_profit_refunds_and_idempotence(context):
    _,client,path = setup(context)
    start = business_today()-timedelta(days=6)
    assert client.put(BASE+"/1/experiment",json={"start_date":str(start)}).status_code == 400
    client.post(BASE+"/1/candidate",json={"strategy":"physical"})
    assert client.put(BASE+"/1/experiment",json={"start_date":str(start)}).status_code == 200
    for i in range(7):
        record = entry(start+timedelta(days=i))
        assert client.put(BASE+"/1/experiment/entry",json=record).status_code == 200
    # Daily records are replaceable; replay does not add an eighth day.
    client.put(BASE+"/1/experiment/entry",json=record)
    dossier = client.get(BASE+"/1/business").json()
    assert dossier["review"]["seven_day_net"] == "385.0"
    assert dossier["review"]["decision"] == "continue"
    assert dossier["review"]["metrics"]["exposure"] is None
    assert client.put(BASE+"/1/experiment/entry",json=entry(start,refund_amount="100",refunds=1)).status_code == 200
    review = client.get(BASE+"/1/business").json()["review"]
    assert review["seven_day_net"] == "285.0" and review["decision"] == "stop"
    assert client.put(BASE+"/1/experiment",json={"start_date":str(start+timedelta(days=1))}).status_code == 400
    exported = client.get(BASE+"/1/experiment/export")
    assert len(exported.text.splitlines()) == 8
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM opportunity_experiment_entries").fetchone()[0] == 7


def test_incomplete_zero_refund_larger_than_revenue_and_window(context):
    _,client,_ = setup(context)
    start = business_today()-timedelta(days=6)
    client.post(BASE+"/1/candidate",json={})
    client.put(BASE+"/1/experiment",json={"start_date":str(start)})
    assert client.put(BASE+"/1/experiment/entry",json=entry(start,revenue="0",refund_amount="100")).json()["profit"]["net_profit"] == -145
    response = client.put(BASE+"/1/experiment/entry",json=entry(start,platform_fee=None))
    assert response.json()["profit"]["net_profit"] is None
    review = client.get(BASE+"/1/business").json()["review"]
    assert review["decision"] == "fill_evidence" and review["seven_day_net"] is None
    assert len(review["missing_days"]) == 6
    assert client.put(BASE+"/1/experiment/entry",json=entry(start-timedelta(days=1))).status_code == 400
    assert client.put(BASE+"/1/experiment/entry",json=entry(business_today()+timedelta(days=1))).status_code == 422
    assert client.put(BASE+"/1/experiment",json={"start_date":str(start),"status":"stopped"}).status_code == 422
    client.put(BASE+"/1/experiment",json={"start_date":str(start),"status":"stopped","stop_reason":"合成测试停止"})
    assert client.get(BASE+"/1/business").json()["review"]["decision"] == "stop"


def test_quote_link_transaction_rolls_back_on_storage_failure(context):
    import sqlite3
    from src.domain.models.opportunity_business import QuoteConfirmation
    from src.services.opportunity_business_service import OpportunityBusinessService
    service,client,path = setup(context)
    import_quote(client)
    with sqlite_connection(path) as conn:
        conn.execute("CREATE TRIGGER fixture_fail_link BEFORE INSERT ON opportunity_quote_links BEGIN SELECT RAISE(ABORT,'synthetic storage failure'); END")
        conn.commit()
    with pytest.raises(sqlite3.IntegrityError):
        OpportunityBusinessService(service).link_quote(1,1,QuoteConfirmation(confirmed=True,identity_note="synthetic identity confirmation"))
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM cost_assumptions").fetchone()[0] == 0


def test_hard_risk_survives_profitable_ledger_and_csv_injection(context):
    _,client,_ = setup(context,title="盗版键盘")
    client.post(BASE+"/1/candidate",json={})
    start = business_today()-timedelta(days=6)
    client.put(BASE+"/1/experiment",json={"start_date":str(start)})
    for i in range(7):
        client.put(BASE+"/1/experiment/entry",json=entry(start+timedelta(days=i),evidence_note="=HYPERLINK(1)"))
    dossier = client.get(BASE+"/1/business").json()
    assert dossier["review"]["decision"] == "stop"
    assert "风险否决" in dossier["review"]["reasons"][-1]
    assert "'=HYPERLINK(1)" in client.get(BASE+"/1/experiment/export").text


def test_monetary_refund_also_blocks_continue_when_count_is_zero(context):
    _,client,_ = setup(context)
    client.post(BASE+"/1/candidate",json={})
    start = business_today()-timedelta(days=6)
    client.put(BASE+"/1/experiment",json={"start_date":str(start)})
    for i in range(7):
        client.put(BASE+"/1/experiment/entry",json=entry(start+timedelta(days=i),refund_amount="1"))
    assert client.get(BASE+"/1/business").json()["review"]["decision"] == "stop"


@pytest.mark.parametrize("method,path,payload",[("get","/suppliers",None),("post","/suppliers/import",{"content":"x"}),
    ("get","/1/business",None),("put","/1/supplier/1",{"confirmed":True,"identity_note":"test identity"}),
    ("put","/1/experiment",{"start_date":"2026-01-01"}), ("put","/1/experiment/entry",entry(business_today())),("get","/1/experiment/export",None)])
def test_business_endpoints_require_auth(context,method,path,payload):
    _,client,_ = context
    options = {"json":payload} if payload else {}
    assert getattr(client,method)(BASE+path,**options).status_code == 401
