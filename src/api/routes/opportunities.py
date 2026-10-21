"""Bounded offline opportunity APIs, using the existing Web login."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.opportunity_auth import require_opportunity_auth
from src.domain.models.opportunity import CategoryConfig, CostAssumptions, DiscoveryRequest, ScoreRequest, Strategy
from src.domain.models.opportunity_business import QuoteConfirmation, ExperimentConfig, ExperimentEntry
from src.services.opportunity_service import OpportunityService, export_csv, import_template

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"], dependencies=[Depends(require_opportunity_auth)])


def get_service():
    return OpportunityService()


class CSVImport(BaseModel):
    content: str = Field(max_length=2_000_000)


class SyncConfig(BaseModel):
    enabled: bool


class SellerWatch(BaseModel):
    watching: bool = True
    note: str = Field("",max_length=1000)


def get_sync_service(service=Depends(get_service)):
    from src.services.opportunity_sync_service import OpportunitySyncService
    return OpportunitySyncService(service.repository)


@router.get("/sync")
def sync_status(sync=Depends(get_sync_service)):
    return sync.status()


@router.put("/sync")
def configure_sync(payload: SyncConfig, sync=Depends(get_sync_service)):
    return sync.configure(payload.enabled)


@router.post("/sync/run")
def run_sync(sync=Depends(get_sync_service)):
    try:
        return sync.run_batch()
    except Exception as exc:
        raise HTTPException(503,"本地同步异常，已暂停；请检查状态后恢复") from exc


@router.get("/sellers")
def sellers(source_scope: Literal["all","demo","imported"]="all", page: int=Query(1,ge=1,le=10000),
            limit: int=Query(20,ge=1,le=100), watching_only: bool=False, service=Depends(get_service)):
    return service.repository.sellers(source_scope=source_scope,page=page,limit=limit,watching_only=watching_only)


@router.get("/sellers/{source}/{seller_id}")
def seller_items(source: str, seller_id: str, page: int=Query(1,ge=1,le=10000), limit: int=Query(20,ge=1,le=100), service=Depends(get_service)):
    return service.repository.seller_items(source,seller_id,page=page,limit=limit)


@router.put("/sellers/{source}/{seller_id}/watch")
def watch_seller(source: str, seller_id: str, payload: SellerWatch, service=Depends(get_service)):
    if not service.repository.watch_seller(source,seller_id,payload.watching,payload.note):
        raise HTTPException(404,"没有该卖家的可信ID观测")
    return {"saved":True}


def filters(strategy: Strategy = "physical", category: str = Query("", max_length=100), q: str = Query("", max_length=200),
            min_confidence: float = Query(0, ge=0, le=100, allow_inf_nan=False),
            min_margin: float | None = Query(None, ge=-1000000, le=100, allow_inf_nan=False),
            source_scope: Literal["all", "demo", "imported"] = "all",
            pool: Literal["all","candidates","candidate","running","completed","stopped"] = "all",
            sort: Literal["score_total", "confidence_score", "net_margin", "observed_at"] = "score_total"):
    return dict(strategy=strategy, category=category, q=q, min_confidence=min_confidence, min_margin=min_margin, source_scope=source_scope, sort=sort, pool=pool)


@router.get("")
def ranking(options: dict = Depends(filters), page: int = Query(1, ge=1, le=10000), limit: int = Query(20, ge=1, le=100), service=Depends(get_service)):
    service.rescore_all(options["strategy"])
    return service.repository.ranking(**options, page=page, limit=limit)


@router.post("/import")
def import_csv(payload: CSVImport, service=Depends(get_service)):
    try:
        return service.import_csv(payload.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/import/preview")
def preview_import(payload: CSVImport, service=Depends(get_service)):
    try:
        return service.import_csv(payload.content,preview=True)
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


@router.get("/import/template")
def download_import_template(kind: Literal["basic","costs"]="basic"):
    return Response(import_template(kind),media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition":f'attachment; filename="opportunity-{kind}-template.csv"'})


@router.post("/demo")
def demo(service=Depends(get_service)):
    return service.demo()


@router.post("/demo-history")
def history_demo(service=Depends(get_service)):
    from pathlib import Path
    content = (Path(__file__).resolve().parents[2]/"resources"/"opportunity_history_demo.csv").read_text(encoding="utf-8-sig")
    return service.import_csv(content,origin="synthetic_history_demo")


@router.post("/import-existing")
def import_existing(limit: int = Query(500, ge=1, le=1000), service=Depends(get_service)):
    return service.import_existing(limit)


@router.post("/score")
def score(payload: ScoreRequest, service=Depends(get_service)):
    return service.rescore_all(payload.strategy, payload.weights)


@router.get("/imports")
def imports(service=Depends(get_service)):
    return service.imports()


@router.get("/categories")
def categories(service=Depends(get_service)):
    return service.repository.categories()


@router.put("/categories")
def save_category(payload: CategoryConfig, service=Depends(get_service)):
    try:
        service.repository.save_category(payload)
        return service.repository.categories()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/keywords")
def keywords(service=Depends(get_service)):
    return service.keywords()


@router.post("/keywords/expand")
def expand(service=Depends(get_service)):
    return service.expand_keywords()


@router.get("/discovery")
def queue(service=Depends(get_service)):
    return service.queue()


@router.post("/discovery")
def plan_queue(payload: DiscoveryRequest, service=Depends(get_service)):
    return service.queue(payload)


@router.get("/export")
def export(options: dict = Depends(filters), service=Depends(get_service)):
    service.rescore_all(options["strategy"])
    result = service.repository.ranking(**options, limit=10000)
    return Response(export_csv(result), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="opportunities.csv"'})


def research_filters(category: str = Query("", max_length=100), keyword: str = Query("", max_length=200),
                     source_scope: Literal["imported", "demo", "all"] = "imported"):
    return dict(category=category, keyword=keyword, source_scope=source_scope)


@router.get("/research")
def research(options: dict = Depends(research_filters), limit: int = Query(100, ge=1, le=100), service=Depends(get_service)):
    from src.services.opportunity_research_service import OpportunityResearchService
    return OpportunityResearchService(service.repository).evidence(**options, limit=limit)


@router.get("/research/export")
def research_export(options: dict = Depends(research_filters), service=Depends(get_service)):
    from src.services.opportunity_research_service import OpportunityResearchService
    return Response(OpportunityResearchService(service.repository).export(**options), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="market-evidence.csv"'})


def get_business_service(service=Depends(get_service)):
    from src.services.opportunity_business_service import OpportunityBusinessService
    return OpportunityBusinessService(service)


def business_action(action):
    try:
        return action()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/suppliers/import")
def supplier_import(payload: CSVImport, business=Depends(get_business_service)):
    return business_action(lambda: business.import_quotes(payload.content))


@router.get("/suppliers/template")
def supplier_template(kind: Literal["demo","blank"]="demo", item_id: int | None=Query(None,ge=1),
                      business=Depends(get_business_service)):
    if kind == "blank":
        content = business_action(lambda: business.quote_template(item_id))
        filename = f"supplier-inquiry-item-{item_id}.csv" if item_id is not None else "blank-supplier-template.csv"
        return Response(content,media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition":f'attachment; filename="{filename}"'})
    if item_id is not None:
        raise HTTPException(400,"候选询价模板请使用 kind=blank")
    from pathlib import Path
    content = (Path(__file__).resolve().parents[2]/"resources"/"opportunity_supplier_demo.csv").read_text(encoding="utf-8")
    return Response("\ufeff"+content, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="synthetic-supplier-example.csv"'})


@router.get("/suppliers")
def supplier_quotes(source_scope: Literal["imported","demo","all"]="imported", page: int=Query(1,ge=1,le=10000),
                    limit: int=Query(50,ge=1,le=100), business=Depends(get_business_service)):
    return business.quotes(source_scope=source_scope,page=page,limit=limit)


@router.get("/{item_id}/business")
def business_dossier(item_id: int, business=Depends(get_business_service)):
    return business_action(lambda: business.dossier(item_id))


@router.put("/{item_id}/supplier/{quote_id}")
def confirm_supplier(item_id: int, quote_id: int, payload: QuoteConfirmation, business=Depends(get_business_service)):
    return business_action(lambda: business.link_quote(item_id,quote_id,payload))


@router.put("/{item_id}/experiment")
def configure_experiment(item_id: int, payload: ExperimentConfig, business=Depends(get_business_service)):
    return business_action(lambda: business.configure_experiment(item_id,payload))


@router.put("/{item_id}/experiment/entry")
def record_experiment(item_id: int, payload: ExperimentEntry, business=Depends(get_business_service)):
    return business_action(lambda: business.record_entry(item_id,payload))


@router.get("/{item_id}/experiment/export")
def export_experiment(item_id: int, business=Depends(get_business_service)):
    content = business_action(lambda: business.export_ledger(item_id))
    return Response(content, media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="experiment.csv"'})


@router.get("/{item_id}")
def detail(item_id: int, strategy: Strategy = "physical", service=Depends(get_service)):
    service.rescore_all(strategy)
    item = service.repository.detail(item_id, strategy)
    if item is None:
        raise HTTPException(404, "商品不存在")
    return item


@router.get("/{item_id}/history")
def history(item_id: int, limit: int=Query(100,ge=1,le=500), service=Depends(get_service)):
    result = service.repository.history(item_id,limit)
    if result is None:
        raise HTTPException(404,"商品不存在")
    return result


@router.put("/{item_id}/costs")
def costs(item_id: int, payload: CostAssumptions, service=Depends(get_service)):
    if not service.update_costs(item_id, payload):
        raise HTTPException(404, "商品不存在")
    return {"saved": True}


@router.post("/{item_id}/candidate")
def candidate(item_id: int, payload: ScoreRequest, service=Depends(get_service)):
    if not service.candidate(item_id, payload.strategy):
        raise HTTPException(404, "商品不存在")
    return {"saved": True, "status": "candidate", "note": "候选待人工验证，未购买或发布"}
