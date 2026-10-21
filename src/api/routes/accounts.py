"""
闲鱼账号管理路由
"""
import json
import os
import re
import aiofiles
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from urllib.parse import urlsplit
from src.infrastructure.config.env_manager import env_manager


router = APIRouter(prefix="/api/accounts", tags=["accounts"])

ACCOUNT_NAME_RE = re.compile(r"^[a-zA-Z0-9_-]{1,50}$")


class AccountCreate(BaseModel):
    name: str
    content: str


class AccountUpdate(BaseModel):
    content: str


def _strip_quotes(value: str) -> str:
    if not value:
        return value
    if value.startswith(("\"", "'")) and value.endswith(("\"", "'")):
        return value[1:-1]
    return value


def _state_dir() -> str:
    raw = env_manager.get_value("ACCOUNT_STATE_DIR", "state") or "state"
    return _strip_quotes(raw.strip())


def _ensure_state_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _validate_name(name: str) -> str:
    trimmed = name.strip()
    if not trimmed or not ACCOUNT_NAME_RE.match(trimmed):
        raise HTTPException(status_code=400, detail="账号名称只能包含字母、数字、下划线或短横线。")
    return trimmed


def _account_path(name: str) -> str:
    filename = f"{name}.json"
    return os.path.join(_state_dir(), filename)


def _validate_json(content: str) -> None:
    try:
        snapshot = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="提供的内容不是有效的JSON格式。")
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=400, detail="登录态必须是扩展导出的 JSON 对象。")
    cookies = snapshot.get("cookies")
    if not isinstance(cookies, list) or not cookies:
        raise HTTPException(status_code=400, detail="登录态没有 Cookie。请在已登录的 www.goofish.com 标签页重新提取，再更新账号；不要在本项目页面提取。")
    has_goofish_cookie = False
    for cookie in cookies:
        if not isinstance(cookie, dict) or not isinstance(cookie.get("name"), str) or not isinstance(cookie.get("value"), str):
            raise HTTPException(status_code=400, detail="Cookie 格式不完整，请使用登录态提取扩展重新导出。")
        domain = str(cookie.get("domain") or "").lstrip(".").lower()
        if not domain:
            try:
                domain = urlsplit(str(cookie.get("url") or "")).hostname or ""
            except ValueError:
                domain = ""
        if cookie["name"] and cookie["value"] and (domain == "goofish.com" or domain.endswith(".goofish.com")):
            has_goofish_cookie = True
    if not has_goofish_cookie:
        raise HTTPException(status_code=400, detail="没有找到闲鱼站点的 Cookie。请确认在已登录的 www.goofish.com 标签页提取。")


async def _state_status(path: str) -> dict:
    """Offline structure check only; never return credential contents or probe the site."""
    try:
        async with aiofiles.open(path, "r", encoding="utf-8") as handle:
            _validate_json(await handle.read())
    except HTTPException as exc:
        return {"state_status": "invalid", "state_message": exc.detail}
    except (OSError, UnicodeError):
        return {"state_status": "invalid", "state_message": "登录态文件无法读取，请重新导入。"}
    return {"state_status": "unchecked", "state_message": "登录态格式检查通过；是否仍有效，需首次运行验证。"}


@router.get("", response_model=List[dict])
async def list_accounts():
    state_dir = _state_dir()
    if not os.path.isdir(state_dir):
        return []
    files = [f for f in os.listdir(state_dir) if f.endswith(".json")]
    accounts = []
    for filename in sorted(files):
        name = filename[:-5]
        accounts.append({
            "name": name,
            "path": os.path.join(state_dir, filename),
            **await _state_status(os.path.join(state_dir, filename)),
        })
    return accounts


@router.get("/{name}", response_model=dict)
async def get_account(name: str):
    account_name = _validate_name(name)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    async with aiofiles.open(path, "r", encoding="utf-8") as f:
        content = await f.read()
    return {"name": account_name, "path": path, "content": content}


@router.post("", response_model=dict)
async def create_account(data: AccountCreate):
    account_name = _validate_name(data.name)
    _validate_json(data.content)
    state_dir = _state_dir()
    _ensure_state_dir(state_dir)
    path = _account_path(account_name)
    if os.path.exists(path):
        raise HTTPException(status_code=409, detail="账号已存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(data.content)
    return {"message": "账号已添加", "name": account_name, "path": path}


@router.put("/{name}", response_model=dict)
async def update_account(name: str, data: AccountUpdate):
    account_name = _validate_name(name)
    _validate_json(data.content)
    state_dir = _state_dir()
    _ensure_state_dir(state_dir)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    async with aiofiles.open(path, "w", encoding="utf-8") as f:
        await f.write(data.content)
    return {"message": "账号已更新", "name": account_name, "path": path}


@router.delete("/{name}", response_model=dict)
async def delete_account(name: str):
    account_name = _validate_name(name)
    path = _account_path(account_name)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="账号不存在")
    os.remove(path)
    return {"message": "账号已删除"}
