import asyncio
import json

import pytest

from tests.integration.test_api_opportunities import context, csv_text, row, login
from src.domain.models.opportunity import CostAssumptions
from src.infrastructure.persistence.sqlite_connection import init_schema, sqlite_connection
from src.services.opportunity_sync_service import OpportunitySyncService, adapt_monitor_row


def result_record(path, item_id="101", stamp="2026-01-02T08:00:00", price=90, raw=None):
    if raw is None:
        raw = {"商品信息": {"“想要”人数": "20", "浏览量": "80"}, "卖家信息": {"卖家ID": "77", "卖家昵称": "not-an-id"}, "cookie": "do-not-copy"}
    with sqlite_connection(path) as conn:
        cursor = conn.execute("""INSERT INTO result_items(result_filename,keyword,task_name,crawl_time,price,item_id,title,link_unique_key,is_recommended,keyword_hit_count,raw_json)
            VALUES ('sync.jsonl','键盘','fixture',?,?,?,'机械键盘',?,0,0,?)""",(stamp,price,item_id,"item:"+item_id,json.dumps(raw)))
        conn.commit()
        return cursor.lastrowid


def price_record(path, item_id="101", stamp="2026-01-03T08:00:00", price=80, run="1", metadata=None):
    with sqlite_connection(path) as conn:
        cursor = conn.execute("""INSERT INTO price_snapshots(keyword_slug,keyword,task_name,snapshot_time,snapshot_day,run_id,item_id,title,price,tags_json,opportunity_metadata_json)
            VALUES ('keyboard','键盘','fixture',?,'2026-01-03',?,?,'机械键盘',?,'[]',?)""",(stamp,run,item_id,price,json.dumps(metadata or {})))
        conn.commit()
        return cursor.lastrowid


def test_bounded_incremental_sync_uses_both_original_tables_and_replays(context):
    service, client, path = context
    result_record(path)
    price_record(path, metadata={"“想要”人数": "25", "浏览量": "120"})
    sync = OpportunitySyncService(service.repository)
    result = sync.run_batch()
    assert (result["processed"],result["inserted"],result["new_snapshots"]) == (2,1,2)
    detail = service.repository.detail(1,"physical")
    assert detail["category"] == "电脑外设" and detail["price"] == "80.0"
    assert detail["want_count"] == 25 and detail["view_count"] == 120
    assert detail["listing_created_at"] is None
    assert detail["first_observed_at"].startswith("2026-01-02")
    assert sync.run_batch()["processed"] == 0
    assert sync.status()["pending"] == {"result_items":0,"price_snapshots":0}
    assert sync.status()["external_calls"] == 0
    assert all("cookie" not in p["data"]["raw_metadata"] for p in detail["observations"])
    login(client)
    history = client.get("/api/opportunities/1/history").json()
    assert history["distinct_times"] == 2 and history["sales_count"] is None
    assert history["points"][1]["changes"] == {"price":-10,"want_count":5,"view_count":40}


def test_old_rows_and_sparse_snapshots_never_replace_unknowns_with_stale_counts(context):
    service, _, path = context
    result_record(path)
    price_record(path, stamp="2026-01-01T08:00:00", price=100)
    sync = OpportunitySyncService(service.repository)
    sync.run_batch()
    service.update_costs(1,CostAssumptions(purchase_cost="55"))
    assert service.repository.detail(1,"physical")["price"] == "90.0"
    price_record(path, stamp="2026-01-04T08:00:00", price=70,run="2")
    sync.run_batch()
    detail = service.repository.detail(1,"physical")
    assert detail["want_count"] is None and detail["view_count"] is None
    assert detail["costs"]["purchase_cost"] == "55"
    history = service.repository.history(1)
    assert history["points"][-1]["changes"]["want_count"] is None
    assert history["points"][-1]["price"] == "70.0"


def test_per_table_limits_do_not_starve_snapshots(context):
    service, _, path = context
    for i in range(5):
        result_record(path,item_id=str(101+i))
        price_record(path,item_id=str(201+i))
    sync = OpportunitySyncService(service.repository)
    assert sync.run_batch(limit=2)["processed"] == 4
    assert sync.status()["pending"] == {"result_items":3,"price_snapshots":3}
    assert sync.run_batch(limit=2)["processed"] == 4
    assert sync.run_batch(limit=2)["processed"] == 2
    with pytest.raises(ValueError):sync.run_batch(limit=101)


