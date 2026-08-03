"""OAuth 后端框架：Gitee 完整接入 + GitHub/Google 占位 + session + 用户表。

路由前缀 /api/auth，挂载到 main.py 的 app。
- GET  /api/auth/login/gitee    生成 state + 跳转 Gitee 授权页
- GET  /api/auth/callback/gitee 校验 state + 换 token + 拉用户信息 + 发 session cookie
- GET  /api/auth/me             返回 {logged_in, user, privileges}
- POST /api/auth/logout         清 session cookie
- GET  /api/auth/login/github   占位 501
- GET  /api/auth/login/google   占位 501

session：自实现 HMAC 签名 cookie（不引入 itsdangerous 新依赖），payload={user_id, provider, exp}。
users 表：放 sentiment.db 主库（复用 get_conn + WAL），CREATE TABLE IF NOT EXISTS 广等。

⚠️ 生产架构注意：
CF Workers (worker/headers.js) 拦截 /api/* -> subscribeHandler，不回源 FastAPI。
本模块仅在本地 uvicorn 开发环境（localhost:8000）生效。生产 ss.fx8.store/api/auth/* 会
走 Workers subscribeHandler 返回 subscribe 路由 404。生产上线需二选一：
  ① Workers 实现 OAuth（worker/auth.js + Web Crypto 签名 cookie + KV session + users 表迁 KV/D1）
  ② 配 origin（Workers 对 /api/auth/* 回源到常驻 FastAPI 部署，如 Railway/Fly.io/自家 Mac port-forward）
详见回报 + NOTES。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Cookie, HTTPException, Query, Response
from fastapi.responses import RedirectResponse

from .db import get_conn

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---- 环境变量（client_secret 不写死，从环境变量读）----
GITEE_CLIENT_ID = os.environ.get("GITEE_CLIENT_ID", "")
GITEE_CLIENT_SECRET = os.environ.get("GITEE_CLIENT_SECRET", "")
GITEE_REDIRECT_URI = os.environ.get("GITEE_REDIRECT_URI", "")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")

# ---- cookie / session 参数 ----
SESSION_COOKIE_NAME = "session"
STATE_COOKIE_NAME = "oauth_state"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 天
STATE_MAX_AGE = 5 * 60  # 5 分钟（OAuth state 短期）

# ---- users 表 schema ----
USERS_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  provider_uid TEXT NOT NULL,
  name TEXT,
  avatar TEXT,
  email TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_login_at TEXT,
  UNIQUE(provider, provider_uid)
);
"""

_users_table_ensured = False


def _ensure_users_table() -> None:
    """幂等建 users 表（首次调用建，后续跳过）。复用 get_conn 的 WAL + row_factory。"""
    global _users_table_ensured
    if _users_table_ensured:
        return
    conn = get_conn()
    try:
        conn.executescript(USERS_SCHEMA)
        conn.commit()
    finally:
        conn.close()
    _users_table_ensured = True


# ---- session 签名（HMAC-SHA256 自实现，不引入 itsdangerous）----
def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def sign_session(payload: dict) -> str:
    """签名 cookie：base64(payload).base64(hmac_sha256(payload))。"""
    if not SESSION_SECRET:
        raise RuntimeError("SESSION_SECRET 未配置（环境变量为空）")
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    sig = hmac.new(SESSION_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64(sig)}"


