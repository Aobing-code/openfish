"""Web监控面板"""
from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

import logging
logger = logging.getLogger("openfish.web")

router = APIRouter()

# 静态文件目录
STATIC_DIR = Path(__file__).parent.parent.parent / "static"


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """监控面板首页"""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>OpenFish</h1><p>Dashboard not found</p>")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_alt():
    """监控面板（备用路径）"""
    return await dashboard()
