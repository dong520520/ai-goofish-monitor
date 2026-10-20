"""Use existing WEB credentials; add an HttpOnly login cookie for new radar APIs."""
import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, Response
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from src.infrastructure.config.settings import settings

COOKIE_NAME = "opportunity_session"
SESSION_SECONDS = 8 * 60 * 60
_SIGNING_KEY = secrets.token_bytes(32)
_basic = HTTPBasic(auto_error=False)


def _signature(expiry):
    # Configuration changes invalidate existing cookies too.
    content = f"{expiry}:{settings.web_username}:{settings.web_password}".encode()
    return hmac.new(_SIGNING_KEY, content, hashlib.sha256).hexdigest()


def set_login_cookie(response: Response, request: Request):
    expiry = str(int(time.time())+SESSION_SECONDS)
    response.set_cookie(COOKIE_NAME, expiry+"."+_signature(expiry), max_age=SESSION_SECONDS,
                        httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/api/opportunities")


def require_opportunity_auth(request: Request, credentials: HTTPBasicCredentials | None = Depends(_basic)):
    if credentials is not None and hmac.compare_digest(credentials.username.encode(), settings.web_username.encode()) and hmac.compare_digest(credentials.password.encode(), settings.web_password.encode()):
        return
    token = request.cookies.get(COOKIE_NAME, "")
    try:
        expiry, signature = token.split(".", 1)
        if int(time.time()) < int(expiry) <= int(time.time())+SESSION_SECONDS and hmac.compare_digest(signature, _signature(expiry)):
            return
    except (ValueError, TypeError):
        pass
    # No Basic challenge: browsers would pause fetch behind a native password
    # prompt instead of letting the existing Vue login handle the 401.
    raise HTTPException(status_code=401, detail="请使用现有 Web 账号重新登录")
