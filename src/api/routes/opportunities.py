"""Bounded offline opportunity APIs, using the existing Web login."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from src.api.opportunity_auth import require_opportunity_auth
from src.domain.models.opportunity import CategoryConfig, CostAssumptions, DiscoveryRequest, ScoreRequest, Strategy
from src.services.opportunity_service import OpportunityService, export_csv

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"], dependencies=[Depends(require_opportunity_auth)])


def get_service():
    return OpportunityService()


class CSVImport(BaseModel):
    content: str = Field(max_length=2_000_000)


def filters(strategy: Strategy = "physical", category: str = Query("", max_length=100), q: str = Query("", max_length=200),
            min_confidence: float = Query(0, ge=0, le=100, allow_inf_nan=False),
            min_margin: float | None = Query(None, ge=-1000000, le=100, allow_inf_nan=False),
            source_scope: Literal["all", "demo", "imported"] = "all",
            sort: Literal["score_total", "confidence_score", "net_margin", "observed_at"] = "score_total"):
    return dict(strategy=strategy, category=category, q=q, min_confidence=min_confidence, min_margin=min_margin, source_scope=source_scope, sort=sort)


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


@router.post("/demo")
def demo(service=Depends(get_service)):
    return service.demo()


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


@router.get("/{item_id}")
def detail(item_id: int, strategy: Strategy = "physical", service=Depends(get_service)):
    service.rescore_all(strategy)
    item = service.repository.detail(item_id, strategy)
    if item is None:
        raise HTTPException(404, "商品不存在")
    return item


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
