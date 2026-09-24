"""
FastAPI 主应用入口
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from backend.api.v1 import (
    sessions,
    steps,
    uploads,
    models,
    prompts,
    script_sessions,
    agent_runs,
    settings,
    materials,
)
from backend.config import override_src_config
from backend.core.agent_sdk import get_run_registry
from backend.core.errors import WorkflowError
from backend.core.persistence.settings_manager import AGENT_CONCURRENCY_KEY
from backend.deps import get_settings_manager, get_workflow

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

    # 恢复持久化的 Agent 并发上限（未配置过则保持默认值）
    saved = get_settings_manager().get(AGENT_CONCURRENCY_KEY)
    if saved:
        get_run_registry().set_max_concurrent(int(saved))

    # 回收上次进程遗留的「生成中」悬挂状态（后台生成线程随进程死亡，不会自行恢复）
    recovered = get_workflow().recover_stale_generations()
    if recovered:
        print(f"已回收 {recovered} 个悬挂的视频生成任务（落盘为已停止）")

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
    # 5174：5173 被残留 vite 占用时新实例自动跳到 5174，需一并放行
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],  # React 开发服务器
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态文件目录
app.mount("/static", StaticFiles(directory="static"), name="static")


# 全局业务异常处理（路由层无需逐个 try/except 转 HTTPException）
@app.exception_handler(WorkflowError)
async def business_error_handler(request: Request, exc: Exception):
    """工作流业务异常 → HTTP detail（状态码由异常携带，默认 400）"""
    return JSONResponse(status_code=getattr(exc, "status_code", 400), content={"detail": str(exc)})


# 注册路由
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["会话管理"])
app.include_router(steps.router, prefix="/api/v1/steps", tags=["工作流步骤"])
app.include_router(uploads.router, prefix="/api/v1/uploads", tags=["文件上传"])
app.include_router(models.router, prefix="/api/v1/models", tags=["生图模型管理"])
app.include_router(prompts.router, prefix="/api/v1/prompts", tags=["提示词管理"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["系统设置"])
app.include_router(script_sessions.router, prefix="/api/v1/script-sessions", tags=["剧本工作流"])
app.include_router(agent_runs.router, prefix="/api/v1/agent-runs", tags=["Agent 运行"])
app.include_router(materials.router, prefix="/api/v1/materials", tags=["素材管理"])


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
