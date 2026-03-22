"""Web监控面板"""
import hashlib
import secrets
import time
from pathlib import Path
from typing import Dict
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel

import logging
logger = logging.getLogger("openfish.web")

router = APIRouter()

# Session存储 {token: expire_time}
sessions: Dict[str, float] = {}

# Session过期时间（秒）
SESSION_EXPIRE = 86400  # 24小时


def get_static_dir() -> Path:
    """获取静态文件目录"""
    possible_paths = [
        Path("/app/static"),
        Path(__file__).parent.parent.parent / "static",
        Path.cwd() / "static",
    ]
    for p in possible_paths:
        if p.exists() and (p / "index.html").exists():
            return p
    return possible_paths[0]


def get_app():
    from app import main as app_main
    return app_main


def verify_session(token: str) -> bool:
    """验证session是否有效"""
    if not token:
        return False
    expire = sessions.get(token)
    if not expire:
        return False
    if time.time() > expire:
        sessions.pop(token, None)
        return False
    return True


def get_session_token(request: Request) -> str:
    """从请求中获取session token"""
    # 从cookie获取
    token = request.cookies.get("openfish_session")
    if token:
        return token
    # 从header获取
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Session "):
        return auth[8:]
    return ""


class LoginRequest(BaseModel):
    password: str


@router.get("/login", response_class=HTMLResponse)
async def login_page():
    """登录页面"""
    static_dir = get_static_dir()
    login_file = static_dir / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    return HTMLResponse("<h1>Login page not found</h1>")


@router.post("/api/login")
async def login(body: LoginRequest):
    """登录API"""
    app = get_app()
    
    # 验证密码（使用第一个API key作为管理员密码）
    valid_keys = app.config.auth.api_keys if app.config.auth.enabled else ["sk-openfish"]
    
    if body.password in valid_keys:
        # 生成session token
        token = secrets.token_hex(32)
        sessions[token] = time.time() + SESSION_EXPIRE
        
        response = JSONResponse({"status": "ok", "message": "登录成功"})
        response.set_cookie(
            key="openfish_session",
            value=token,
            max_age=SESSION_EXPIRE,
            httponly=True,
            samesite="lax"
        )
        return response
    
    raise HTTPException(status_code=401, detail="密码错误")


@router.post("/api/logout")
async def logout(request: Request):
    """登出API"""
    token = get_session_token(request)
    if token:
        sessions.pop(token, None)
    
    response = JSONResponse({"status": "ok", "message": "已登出"})
    response.delete_cookie("openfish_session")
    return response


@router.get("/api/session/check")
async def check_session(request: Request):
    """检查session状态"""
    token = get_session_token(request)
    if verify_session(token):
        return {"authenticated": True}
    return {"authenticated": False}


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """监控面板首页"""
    app = get_app()
    
    # 如果启用了认证，检查session
    if app.config.auth.enabled:
        token = get_session_token(request)
        if not verify_session(token):
            # 重定向到登录页
            static_dir = get_static_dir()
            login_file = static_dir / "login.html"
            if login_file.exists():
                return FileResponse(login_file)
    
    static_dir = get_static_dir()
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>OpenFish</h1><p>Dashboard not found</p>")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_alt(request: Request):
    """监控面板（备用路径）"""
    return await dashboard(request)