def test_rejected_records_are_audited_and_cursor_continues(context):
    service, _, path = context
    result_record(path,item_id="unknown")
    result_record(path,item_id="102",raw={"商品信息":[],"卖家信息":{"卖家昵称":"77"}})
    result_record(path,item_id="103",stamp="2099-01-01T00:00:00Z")
    result_record(path,item_id="104",raw={"商品信息":{"“想要”人数":"NaN"},"卖家信息":{"卖家昵称":"77"}})
    sync = OpportunitySyncService(service.repository)
    result = sync.run_batch()
    assert result["processed"] == 4 and result["rejected"] == 3
    assert sync.status()["rejected_count"] == 3
    assert sync.status()["cursors"]["result_items"] == 4
    assert service.repository.sellers()["total"] == 0


def test_pause_and_resume_persist_across_instances(context):
    service, client, path = context
    result_record(path)
    login(client)
    assert client.put("/api/opportunities/sync",json={"enabled":False}).json()["enabled"] is False
    assert OpportunitySyncService(service.repository).run_batch()["paused"]
    assert client.post("/api/opportunities/sync/run").json()["processed"] == 0
    assert client.put("/api/opportunities/sync",json={"enabled":True}).status_code == 200
    assert client.post("/api/opportunities/sync/run").json()["processed"] == 1