def verify_session(token: str) -> Optional[dict]:
    """校验签名 + exp。失败返回 None（调用方按未登录处理）。"""
    if not token or not SESSION_SECRET or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    expected = hmac.new(SESSION_SECRET.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    try:
        actual = _unb64(sig)
    except Exception:
        return None
    if not hmac.compare_digest(expected, actual):
        return None
    try:
        payload = json.loads(_unb64(body))
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    return payload


def _set_session_cookie(resp: Response, token: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(resp: Response) -> None:
    resp.delete_cookie(SESSION_COOKIE_NAME, path="/")


# ============ 路由 ============

@router.get("/login/gitee")
def login_gitee():
    """跳转 Gitee 授权页。state 存 cookie，回调校验防 CSRF。"""
    if not GITEE_CLIENT_ID:
        raise HTTPException(status_code=503, detail="Gitee OAuth 未配置（GITEE_CLIENT_ID 环境变量为空）")
    if not GITEE_REDIRECT_URI:
        raise HTTPException(status_code=503, detail="GITEE_REDIRECT_URI 未配置")
    state = secrets.token_urlsafe(16)
    login_url = (
        "https://gitee.com/oauth/authorize"
        f"?client_id={GITEE_CLIENT_ID}"
        f"&redirect_uri={GITEE_REDIRECT_URI}"
        "&response_type=code"
        f"&state={state}"
        "&scope=user_info"
    )
    resp = RedirectResponse(login_url)
    resp.set_cookie(
        STATE_COOKIE_NAME,
        state,
        max_age=STATE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return resp


@router.get("/callback/gitee")
def callback_gitee(
    code: str = Query(...),
    state: str = Query(...),
    oauth_state: Optional[str] = Cookie(None),
):
    """Gitee 回调：校验 state -> 换 token -> 拉用户信息 -> upsert users -> 发 session cookie -> 回首页。"""
    if not GITEE_CLIENT_ID or not GITEE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Gitee OAuth 未配置")
    if not oauth_state or oauth_state != state:
        raise HTTPException(
            status_code=400,
            detail="state 校验失败（可能跨站请求伪造或 state cookie 过期）",
        )
    # token 交换
    with httpx.Client(timeout=10.0) as c:
        tok_resp = c.post(
            "https://gitee.com/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": GITEE_CLIENT_ID,
                "client_secret": GITEE_CLIENT_SECRET,
                "redirect_uri": GITEE_REDIRECT_URI,
            },
            headers={"Accept": "application/json"},
        )
        if tok_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"换 access_token 失败: {tok_resp.status_code} {tok_resp.text}")
        access_token = tok_resp.json().get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="Gitee 未返回 access_token")
        # 拉用户信息
        user_resp = c.get(
            "https://gitee.com/api/v5/user",
            params={"access_token": access_token},
        )
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"拉 Gitee 用户信息失败: {user_resp.status_code}")
        u = user_resp.json()
    provider_uid = str(u.get("id") or "")
    if not provider_uid:
        raise HTTPException(status_code=400, detail="Gitee 用户信息缺 id 字段")
    name = u.get("name") or u.get("login") or ""
    avatar = u.get("avatar_url") or ""
    email = u.get("email") or ""
    # upsert users 表
    _ensure_users_table()
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE provider=? AND provider_uid=?",
            ("gitee", provider_uid),
        ).fetchone()
        now = datetime.now().isoformat(timespec="seconds")
        if row:
            user_id = row["id"]
            conn.execute(
                "UPDATE users SET name=?, avatar=?, email=?, last_login_at=? WHERE id=?",
                (name, avatar, email, now, user_id),
            )
        else:
            cur = conn.execute(
                "INSERT INTO users (provider, provider_uid, name, avatar, email, last_login_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("gitee", provider_uid, name, avatar, email, now),
            )
            user_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    # 发 session cookie + 回首页
    payload = {
        "user_id": user_id,
        "provider": "gitee",
        "exp": int(time.time()) + SESSION_MAX_AGE,
    }
    token = sign_session(payload)
    resp = RedirectResponse("/")
    _set_session_cookie(resp, token)
    resp.delete_cookie(STATE_COOKIE_NAME, path="/")
    return resp


@router.get("/me")
def me(session: Optional[str] = Cookie(None)):
    """返回登录状态 + 用户信息 + privileges。
    MVP: logged_in 即给 detailed_view 特权；其他特权（模拟回测/订阅/对比）预留接口字段。
    """
    _ensure_users_table()  # 无条件建表（幂等，首次建后续跳过），避免无 session 时表缺失
    if not session:
        return {"logged_in": False, "user": None, "privileges": []}
    payload = verify_session(session)
    if not payload:
        # cookie 无效/过期，清掉
        resp = Response(
            content='{"logged_in": false, "user": null, "privileges": []}',
            media_type="application/json",
        )
        _clear_session_cookie(resp)
        return resp
    user_id = payload.get("user_id")
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT name, avatar, provider FROM users WHERE id=?",
            (user_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"logged_in": False, "user": None, "privileges": []}
    return {
        "logged_in": True,
        "user": {
            "name": row["name"],
            "avatar": row["avatar"],
            "provider": row["provider"],
        },
        "privileges": ["detailed_view"],
    }


@router.post("/logout")
def logout():
    """清 session cookie。"""
    resp = Response(content='{"logged_out": true}', media_type="application/json")
    _clear_session_cookie(resp)
    return resp


@router.get("/login/github")
def login_github():
    """占位：GitHub 登录即将支持。"""
    raise HTTPException(status_code=501, detail="github 登录即将支持")


@router.get("/login/google")
def login_google():
    """占位：Google 登录即将支持。"""
    raise HTTPException(status_code=501, detail="google 登录即将支持")
