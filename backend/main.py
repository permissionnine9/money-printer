"""
FastAPI 主应用入口
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from backend.api.v1 import sessions, steps, segments, frames, materials, uploads, assets, models, prompts
from backend.config import override_src_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    print("FastAPI 应用启动")

    # 打印实际生效的模型配置（模型管理默认配置 > 系统内置常量）
    override_src_config()

    yield
    # 关闭时清理
    print("FastAPI 应用关闭")


app = FastAPI(
    title="AI视频创作智能体 API",
    description="基于LangGraph的视频生成工作流",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # React 开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")

# 注册路由
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["会话管理"])
app.include_router(steps.router, prefix="/api/v1/steps", tags=["工作流步骤"])
app.include_router(segments.router, prefix="/api/v1/segments", tags=["分片编辑"])
app.include_router(frames.router, prefix="/api/v1/frames", tags=["首尾帧管理"])
app.include_router(materials.router, prefix="/api/v1/materials", tags=["素材图管理"])
app.include_router(uploads.router, prefix="/api/v1/uploads", tags=["文件上传"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["会话资产管理"])
app.include_router(models.router, prefix="/api/v1/models", tags=["生图模型管理"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["提示词管理"])


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "message": "AI视频创作智能体 API"}


@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