def test_unexpected_write_failure_rolls_back_and_requires_manual_resume(context,monkeypatch):
    service, _, path = context
    result_record(path)
    sync = OpportunitySyncService(service.repository)
    original = service.repository.upsert
    monkeypatch.setattr(service.repository,"upsert",lambda *args: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    with pytest.raises(RuntimeError):sync.run_batch()
    assert sync.status()["enabled"] is False and sync.status()["cursors"]["result_items"] == 0
    assert service.repository.ranking()["total"] == 0
    monkeypatch.setattr(service.repository,"upsert",original)
    sync.configure(True)
    assert sync.run_batch()["inserted"] == 1


def test_scoring_failure_keeps_dirty_marker_and_resume_repairs_scores(context,monkeypatch):
    from src.services.opportunity_service import OpportunityService
    service, _, path = context
    result_record(path)
    sync = OpportunitySyncService(service.repository)
    original = OpportunityService.rescore_all
    monkeypatch.setattr(OpportunityService,"rescore_all",lambda *args: (_ for _ in ()).throw(RuntimeError("fixture scoring failure")))
    with pytest.raises(RuntimeError):sync.run_batch()
    assert sync.status()["enabled"] is False and sync.status()["cursors"]["result_items"] == 1
    monkeypatch.setattr(OpportunityService,"rescore_all",original)
    sync.configure(True)
    assert sync.run_batch()["processed"] == 0
    assert service.repository.ranking()["total"] == 1


def test_capacity_pauses_without_dropping_unprocessed_row(context,monkeypatch):
    import src.services.opportunity_sync_service as sync_module
    service, _, path = context
    result_record(path,item_id="101");result_record(path,item_id="102")
    monkeypatch.setattr(sync_module,"MAX_ITEMS",1)
    sync = OpportunitySyncService(service.repository)
    assert sync.run_batch()["paused"]
    assert sync.status()["cursors"]["result_items"] == 1
    assert sync.status()["pending"]["result_items"] == 1
    monkeypatch.setattr(sync_module,"MAX_ITEMS",2)
    sync.configure(True)
    assert sync.run_batch()["inserted"] == 1


def test_original_price_writer_keeps_only_whitelisted_observation_fields(context,monkeypatch):
    from src.services.price_history_service import record_market_snapshots
    service, _, path = context
    monkeypatch.setenv("APP_DATABASE_FILE",path)
    record_market_snapshots(keyword="键盘",task_name="fixture",run_id="run-1",snapshot_time="2026-01-01T08:00:00+08:00",
        items=[{"商品ID":"101","商品标题":"机械键盘","当前售价":"¥88","“想要”人数":7,"浏览量":30,"cookie":"do-not-copy"}])
    sync = OpportunitySyncService(service.repository)
    assert sync.run_batch()["inserted"] == 1
    detail = service.repository.detail(1,"physical")
    assert detail["want_count"] == 7 and detail["view_count"] == 30
    with sqlite_connection(path) as conn:
        assert "cookie" not in conn.execute("SELECT opportunity_metadata_json FROM price_snapshots").fetchone()[0]


def test_schema_upgrade_preserves_old_price_rows_and_runs_twice(context):
    _, _, path = context
    price_record(path)
    with sqlite_connection(path) as conn:
        conn.execute("ALTER TABLE price_snapshots DROP COLUMN opportunity_metadata_json")
        init_schema(conn);init_schema(conn)
        row = conn.execute("SELECT price,opportunity_metadata_json FROM price_snapshots").fetchone()
        assert row[0] == 80 and row[1] == "{}"


def test_demo_timeline_is_idempotent_and_counter_drop_is_not_sales(context):
    service, client, _ = context
    login(client)
    client.post("/api/opportunities/demo")
    assert client.post("/api/opportunities/demo-history").json()["new_snapshots"] == 80
    assert client.post("/api/opportunities/demo-history").json()["new_snapshots"] == 0
    history = client.get("/api/opportunities/1/history").json()
    assert history["distinct_times"] == 3 and history["price_delta"] == -18
    assert history["sales_count"] is None and not history["baseline_only"]
    dropped = client.get("/api/opportunities/10/history").json()["points"][-1]
    assert dropped["changes"]["want_count"] < 0
    assert any("计数下降" in w for w in dropped["warnings"])
    assert client.get("/api/opportunities/9999/history").status_code == 404
    assert client.get("/api/opportunities/1/history?limit=501").status_code == 422


def test_same_instant_revisions_and_late_arrivals_do_not_create_false_trend(context):
    service, _, _ = context
    service.import_csv(csv_text(row(price="90"),row(price="80")))
    history = service.repository.history(1)
    assert history["baseline_only"] and history["distinct_times"] == 1
    assert history["points"][0]["revision_count"] == 2 and history["price_delta"] is None
    service.import_csv(csv_text(row(price="100",observed_at="2026-01-01T00:00:00Z")))
    history = service.repository.history(1)
    assert history["points"][1]["changes"]["price"] == -20
    assert service.repository.history(1,limit=1)["truncated"]


def test_sellers_are_historical_stable_id_associations_and_watches_are_local(context):
    service, client, path = context
    result_record(path)
    price_record(path)
    OpportunitySyncService(service.repository).run_batch()
    # Latest sparse price row has no seller ID; prior explicit association remains traceable.
    assert service.repository.detail(1,"physical")["seller_id"] is None
    login(client)
    sellers = client.get("/api/opportunities/sellers").json()
    assert sellers["total"] == 1 and sellers["items"][0]["seller_id"] == "77"
    assert sellers["items"][0]["observed_items"] == 1
    assert client.put("/api/opportunities/sellers/goofish/77/watch",json={"watching":True}).status_code == 200
    assert client.get("/api/opportunities/sellers?watching_only=true").json()["total"] == 1
    assert client.get("/api/opportunities/sellers/goofish/77").json()["items"][0]["id"] == 1
    assert client.put("/api/opportunities/sellers/goofish/unknown/watch",json={"watching":True}).status_code == 404
    assert client.put("/api/opportunities/sellers/goofish/77/watch",json={"watching":False}).status_code == 200
    assert client.get("/api/opportunities/sellers?watching_only=true").json()["total"] == 0


def test_seller_source_isolation_and_api_auth(context):
    service, client, _ = context
    service.import_csv(csv_text(row(seller_id="77"),row("2",source="synthetic_demo",seller_id="77")))
    assert client.get("/api/opportunities/sync").status_code == 401
    assert client.get("/api/opportunities/sellers").status_code == 401
    login(client)
    assert client.get("/api/opportunities/sellers").json()["total"] == 2
    assert client.get("/api/opportunities/sellers?source_scope=demo").json()["total"] == 1
    assert client.get("/api/opportunities/sellers?source_scope=imported").json()["total"] == 1
    assert client.get("/api/opportunities/sellers?limit=101").status_code == 422


def test_scheduler_registers_sync_after_every_task_reload(monkeypatch):
    from src.services.scheduler_service import SchedulerService
    from types import SimpleNamespace
    calls = []
    class FakeScheduler:
        def __init__(self):self.jobs = {}
        def get_jobs(self):return list(self.jobs.values())
        def get_job(self,job_id):return self.jobs.get(job_id)
        def remove_job(self,job_id):self.jobs.pop(job_id)
        def add_job(self,*args,**kwargs):
            calls.append((args,kwargs))
            self.jobs[kwargs["id"]] = SimpleNamespace(id=kwargs["id"])
    scheduler = SchedulerService(object())
    scheduler.scheduler = FakeScheduler()
    asyncio.run(scheduler.reload_jobs([]));asyncio.run(scheduler.reload_jobs([]))
    assert len(calls) == 1 and calls[0][1]["id"] == "opportunity_local_sync"
    assert calls[0][1]["seconds"] == 60 and calls[0][1]["max_instances"] == 1
    invoked = []
    monkeypatch.setattr(OpportunitySyncService,"run_batch",lambda _:invoked.append(True))
    asyncio.run(scheduler._sync_opportunity_records())
    assert invoked == [True]
