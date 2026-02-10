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
    OptimizeSegmentPromptRequest,
)
from backend.deps import get_session_manager, get_workflow
from backend.core.persistence.session_manager import SessionManager
from backend.core.agents.workflow_v2 import VideoCreationWorkflowV2
from backend.core.models.video_models import VideoParams

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
    logger.info(f"[API] 分片时长: {request.max_segment_duration}秒")

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
        "max_segment_duration": request.max_segment_duration,
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
    """步骤5：生成首尾帧

    采用异步轮询模式：
    1. 先保存初始状态（带 _generating 标志）
    2. 后台执行生成任务
    3. 前端轮询获取最新状态
    """
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

    # 获取分片脚本信息，构建初始帧数据
    segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
    segment_scripts = segments_result['result_data'].get('segment_scripts', [])

    # 创建初始"生成中"状态（所有帧标记为pending）
    initial_frames = []
    for segment in segment_scripts:
        initial_frames.append({
            "segment_index": segment.get("index", 0),
            "first_image_id": "",
            "first_image_path": "",
            "last_image_id": "",
            "last_image_path": "",
            "first_prompt": "",
            "last_prompt": "",
            "first_status": "pending",  # 首帧状态
            "last_status": "pending",   # 尾帧状态
        })

    initial_data = {
        "segment_frames": initial_frames,
        "frame_count": len(initial_frames),
        "generated_count": 0,
        "reused_count": 0,
        "error_count": 0,
        "_generating": True,   # 标记为生成中
        "_success": False      # 标记为未完成
    }

    # 先保存生成中状态，让前端知道正在处理
    session_manager.save_step_result(session_id, "generate_segment_frames", initial_data, success=False)
    logger.info(f"[API] 已保存生成中状态，开始后台生成首尾帧 - 会话: {session_id[:8]}...")

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
        message="首尾帧生成任务已启动",
        data=initial_data,
    )


@router.post("/{session_id}/videos", response_model=StepResponse)
async def step_6_generate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6：生成视频

    采用异步轮询模式：
    1. 先保存初始状态（带 _generating 标志）
    2. 后台执行生成任务
    3. 前端轮询获取最新状态
    """
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

    # 获取分片脚本信息，构建初始视频数据
    segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
    segment_scripts = segments_result['result_data'].get('segment_scripts', [])

    # 创建初始"生成中"状态（所有视频标记为pending）
    initial_videos = []
    for segment in segment_scripts:
        initial_videos.append({
            "segment_index": segment.get("index", 0),
            "video_id": "",
            "video_path": "",
            "duration": 0.0,
            "prompt": "",
            "task_status": "pending"
        })

    initial_data = {
        "generated_videos": initial_videos,
        "video_count": len(initial_videos),
        "success_count": 0,
        "failed_count": 0,
        "_generating": True,   # 标记为生成中
        "_success": False      # 标记为未完成
    }

    # 先保存生成中状态，让前端知道正在处理
    session_manager.save_step_result(session_id, "generate_videos", initial_data, success=False)
    logger.info(f"[API] 已保存生成中状态，开始后台生成视频 - 会话: {session_id[:8]}...")

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
        message="视频生成任务已启动，正在生成中...",
        data=initial_data,
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

    采用异步轮询模式，重新生成后会清空步骤5之后的所有步骤数据（视频）。
    """
    logger.info(f"[API] 步骤5 - 重新生成首尾帧 - 会话: {session_id[:8]}...")

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

    # 获取分片脚本信息，构建初始帧数据
    segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
    segment_scripts = segments_result['result_data'].get('segment_scripts', [])

    # 创建初始"生成中"状态（所有帧标记为pending）
    initial_frames = []
    for segment in segment_scripts:
        initial_frames.append({
            "segment_index": segment.get("index", 0),
            "first_image_id": "",
            "first_image_path": "",
            "last_image_id": "",
            "last_image_path": "",
            "first_prompt": "",
            "last_prompt": "",
            "first_status": "pending",
            "last_status": "pending",
        })

    initial_data = {
        "segment_frames": initial_frames,
        "frame_count": len(initial_frames),
        "generated_count": 0,
        "reused_count": 0,
        "error_count": 0,
        "_generating": True,
        "_success": False
    }

    # 先保存生成中状态
    session_manager.save_step_result(session_id, "generate_segment_frames", initial_data, success=False)
    logger.info(f"[API] 已清空旧数据并保存生成中状态 - 会话: {session_id[:8]}...")

    # 在后台任务中执行
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始重新生成首尾帧 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_segment_frames(session_id)
        logger.info(f"[API] 后台任务完成 - 首尾帧重新生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 首尾帧重新生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="首尾帧重新生成任务已启动，后续步骤数据已重置",
        data=initial_data,
    )


