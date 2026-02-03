"""
工作流步骤 API
"""
import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Dict, Any

from backend.schemas.steps import (
    Step1Request,
    Step2Request,
    Step3Request,
    Step4Request,
    StepResponse,
)
from backend.deps import get_session_manager, get_workflow
from core.persistence.session_manager import SessionManager
from core.agents.workflow_v2 import VideoCreationWorkflowV2
from core.models.video_models import VideoParams

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/submit", response_model=StepResponse)
async def step_1_submit_script(
    session_id: str,
    request: Step1Request,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤1：提交脚本和参数"""
    logger.info(f"[API] 步骤1 - 提交脚本 - 会话: {session_id[:8]}...")
    logger.info(f"[API] 脚本长度: {len(request.script)} 字符")
    logger.info(f"[API] 视频参数 - resolution: {request.resolution}, aspect_ratio: {request.aspect_ratio}")
    logger.info(f"[API] 视频参数 - language: {request.language}, style: {request.style}, camera_view: {request.camera_view}")

    # 检查会话是否存在
    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 创建工作流
    workflow = get_workflow()

    # 创建视频参数字典（与 VideoParams 模型字段名保持一致）
    video_params = {
        "resolution": request.resolution,
        "aspect_ratio": request.aspect_ratio,
        "language": request.language,
        "style": request.style,
        "perspective": request.camera_view,  # 映射 camera_view -> perspective
    }

    # 执行步骤1
    logger.info(f"[API] 执行 workflow.step_submit - 会话: {session_id[:8]}...")
    result = workflow.step_submit(session_id, request.script, video_params)

    if not result.get("success"):
        logger.error(f"[API] 提交失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "提交失败"))

    logger.info(f"[API] 步骤1完成 - 脚本已提交")

    # 获取步骤结果
    result_data = session_manager.get_step_result(session_id, "submit_script_and_params")

    return StepResponse(
        success=True,
        message=result.get("message", "脚本和参数已提交"),
        data=result_data,
    )


@router.post("/{session_id}/optimize", response_model=StepResponse)
async def step_2_optimize_script(
    session_id: str,
    request: Step2Request = None,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤2：优化脚本"""
    extra_prompt = request.extra_prompt if request else None
    logger.info(f"[API] 步骤2 - 优化脚本 - 会话: {session_id[:8]}...")
    if extra_prompt:
        logger.info(f"[API] 自定义提示词: {extra_prompt[:100]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()

    # 检查前置步骤
    can_execute, reason = session_manager.can_execute_step(session_id, "optimize_script")
    if not can_execute:
        logger.error(f"[API] 前置步骤未完成: {reason}")
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤1：提交脚本")

    # 执行步骤2（异步方法）
    logger.info(f"[API] 执行 workflow.step_optimize_script - 会话: {session_id[:8]}...")
    result = await workflow.step_optimize_script(session_id, extra_prompt=extra_prompt or "")

    if not result.get("success"):
        logger.error(f"[API] 优化失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "优化脚本失败"))

    logger.info(f"[API] 步骤2完成 - 脚本优化完成")

    result_data = session_manager.get_step_result(session_id, "optimize_script")

    return StepResponse(
        success=True,
        message=result.get("message", "脚本优化完成"),
        data=result_data,
    )


@router.post("/{session_id}/materials", response_model=StepResponse)
async def step_3_generate_materials(
    session_id: str,
    request: Step3Request,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3：生成素材图

    支持两种模式：
    1. 纯文生图：不提供参考图，使用默认模型生成
    2. 图生图：提供参考图，使用 gemini-3-pro-image-preview 模型，基于参考图生成
    """
    logger.info(f"[API] 步骤3 - 生成素材图 - 会话: {session_id[:8]}...")
    logger.info(f"[API] 请求参数 - extra_prompt: {request.extra_prompt if request.extra_prompt else '(未设置)'}")
    if request.reference_images:
        logger.info(f"[API] 请求参数 - reference_images: {len(request.reference_images)} 张参考图")
        for idx, img_path in enumerate(request.reference_images):
            logger.info(f"[API]   参考图 {idx+1}: {img_path[:100]}...")
    else:
        logger.info(f"[API] 请求参数 - reference_images: (未设置，使用纯文生图模式)")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查前置步骤
    can_execute, reason = session_manager.can_execute_step(session_id, "generate_material_images")
    if not can_execute:
        logger.error(f"[API] 前置步骤未完成: {reason}")
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤2：优化脚本")

    # 创建生成中状态（不预设固定数量，让 LLM 决定生成多少张）
    initial_data = {
        "material_images": [],  # 空列表，由 workflow 填充实际生成的素材图
        "image_count": 0,
        "type_counts": {},
        "_generating": True,  # 标记为生成中
        "_success": False  # 标记为未完成
    }

    # 先保存生成中状态，让前端知道正在处理
    session_manager.save_step_result(session_id, "generate_material_images", initial_data, success=False)
    logger.info(f"[API] 已保存生成中状态，开始后台生成素材图")

    # 在后台任务中执行（因为可能耗时较长）
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始生成素材图 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_material_images(
            session_id,
            extra_prompt=request.extra_prompt or "",
            reference_images=request.reference_images
        )
        logger.info(f"[API] 后台任务完成 - 素材图生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 素材图生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="素材图生成任务已启动",
        data=initial_data,
    )


@router.post("/{session_id}/segments", response_model=StepResponse)
async def step_4_generate_segments(
    session_id: str,
    request: Step4Request = None,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤4：生成分片脚本"""
    extra_prompt = request.extra_prompt if request else None
    logger.info(f"[API] 步骤4 - 生成分片脚本 - 会话: {session_id[:8]}...")
    if extra_prompt:
        logger.info(f"[API] 自定义提示词: {extra_prompt[:100]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()

    # 检查前置步骤
    can_execute, reason = session_manager.can_execute_step(session_id, "generate_segment_scripts")
    if not can_execute:
        logger.error(f"[API] 前置步骤未完成: {reason}")
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤3：生成素材图")

    # 执行步骤4（异步方法）
    logger.info(f"[API] 执行 workflow.step_generate_segment_scripts - 会话: {session_id[:8]}...")
    result = await workflow.step_generate_segment_scripts(session_id, extra_prompt=extra_prompt or "")

    if not result.get("success"):
        logger.error(f"[API] 生成分片失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "生成分片脚本失败"))

    logger.info(f"[API] 步骤4完成 - 分片脚本生成完成")

    result_data = session_manager.get_step_result(session_id, "generate_segment_scripts")

    return StepResponse(
        success=True,
        message=result.get("message", "分片脚本生成完成"),
        data=result_data,
    )


@router.post("/{session_id}/frames", response_model=StepResponse)
async def step_5_generate_frames(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤5：生成首尾帧"""
    logger.info(f"[API] 步骤5 - 生成首尾帧 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查前置步骤
    can_execute, reason = session_manager.can_execute_step(session_id, "generate_segment_frames")
    if not can_execute:
        logger.error(f"[API] 前置步骤未完成: {reason}")
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤4：生成分片脚本")

    # 在后台任务中执行
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始生成首尾帧 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_segment_frames(session_id)
        logger.info(f"[API] 后台任务完成 - 首尾帧生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 首尾帧生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="首尾帧生成任务已启动，请稍后查询结果",
        data=None,
    )


@router.post("/{session_id}/videos", response_model=StepResponse)
async def step_6_generate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6：生成视频"""
    logger.info(f"[API] 步骤6 - 生成视频 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查前置步骤
    can_execute, reason = session_manager.can_execute_step(session_id, "generate_videos")
    if not can_execute:
        logger.error(f"[API] 前置步骤未完成: {reason}")
        raise HTTPException(status_code=400, detail=reason or "请先完成步骤5：生成首尾帧")

    # 在后台任务中执行
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始生成视频 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_videos(session_id)
        logger.info(f"[API] 后台任务完成 - 视频生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 视频生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="视频生成任务已启动，请稍后查询结果",
        data=None,
    )


# ==================== 重新提交/重新优化 API ====================

@router.post("/{session_id}/resubmit", response_model=StepResponse)
async def step_1_resubmit_script(
    session_id: str,
    request: Step1Request,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤1重新提交：修改脚本和参数
    
    重新提交后，会清空步骤1之后的所有步骤数据，允许用户重新走完整流程。
    """
    # 检查会话是否存在
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤1是否已完成（只有已完成才需要重新提交）
    if not session_manager.is_step_completed(session_id, "submit_script_and_params"):
        raise HTTPException(status_code=400, detail="步骤1尚未完成，请使用正常提交接口")

    # 清空步骤1之后的所有步骤数据
    logger.info(f"[步骤1重新提交] 清空后续步骤数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "submit_script_and_params")
    if not cleared:
        raise HTTPException(status_code=500, detail="清空后续步骤数据失败")

    # 重置 current_step 到步骤1
    reset = session_manager.reset_current_step(session_id, "submit_script_and_params")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 创建工作流并重新提交
    workflow = get_workflow()

    # 创建视频参数字典
    video_params = {
        "resolution": request.resolution,
        "aspect_ratio": request.aspect_ratio,
        "language": request.language,
        "style": request.style,
        "perspective": request.camera_view,
    }

    # 重新执行步骤1
    result = workflow.step_submit(session_id, request.script, video_params)

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "重新提交失败"))

    # 获取更新后的步骤结果
    result_data = session_manager.get_step_result(session_id, "submit_script_and_params")

    return StepResponse(
        success=True,
        message="脚本和参数已重新提交，后续步骤数据已重置",
        data=result_data,
    )


@router.post("/{session_id}/reoptimize", response_model=StepResponse)
async def step_2_reoptimize_script(
    session_id: str,
    request: Step2Request = None,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤2重新优化：重新优化脚本

    重新优化后，会清空步骤2之后的所有步骤数据。
    """
    extra_prompt = request.extra_prompt if request else None
    logger.info(f"[API] 步骤2重新优化 - 会话: {session_id[:8]}...")
    if extra_prompt:
        logger.info(f"[API] 自定义提示词: {extra_prompt[:100]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤2是否已完成（只有已完成才需要重新优化）
    if not session_manager.is_step_completed(session_id, "optimize_script"):
        raise HTTPException(status_code=400, detail="步骤2尚未完成，请使用正常优化接口")

    # 检查前置步骤（步骤1）是否完成
    if not session_manager.is_step_completed(session_id, "submit_script_and_params"):
        raise HTTPException(status_code=400, detail="请先完成步骤1：提交脚本")

    # 清空步骤2之后的所有步骤数据
    logger.info(f"[步骤2重新优化] 清空后续步骤数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "optimize_script")
    if not cleared:
        raise HTTPException(status_code=500, detail="清空后续步骤数据失败")

    # 重置 current_step 到步骤2
    reset = session_manager.reset_current_step(session_id, "optimize_script")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 创建工作流并重新优化
    workflow = get_workflow()

    # 重新执行步骤2（异步方法）
    result = await workflow.step_optimize_script(session_id, extra_prompt=extra_prompt or "")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "重新优化脚本失败"))

    result_data = session_manager.get_step_result(session_id, "optimize_script")

    return StepResponse(
        success=True,
        message="脚本已重新优化，后续步骤数据已重置",
        data=result_data,
    )


@router.post("/{session_id}/regenerate-materials", response_model=StepResponse)
async def step_3_regenerate_materials(
    session_id: str,
    request: Step3Request,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤3重新生成：重新生成素材图

    重新生成后，会清空步骤3之后的所有步骤数据（分片脚本、首尾帧、视频）。
    """
    logger.info(f"[API] 步骤3 - 重新生成素材图 - 会话: {session_id[:8]}...")
    logger.info(f"[API] 请求参数 - extra_prompt: {request.extra_prompt if request.extra_prompt else '(未设置)'}")
    if request.reference_images:
        logger.info(f"[API] 请求参数 - reference_images: {len(request.reference_images)} 张参考图")
        for idx, img_path in enumerate(request.reference_images):
            logger.info(f"[API]   参考图 {idx+1}: {img_path[:100]}...")
    else:
        logger.info(f"[API] 请求参数 - reference_images: (未设置，使用纯文生图模式)")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤3是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_material_images"):
        logger.error(f"[API] 步骤3尚未完成，无法重新生成")
        raise HTTPException(status_code=400, detail="步骤3尚未完成，请使用正常生成接口")

    # 检查前置步骤（步骤2）是否完成
    if not session_manager.is_step_completed(session_id, "optimize_script"):
        logger.error(f"[API] 步骤2尚未完成")
        raise HTTPException(status_code=400, detail="请先完成步骤2：优化脚本")

    # 清空步骤3之后的所有步骤数据
    logger.info(f"[API] 清空后续步骤数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "generate_material_images")
    if not cleared:
        logger.error(f"[API] 清空后续步骤数据失败")
        raise HTTPException(status_code=500, detail="清空后续步骤数据失败")

    # 重置 current_step 到步骤3
    reset = session_manager.reset_current_step(session_id, "generate_material_images")
    if not reset:
        logger.error(f"[API] 重置步骤状态失败")
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 创建生成中状态（清除旧数据，不预设固定数量，让 LLM 决定生成多少张）
    initial_data = {
        "material_images": [],  # 清空旧素材图，由 workflow 填充新生成的素材图
        "image_count": 0,
        "type_counts": {},
        "_generating": True,  # 标记为生成中
        "_success": False  # 标记为未完成
    }

    # 先保存生成中状态，让前端知道正在处理
    session_manager.save_step_result(session_id, "generate_material_images", initial_data, success=False)
    logger.info(f"[API] 已清空旧素材图数据，开始后台重新生成素材图")

    # 在后台任务中执行（因为可能耗时较长）
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始重新生成素材图 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_material_images(
            session_id,
            extra_prompt=request.extra_prompt or "",
            reference_images=request.reference_images
        )
        logger.info(f"[API] 后台任务完成 - 素材图重新生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 素材图重新生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="素材图重新生成任务已启动，后续步骤数据已重置",
        data=initial_data,
    )


@router.post("/{session_id}/regenerate-segments", response_model=StepResponse)
async def step_4_regenerate_segments(
    session_id: str,
    request: Step4Request = None,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤4重新生成：重新生成分片脚本

    重新生成后，会清空步骤4之后的所有步骤数据（首尾帧、视频）。
    """
    extra_prompt = request.extra_prompt if request else None
    logger.info(f"[API] 步骤4重新生成 - 会话: {session_id[:8]}...")
    if extra_prompt:
        logger.info(f"[API] 自定义提示词: {extra_prompt[:100]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤4是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_segment_scripts"):
        raise HTTPException(status_code=400, detail="步骤4尚未完成，请使用正常生成接口")

    # 检查前置步骤（步骤3）是否完成
    if not session_manager.is_step_completed(session_id, "generate_material_images"):
        raise HTTPException(status_code=400, detail="请先完成步骤3：生成素材图")

    # 清空步骤4之后的所有步骤数据
    logger.info(f"[步骤4重新生成] 清空后续步骤数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "generate_segment_scripts")
    if not cleared:
        raise HTTPException(status_code=500, detail="清空后续步骤数据失败")

    # 重置 current_step 到步骤4
    reset = session_manager.reset_current_step(session_id, "generate_segment_scripts")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 创建工作流并重新生成分片脚本
    workflow = get_workflow()

    # 重新执行步骤4（异步方法）
    result = await workflow.step_generate_segment_scripts(session_id, extra_prompt=extra_prompt or "")

    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "重新生成分片脚本失败"))

    result_data = session_manager.get_step_result(session_id, "generate_segment_scripts")

    return StepResponse(
        success=True,
        message="分片脚本已重新生成，后续步骤数据已重置",
        data=result_data,
    )


@router.post("/{session_id}/regenerate-frames", response_model=StepResponse)
async def step_5_regenerate_frames(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤5重新生成：重新生成首尾帧
    
    重新生成后，会清空步骤5之后的所有步骤数据（视频）。
    """
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤5是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_segment_frames"):
        raise HTTPException(status_code=400, detail="步骤5尚未完成，请使用正常生成接口")

    # 检查前置步骤（步骤4）是否完成
    if not session_manager.is_step_completed(session_id, "generate_segment_scripts"):
        raise HTTPException(status_code=400, detail="请先完成步骤4：生成分片脚本")

    # 清空步骤5之后的所有步骤数据
    logger.info(f"[步骤5重新生成] 清空后续步骤数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "generate_segment_frames")
    if not cleared:
        raise HTTPException(status_code=500, detail="清空后续步骤数据失败")

    # 重置 current_step 到步骤5
    reset = session_manager.reset_current_step(session_id, "generate_segment_frames")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 在后台任务中执行
    async def execute_step():
        workflow = get_workflow()
        await workflow.step_generate_segment_frames(session_id)

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)

    return StepResponse(
        success=True,
        message="首尾帧重新生成任务已启动，后续步骤数据已重置，请稍后查询结果",
        data=None,
    )


@router.post("/{session_id}/regenerate-videos", response_model=StepResponse)
async def step_6_regenerate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6重新生成：重新生成视频
    
    重新生成后，会清空之前的视频数据并重新生成。
    """
    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤6是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_videos"):
        raise HTTPException(status_code=400, detail="步骤6尚未完成，请使用正常生成接口")

    # 检查前置步骤（步骤5）是否完成
    if not session_manager.is_step_completed(session_id, "generate_segment_frames"):
        raise HTTPException(status_code=400, detail="请先完成步骤5：生成首尾帧")

    # 清空步骤6的数据（虽然是最后一步，但也清空以防万一）
    logger.info(f"[步骤6重新生成] 清空视频数据 - 会话: {session_id[:8]}...")
    cleared = session_manager.clear_steps_after(session_id, "generate_videos")
    if not cleared:
        raise HTTPException(status_code=500, detail="清空视频数据失败")

    # 重置 current_step 到步骤6
    reset = session_manager.reset_current_step(session_id, "generate_videos")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 在后台任务中执行
    async def execute_step():
        workflow = get_workflow()
        await workflow.step_generate_videos(session_id)

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)

    return StepResponse(
        success=True,
        message="视频重新生成任务已启动，请稍后查询结果",
        data=None,
    )
