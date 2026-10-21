import csv
import io

import pytest

from tests.integration.test_api_opportunities import context, csv_text, login, row
from src.domain.models.opportunity_business import SupplierQuote
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


BASE = "/api/opportunities/suppliers/template"


def read(response):
    assert response.status_code == 200
    return list(csv.DictReader(io.StringIO(response.text.lstrip("\ufeff"))))


def test_blank_template_has_headers_only_and_keeps_demo_contract(context):
    _, client, _ = context
    login(client)
    response = client.get(BASE, params={"kind": "blank"})
    assert response.text.startswith("\ufeff")
    assert read(response) == []
    assert next(csv.reader(io.StringIO(response.text.lstrip("\ufeff")))) == list(SupplierQuote.model_fields)
    assert read(client.get(BASE))[0]["source"] == "synthetic_demo"


def test_candidate_template_preserves_known_identity_but_leaves_quote_unknown(context):
    service, client, path = context
    service.import_csv(csv_text(row(title="合成同款引用", price="99", condition="新",
        raw_metadata='{"model":"M1","sku":"S1","specification":"87键"}')))
    login(client)
    with sqlite_connection(path) as conn:
        before = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in
                  ("opportunity_items", "opportunity_supplier_quotes", "opportunity_imports", "cost_assumptions")}
    data = read(client.get(BASE, params={"kind": "blank", "item_id": 1}))[0]
    assert {k: data[k] for k in ("product", "currency", "condition", "model", "sku", "specification")} == {
        "product": "合成同款引用", "currency": "CNY", "condition": "新", "model": "M1", "sku": "S1", "specification": "87键"}
    assert all(data[k] == "" for k in ("source", "quote_id", "supplier", "quoted_at", "purchase_cost",
               "shipping_cost", "lead_days", "moq", "source_confidence", "evidence_note", "verification_note"))
    with sqlite_connection(path) as conn:
        assert before == {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in before}
    # Filling real quote inputs uses the existing importer without extra columns.
    data.update(source="synthetic_fixture", quote_id="q1", supplier="合成供货方", quoted_at="2026-01-01T00:00:00Z",
                purchase_cost="0", shipping_cost="0", evidence_note="synthetic quote only")
    result = client.post("/api/opportunities/suppliers/import", json={"content": csv_text(data)}).json()
    assert result["accepted"] == 1 and result["rejected"] == 0


def test_template_escapes_formulas_without_inventing_identity(context):
    service, client, _ = context
    service.import_csv(csv_text(row(title="=HYPERLINK(1)",raw_metadata='{"model":["ambiguous"],"sku":false}')))
    login(client)
    data = read(client.get(BASE, params={"kind": "blank", "item_id": 1}))[0]
    assert data["product"] == "'=HYPERLINK(1)"
    assert all(data[k] == "" for k in ("model", "sku", "specification", "condition"))


@pytest.mark.parametrize("params,code", [({"kind":"blank","item_id":999},404),
    ({"kind":"blank","item_id":0},422), ({"kind":"other"},422), ({"item_id":1},400)])
def test_template_rejects_invalid_requests(context, params, code):
    _, client, _ = context
    login(client)
    assert client.get(BASE, params=params).status_code == code


def test_inquiry_template_requires_existing_login(context):
    _, client, _ = context
    assert client.get(BASE, params={"kind":"blank"}).status_code == 401
