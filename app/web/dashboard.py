"""Web监控面板"""
from pathlib import Path
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse

import logging
logger = logging.getLogger("openfish.web")

router = APIRouter()

# 静态文件目录 - 支持Docker和本地环境
def get_static_dir() -> Path:
    """获取静态文件目录"""
    # 尝试多个可能的路径
    possible_paths = [
        Path("/app/static"),  # Docker容器内
        Path(__file__).parent.parent.parent / "static",  # 本地开发
        Path.cwd() / "static",  # 当前工作目录
    ]
    for p in possible_paths:
        if p.exists() and (p / "index.html").exists():
            return p
    return possible_paths[0]


@router.get("/", response_class=HTMLResponse)
async def dashboard():
    """监控面板首页"""
    static_dir = get_static_dir()
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return HTMLResponse("<h1>OpenFish</h1><p>Dashboard not found</p><p>Static dir: " + str(static_dir) + "</p>")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_alt():
    """监控面板（备用路径）"""
    return await dashboard()