@router.post("/{session_id}/cancel-frames", response_model=StepResponse)
async def step_5_cancel_frames(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤5取消：取消正在进行的首尾帧生成任务

    设置取消标志，后台任务会在下一次检查时停止。
    """
    logger.info(f"[API] 步骤5 - 取消首尾帧生成 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查是否正在生成
    step_result = session_manager.get_step_result(session_id, "generate_segment_frames")
    if not step_result:
        raise HTTPException(status_code=400, detail="首尾帧生成任务尚未开始")

    result_data = step_result['result_data']
    if not result_data.get('_generating', False):
        raise HTTPException(status_code=400, detail="当前没有正在进行的首尾帧生成任务")

    # 设置取消标志
    success = session_manager.set_step_cancelled(session_id, "generate_segment_frames", True)
    if not success:
        raise HTTPException(status_code=500, detail="设置取消标志失败")

    logger.info(f"[API] 首尾帧生成取消标志已设置 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="取消请求已发送，正在停止生成任务...",
        data={"cancelled": True},
    )


@router.post("/{session_id}/reset-frames", response_model=StepResponse)
async def step_5_reset_frames(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤5重置：重置首尾帧生成状态为未开始

    删除步骤5的所有数据，让用户可以重新开始生成。
    适用于生成中、已取消、部分完成等任何状态。
    """
    logger.info(f"[API] 步骤5 - 重置首尾帧状态 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查前置步骤（步骤4）是否完成
    if not session_manager.is_step_completed(session_id, "generate_segment_scripts"):
        raise HTTPException(status_code=400, detail="请先完成步骤4：生成分片脚本")

    # 清空步骤5及之后的所有步骤数据
    logger.info(f"[API] 清空步骤5及后续步骤数据 - 会话: {session_id[:8]}...")

    # 先删除步骤5的数据
    success = session_manager.delete_step_result(session_id, "generate_segment_frames")
    if not success:
        logger.warning(f"[API] 步骤5数据不存在或删除失败 - 会话: {session_id[:8]}...")

    # 清空步骤5之后的所有步骤数据（如视频）
    cleared = session_manager.clear_steps_after(session_id, "generate_segment_frames")
    if not cleared:
        logger.warning(f"[API] 清空后续步骤数据失败 - 会话: {session_id[:8]}...")

    # 重置 current_step 到步骤5
    reset = session_manager.reset_current_step(session_id, "generate_segment_frames")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    logger.info(f"[API] 步骤5状态已重置为未开始 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="首尾帧生成状态已重置，可以重新开始生成",
        data={"reset": True},
    )


@router.post("/{session_id}/cancel-videos", response_model=StepResponse)
async def step_6_cancel_videos(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6取消：取消正在进行的视频生成任务

    设置取消标志，后台任务会在下一次检查时停止。
    """
    logger.info(f"[API] 步骤6 - 取消视频生成 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查是否正在生成
    step_result = session_manager.get_step_result(session_id, "generate_videos")
    if not step_result:
        raise HTTPException(status_code=400, detail="视频生成任务尚未开始")

    result_data = step_result['result_data']
    if not result_data.get('_generating', False):
        raise HTTPException(status_code=400, detail="当前没有正在进行的视频生成任务")

    # 设置取消标志
    success = session_manager.set_step_cancelled(session_id, "generate_videos", True)
    if not success:
        raise HTTPException(status_code=500, detail="设置取消标志失败")

    logger.info(f"[API] 视频生成取消标志已设置 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message="取消请求已发送，正在停止生成任务...",
        data={"cancelled": True},
    )


@router.post("/{session_id}/regenerate-videos", response_model=StepResponse)
async def step_6_regenerate_videos(
    session_id: str,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6重新生成：重新生成视频

    采用异步轮询模式，保留旧视频数据作为备份，标记为待重新生成状态。

    重要：不删除旧视频数据，而是：
    1. 保留旧的 video_path 到 _old_video_path（作为备份）
    2. 将 task_status 改为 pending（标记为待重新生成）
    3. 清空 video_id 和 prompt
    """
    logger.info(f"[API] 步骤6 - 重新生成视频 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤6是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_videos"):
        raise HTTPException(status_code=400, detail="步骤6尚未完成，请使用正常生成接口")

    # 检查前置步骤（步骤5）是否完成
    if not session_manager.is_step_completed(session_id, "generate_segment_frames"):
        raise HTTPException(status_code=400, detail="请先完成步骤5：生成首尾帧")

    # 重置 current_step 到步骤6（不删除数据，只重置步骤状态）
    reset = session_manager.reset_current_step(session_id, "generate_videos")
    if not reset:
        raise HTTPException(status_code=500, detail="重置步骤状态失败")

    # 获取现有的视频数据
    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    existing_videos = existing_result['result_data'].get('generated_videos', []) if existing_result else []

    # 获取分片脚本信息
    segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
    segment_scripts = segments_result['result_data'].get('segment_scripts', [])

    # 创建待重新生成状态（保留旧数据作为备份）
    initial_videos = []
    for segment in segment_scripts:
        seg_idx = segment.get("index", 0)

        # 查找现有的视频记录
        existing_video = next((v for v in existing_videos if v.get('segment_index') == seg_idx), None)

        if existing_video and existing_video.get('video_path'):
            # 有旧视频，保留作为备份
            initial_videos.append({
                "segment_index": seg_idx,
                "video_id": "",
                "video_path": "",
                "duration": 0.0,
                "prompt": "",
                "task_status": "pending",
                "_old_video_path": existing_video.get('video_path'),  # 备份旧路径
                "_old_video_id": existing_video.get('video_id', ''),
            })
        else:
            # 没有旧视频
            initial_videos.append({
                "segment_index": seg_idx,
                "video_id": "",
                "video_path": "",
                "duration": 0.0,
                "prompt": "",
                "task_status": "pending"
            })

    # 统计备份的视频数量
    backed_up_count = sum(1 for v in initial_videos if '_old_video_path' in v)

    initial_data = {
        "generated_videos": initial_videos,
        "video_count": len(initial_videos),
        "success_count": 0,
        "failed_count": 0,
        "_generating": True,
        "_success": False,
        "_backed_up_count": backed_up_count,  # 记录备份数量
    }

    # 先保存待重新生成状态（不删除旧数据）
    session_manager.save_step_result(session_id, "generate_videos", initial_data, success=False)
    logger.info(f"[API] 已标记为待重新生成状态（保留 {backed_up_count} 个旧视频作为备份）- 会话: {session_id[:8]}...")

    # 在后台任务中执行
    async def execute_step():
        logger.info(f"[API] 后台任务启动 - 开始重新生成视频 - 会话: {session_id[:8]}...")
        workflow = get_workflow()
        await workflow.step_generate_videos(session_id)
        logger.info(f"[API] 后台任务完成 - 视频重新生成完成 - 会话: {session_id[:8]}...")

    def run_async_task():
        asyncio.run(execute_step())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 视频重新生成任务已提交到后台队列 - 会话: {session_id[:8]}...")

    message = "视频重新生成任务已启动，正在生成中..."
    if backed_up_count > 0:
        message += f"（已保留 {backed_up_count} 个旧视频作为备份）"

    return StepResponse(
        success=True,
        message=message,
        data=initial_data,
    )


@router.post("/{session_id}/restore-videos-backup", response_model=StepResponse)
async def step_6_restore_videos_backup(
    session_id: str,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """恢复备份的视频

    将 _old_video_path 恢复为 video_path，用于撤销重新生成操作。
    只能在有备份数据时使用。
    """
    logger.info(f"[API] 步骤6 - 恢复视频备份 - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 获取当前的视频数据
    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    if not existing_result:
        raise HTTPException(status_code=404, detail="未找到视频数据")

    result_data = existing_result['result_data']
    generated_videos = result_data.get('generated_videos', [])

    # 恢复备份
    restored_count = 0
    for video in generated_videos:
        old_path = video.get('_old_video_path')
        if old_path:
            video['video_path'] = old_path
            video['video_id'] = video.get('_old_video_id', '')
            video['task_status'] = 'completed'
            video['duration'] = 5.0  # 恢复默认时长
            # 保留备份字段，方便再次恢复
            restored_count += 1

    if restored_count == 0:
        raise HTTPException(status_code=400, detail="没有可恢复的备份数据")

    # 更新统计信息
    result_data['success_count'] = restored_count
    result_data['failed_count'] = len(generated_videos) - restored_count
    result_data['_generating'] = False
    result_data['_success'] = (restored_count == len(generated_videos))

    # 保存恢复后的数据
    session_manager.save_step_result(session_id, "generate_videos", result_data, success=True)
    logger.info(f"[API] 已恢复 {restored_count} 个视频的备份 - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message=f"已恢复 {restored_count} 个视频的备份",
        data=result_data,
    )


@router.post("/{session_id}/regenerate-single-video/{segment_index}", response_model=StepResponse)
async def step_6_regenerate_single_video(
    session_id: str,
    segment_index: int,
    background_tasks: BackgroundTasks,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """步骤6重新生成单个视频：仅重新生成指定分片的视频

    保留旧视频数据作为备份，标记该视频为待重新生成状态。
    """
    logger.info(f"[API] 步骤6 - 重新生成单个视频 (分片 {segment_index}) - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤6是否已完成（只有已完成才需要重新生成）
    if not session_manager.is_step_completed(session_id, "generate_videos"):
        raise HTTPException(status_code=400, detail="步骤6尚未完成，请先完成视频生成")

    # 检查前置步骤（步骤5）是否完成
    if not session_manager.is_step_completed(session_id, "generate_segment_frames"):
        raise HTTPException(status_code=400, detail="请先完成步骤5：生成首尾帧")

    # 获取现有的视频数据
    existing_result = session_manager.get_step_result(session_id, "generate_videos")
    result_data = existing_result['result_data']
    generated_videos = result_data.get('generated_videos', []) if existing_result else []

    # 查找指定分片的视频
    target_video = None
    target_index = -1
    for i, video in enumerate(generated_videos):
        if video.get('segment_index') == segment_index:
            target_video = video
            target_index = i
            break

    if target_video is None:
        raise HTTPException(status_code=404, detail=f"未找到分片 {segment_index} 的视频数据")

    # 保存旧视频数据作为备份
    if target_video.get('video_path'):
        target_video['_old_video_path'] = target_video['video_path']
        target_video['_old_video_id'] = target_video.get('video_id', '')

    # 标记为待重新生成状态
    target_video['video_id'] = ""
    target_video['video_path'] = ""
    target_video['prompt'] = ""
    target_video['task_status'] = "pending"

    # 更新数据库
    result_data['_generating'] = True
    result_data['_success'] = False
    session_manager.update_step_result(session_id, "generate_videos", result_data)

    logger.info(f"[API] 已标记视频 {segment_index} 为待重新生成状态 - 会话: {session_id[:8]}...")

    # 在后台任务中重新生成单个视频
    async def execute_single_video_generation():
        logger.info(f"[API] 后台任务启动 - 开始重新生成单个视频 (分片 {segment_index}) - 会话: {session_id[:8]}...")

        try:
            workflow = get_workflow()

            # 获取必要的数据
            frames_result = session_manager.get_step_result(session_id, "generate_segment_frames")
            segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
            script_result = session_manager.get_step_result(session_id, "optimize_script")

            from backend.core.models import SegmentFrame, ScriptSegment, VideoParams

            # 处理 segment_frames 数据，将 None 值转换为 ""
            raw_frames = frames_result['result_data']['segment_frames']
            cleaned_frames = []
            for frame in raw_frames:
                cleaned_frame = {}
                for key, value in frame.items():
                    cleaned_frame[key] = "" if value is None else value
                cleaned_frames.append(cleaned_frame)
            segment_frames = [SegmentFrame(**frame) for frame in cleaned_frames]
            segment_scripts = [ScriptSegment(**seg) for seg in segments_result['result_data']['segment_scripts']]
            params = script_result['result_data']['video_params']
            video_params = VideoParams(**params)

            # 找到对应的分片和首尾帧
            segment = None
            frame = None
            seg_list_index = -1

            for i, seg in enumerate(segment_scripts):
                if seg.index == segment_index:
                    segment = seg
                    seg_list_index = i
                    break

            for f in segment_frames:
                if f.segment_index == segment_index:
                    frame = f
                    break

            if not segment or not frame or not frame.first_image_path:
                # 标记为失败
                result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
                for video in result_data['generated_videos']:
                    if video.get('segment_index') == segment_index:
                        video['task_status'] = "failed"
                        video['video_path'] = f"生成失败: 缺少分片数据或首尾帧"
                        break
                result_data['_generating'] = False
                result_data['failed_count'] = result_data.get('failed_count', 0) + 1
                session_manager.update_step_result(session_id, "generate_videos", result_data)
                logger.error(f"[API] 分片 {segment_index} 缺少数据或首尾帧 - 会话: {session_id[:8]}...")
                return

            # 获取前后分片（用于上下文）
            prev_segment = segment_scripts[seg_list_index - 1] if seg_list_index > 0 else None
            next_segment = segment_scripts[seg_list_index + 1] if seg_list_index < len(segment_scripts) - 1 else None

            # 生成视频
            video = await workflow.video_service.generate_video_from_frames(
                segment,
                frame.first_image_path,
                frame.last_image_path,
                video_params,
                total_segments=len(segment_scripts),
                extra_prompt="",
                prev_segment=prev_segment,
                next_segment=next_segment,
            )

            # 确保设置 task_status
            if not hasattr(video, 'task_status') or not video.task_status:
                if video.video_path and not video.video_path.startswith("生成失败"):
                    video.task_status = "completed"
                elif video.video_path and video.video_path.startswith("生成失败"):
                    video.task_status = "failed"
                else:
                    video.task_status = "pending"

            # 更新数据库中的视频数据
            result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
            for i, v in enumerate(result_data['generated_videos']):
                if v.get('segment_index') == segment_index:
                    result_data['generated_videos'][i] = video.model_dump()
                    break

            # 更新统计
            success_count = sum(1 for v in result_data['generated_videos'] if v.get('task_status') == 'completed')
            failed_count = sum(1 for v in result_data['generated_videos'] if v.get('task_status') == 'failed')

            result_data['success_count'] = success_count
            result_data['failed_count'] = failed_count
            result_data['_generating'] = False
            result_data['_success'] = (failed_count == 0)

            session_manager.update_step_result(session_id, "generate_videos", result_data)
            logger.info(f"[API] 后台任务完成 - 单个视频重新生成完成 (分片 {segment_index}) - 会话: {session_id[:8]}...")

        except Exception as e:
            logger.error(f"[API] 单个视频重新生成失败 (分片 {segment_index}): {e}")
            # 标记为失败
            result_data = session_manager.get_step_result(session_id, "generate_videos")['result_data']
            for video in result_data['generated_videos']:
                if video.get('segment_index') == segment_index:
                    video['task_status'] = "failed"
                    video['video_path'] = f"生成失败: {str(e)}"
                    break
            result_data['_generating'] = False
            session_manager.update_step_result(session_id, "generate_videos", result_data)

    def run_async_task():
        asyncio.run(execute_single_video_generation())

    background_tasks.add_task(run_async_task)
    logger.info(f"[API] 单个视频重新生成任务已提交到后台队列 (分片 {segment_index}) - 会话: {session_id[:8]}...")

    return StepResponse(
        success=True,
        message=f"视频 {segment_index + 1} 重新生成任务已启动",
        data=result_data,
    )


@router.post("/{session_id}/optimize-segment-prompt/{segment_index}", response_model=StepResponse)
async def optimize_segment_prompt(
    session_id: str,
    segment_index: int,
    request: OptimizeSegmentPromptRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """优化分片提示词：基于首尾帧图片和上下文生成优化的分片文案

    使用 LLM 的多模态能力分析首尾帧图片，结合优化后的总脚本和视频参数，
    生成更好的分片文案供用户参考。
    """
    logger.info(f"[API] 优化分片提示词 (分片 {segment_index}) - 会话: {session_id[:8]}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查步骤5是否已完成（需要有首尾帧）
    if not session_manager.is_step_completed(session_id, "generate_segment_frames"):
        raise HTTPException(status_code=400, detail="请先完成步骤5：生成首尾帧")

    # 获取必要的数据
    frames_result = session_manager.get_step_result(session_id, "generate_segment_frames")
    segments_result = session_manager.get_step_result(session_id, "generate_segment_scripts")
    script_result = session_manager.get_step_result(session_id, "optimize_script")

    if not frames_result or not segments_result or not script_result:
        raise HTTPException(status_code=400, detail="缺少必要的步骤数据")

    # 获取首尾帧
    segment_frames = frames_result['result_data'].get('segment_frames', [])
    target_frame = None
    for frame in segment_frames:
        if frame.get('segment_index') == segment_index:
            target_frame = frame
            break

    if not target_frame:
        raise HTTPException(status_code=404, detail=f"未找到分片 {segment_index} 的首尾帧数据")

    first_frame_path = target_frame.get('first_image_path', '')
    last_frame_path = target_frame.get('last_image_path', '')

    if not first_frame_path:
        raise HTTPException(status_code=400, detail="首帧图片不存在")

    # 获取分片脚本
    segment_scripts = segments_result['result_data'].get('segment_scripts', [])
    target_segment = None
    for seg in segment_scripts:
        if seg.get('index') == segment_index:
            target_segment = seg
            break

    if not target_segment:
        raise HTTPException(status_code=404, detail=f"未找到分片 {segment_index} 的脚本数据")

    # 获取优化后的总脚本和视频参数
    optimized_script = script_result['result_data'].get('optimized_script', '')
    params_data = script_result['result_data'].get('video_params', {})

    try:
        from backend.core.models import VideoParams, ScriptSegment
        from backend.core.services.llm_service import LLMService

        video_params = VideoParams(**params_data)
        current_segment = ScriptSegment(**target_segment)

        # 调用 LLM 服务优化提示词
        llm_service = LLMService()
        optimized_prompt = await llm_service.optimize_segment_prompt_with_images(
            first_frame_path=first_frame_path,
            last_frame_path=last_frame_path,
            optimized_script=optimized_script,
            video_params=video_params,
            current_segment=current_segment,
            custom_requirement=request.custom_requirement or ""
        )

        logger.info(f"[API] 分片 {segment_index} 提示词优化完成 - 会话: {session_id[:8]}...")

        return StepResponse(
            success=True,
            message="分片提示词优化完成",
            data={
                "segment_index": segment_index,
                "optimized_prompt": optimized_prompt,
            },
        )

    except Exception as e:
        logger.error(f"[API] 优化分片提示词失败: {e}")
        raise HTTPException(status_code=500, detail=f"优化分片提示词失败: {str(e)}")
