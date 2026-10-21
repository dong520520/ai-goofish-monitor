import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import accounts


@pytest.fixture()
def account_client(tmp_path, monkeypatch):
    monkeypatch.setattr(accounts, "_state_dir", lambda: str(tmp_path))
    app = FastAPI()
    app.include_router(accounts.router)
    with TestClient(app) as client:
        yield client, tmp_path


def snapshot(domain=".goofish.com"):
    # Synthetic credential, never used for network requests.
    return {"cookies": [{"name": "synthetic_session", "value": "synthetic-only-secret", "domain": domain, "path": "/"}], "origins": []}


@pytest.mark.parametrize("content", ["not-json", "[]", "{}", '{"cookies": []}', '{"cookies": "wrong"}', '{"cookies": [null]}'])
def test_reject_invalid_account_before_writing(account_client, content):
    client, folder = account_client
    response = client.post("/api/accounts", json={"name": "test", "content": content})
    assert response.status_code == 400
    assert not (folder / "test.json").exists()


@pytest.mark.parametrize("enhanced", [False, True])
def test_accept_standard_and_extension_states_without_returning_cookies(account_client, enhanced):
    client, _ = account_client
    data = snapshot()
    if enhanced:
        data.update(env={}, headers={}, page={}, storage={})
    response = client.post("/api/accounts", json={"name": "test", "content": json.dumps(data)})
    assert response.status_code == 200
    listed = client.get("/api/accounts")
    assert listed.json()[0]["state_status"] == "unchecked"
    assert "synthetic-only-secret" not in response.text + listed.text


@pytest.mark.parametrize("domain", ["notgoofish.com", ".goofish.com.example.org", "example.com"])
def test_reject_other_site_cookies_without_echoing_values(account_client, domain):
    client, _ = account_client
    response = client.post("/api/accounts", json={"name": "test", "content": json.dumps(snapshot(domain))})
    assert response.status_code == 400
    assert "synthetic-only-secret" not in response.text


def test_failed_update_preserves_existing_state(account_client):
    client, folder = account_client
    content = json.dumps(snapshot())
    client.post("/api/accounts", json={"name": "test", "content": content})
    response = client.put("/api/accounts/test", json={"content": '{"cookies": []}'})
    assert response.status_code == 400
    assert (folder / "test.json").read_text(encoding="utf-8") == content


def test_list_reports_legacy_empty_and_corrupt_files_without_changing_them(account_client):
    client, folder = account_client
    (folder / "empty.json").write_text('{"cookies": []}', encoding="utf-8")
    (folder / "corrupt.json").write_bytes(b"\xff")
    listed = client.get("/api/accounts").json()
    assert len(listed) == 2
    assert all(row["state_status"] == "invalid" for row in listed)
    assert any("www.goofish.com" in row["state_message"] for row in listed)
    assert (folder / "empty.json").read_text(encoding="utf-8") == '{"cookies": []}'
    assert (folder / "corrupt.json").read_bytes() == b"\xff"
