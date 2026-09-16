"""
素材图管理 API
"""
import logging
from fastapi import APIRouter, Depends, HTTPException

from backend.schemas.materials import (
    MaterialEditRequest,
    MaterialRegenerateRequest,
    MaterialAddRequest,
    MaterialUpdateDescriptionRequest,
    MaterialResponse,
)
from backend.deps import get_session_manager, get_workflow
from backend.core.persistence.session_manager import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/{session_id}/{index}/edit", response_model=MaterialResponse)
async def edit_material(
    session_id: str,
    index: int,
    request: MaterialEditRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """编辑素材图（使用图生图）"""
    logger.info(f"[API] 编辑素材图 - 会话: {session_id[:8]}... - 索引: {index}")
    logger.info(f"[API] 编辑参数 - prompt: {request.prompt[:100] if request.prompt else '(未设置)'}...")
    logger.info(f"[API] 编辑参数 - original_image_path: {request.original_image_path[:100] if request.original_image_path else '(未设置)'}...")
    if request.reference_images:
        logger.info(f"[API] 编辑参数 - reference_images: {len(request.reference_images)} 张参考图")
        for idx, img_path in enumerate(request.reference_images):
            logger.info(f"[API]   参考图 {idx+1}: {img_path[:100]}...")
    else:
        logger.info(f"[API] 编辑参数 - reference_images: (未设置，将使用原素材图)")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    workflow = get_workflow()

    logger.info(f"[API] 调用 workflow.edit_material_image - 会话: {session_id[:8]}... - 索引: {index}")
    if request.description:
        logger.info(f"[API] 编辑参数 - description: {request.description[:100]}...")

    result = await workflow.edit_material_image(
        session_id=session_id,
        image_index=index,
        prompt=request.prompt,
        description=request.description,
        reference_images=request.reference_images,
        original_image_path=request.original_image_path
    )

    if not result.get("success"):
        logger.error(f"[API] 编辑失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "编辑失败"))

    logger.info(f"[API] 编辑成功 - 新图片路径: {result.get('image_path', '')[:100]}...")

    return MaterialResponse(
        success=True,
        message=result.get("message", f"素材图 {index} 已更新"),
        image_path=result.get("image_path")
    )


@router.post("/{session_id}/{index}/regenerate", response_model=MaterialResponse)
async def regenerate_material(
    session_id: str,
    index: int,
    request: MaterialRegenerateRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """重新生成素材图"""
    logger.info(f"[API] 重新生成素材图 - 会话: {session_id[:8]}... - 索引: {index}")
    logger.info(f"[API] 重新生成参数 - custom_prompt: {request.custom_prompt if request.custom_prompt else '(未设置，使用原提示词)'}")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 获取当前素材图数据
    step_result = session_manager.get_step_result(session_id, "generate_material_images")
    if not step_result or "material_images" not in step_result:
        logger.error(f"[API] 素材图尚未生成")
        raise HTTPException(status_code=400, detail="素材图尚未生成")

    material_images = step_result["result_data"]["material_images"]
    if index < 0 or index >= len(material_images):
        logger.error(f"[API] 素材图索引 {index} 不存在（总数: {len(material_images)}）")
        raise HTTPException(status_code=404, detail=f"素材图索引 {index} 不存在")

    workflow = get_workflow()

    # 使用原提示词重新生成
    original_image = material_images[index]
    original_prompt = original_image.get("prompt", "")
    original_path = original_image.get("image_path", "")

    logger.info(f"[API] 原素材图信息 - prompt: {original_prompt[:100] if original_prompt else '(无)'}...")
    logger.info(f"[API] 原素材图信息 - path: {original_path[:100] if original_path else '(无)'}...")

    final_prompt = request.custom_prompt or original_prompt or "重新生成，保持风格一致"
    logger.info(f"[API] 最终使用提示词: {final_prompt[:100]}...")

    result = await workflow.edit_material_image(
        session_id=session_id,
        image_index=index,
        edit_prompt=final_prompt,
        reference_images=[original_path] if original_path else None,
        original_image_path=original_path
    )

    if not result.get("success"):
        logger.error(f"[API] 重新生成失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "重新生成失败"))

    logger.info(f"[API] 重新生成成功 - 新图片路径: {result.get('image_path', '')[:100]}...")

    return MaterialResponse(
        success=True,
        message=result.get("message", f"素材图 {index} 已重新生成"),
        image_path=result.get("image_path")
    )


@router.put("/{session_id}/{index}/description", response_model=MaterialResponse)
async def update_material_description(
    session_id: str,
    index: int,
    request: MaterialUpdateDescriptionRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """仅更新素材图描述（不重新生成图片）"""
    logger.info(f"[API] 更新素材图描述 - 会话: {session_id[:8]}... - 索引: {index}")
    logger.info(f"[API] 新描述: {request.description[:100] if request.description else '(空)'}...")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 获取当前素材图数据
    step_result = session_manager.get_step_result(session_id, "generate_material_images")
    if not step_result or "material_images" not in step_result.get("result_data", {}):
        logger.error(f"[API] 素材图尚未生成")
        raise HTTPException(status_code=400, detail="素材图尚未生成")

    material_images = step_result["result_data"]["material_images"]
    if index < 0 or index >= len(material_images):
        logger.error(f"[API] 素材图索引 {index} 不存在（总数: {len(material_images)}）")
        raise HTTPException(status_code=404, detail=f"素材图索引 {index} 不存在")

    # 仅更新描述字段
    material_images[index]["description"] = request.description

    # 保存更新
    session_manager.save_step_result(
        session_id, "generate_material_images", step_result["result_data"], success=True
    )

    logger.info(f"[API] 素材图描述更新成功")

    return MaterialResponse(
        success=True,
        message=f"素材图 {index + 1} 描述已更新"
    )


@router.delete("/{session_id}/{index}", response_model=MaterialResponse)
async def delete_material(
    session_id: str,
    index: int,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """删除素材图"""
    logger.info(f"[API] 删除素材图 - 会话: {session_id[:8]}... - 索引: {index}")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    step_result = session_manager.get_step_result(session_id, "generate_material_images")
    if not step_result or "material_images" not in step_result.get("result_data", {}):
        logger.error(f"[API] 素材图尚未生成")
        raise HTTPException(status_code=400, detail="素材图尚未生成")

    material_images = step_result["result_data"]["material_images"]
    if index < 0 or index >= len(material_images):
        logger.error(f"[API] 素材图索引 {index} 不存在（总数: {len(material_images)}）")
        raise HTTPException(status_code=404, detail=f"素材图索引 {index} 不存在")

    # 记录被删除的素材图信息
    deleted_image = material_images[index]
    logger.info(f"[API] 删除的素材图信息 - description: {deleted_image.get('description', '(无)')}")
    logger.info(f"[API] 删除的素材图信息 - path: {deleted_image.get('image_path', '(无)')[:100]}...")

    # 删除素材图
    del material_images[index]
    logger.info(f"[API] 删除成功 - 剩余素材图数量: {len(material_images)}")

    # 保存更新
    session_manager.save_step_result(
        session_id, "generate_material_images", step_result["result_data"], success=True
    )

    return MaterialResponse(success=True, message=f"素材图 {index} 已删除")


@router.post("/{session_id}/add", response_model=MaterialResponse)
async def add_material(
    session_id: str,
    request: MaterialAddRequest,
    session_manager: SessionManager = Depends(get_session_manager),
):
    """新增素材图（使用图生图）"""
    logger.info(f"[API] 新增素材图 - 会话: {session_id[:8]}...")
    logger.info(f"[API] 新增参数 - prompt: {request.prompt[:100] if request.prompt else '(未设置)'}...")
    logger.info(f"[API] 新增参数 - description: {request.description if request.description else '(未设置)'}")
    if request.reference_images:
        logger.info(f"[API] 新增参数 - reference_images: {len(request.reference_images)} 张参考图")
        for idx, img_path in enumerate(request.reference_images):
            logger.info(f"[API]   参考图 {idx+1}: {img_path[:100]}...")
    else:
        logger.info(f"[API] 新增参数 - reference_images: (未设置，将使用纯文生图模式)")

    session_info = session_manager.get_session(session_id)
    if not session_info:
        logger.error(f"[API] 会话不存在: {session_id}")
        raise HTTPException(status_code=404, detail=f"会话 {session_id} 不存在")

    # 检查是否已经生成过素材图
    step_result = session_manager.get_step_result(session_id, "generate_material_images")
    if not step_result or "material_images" not in step_result.get("result_data", {}):
        logger.error(f"[API] 素材图尚未生成，请先执行步骤3")
        raise HTTPException(status_code=400, detail="素材图尚未生成，请先执行步骤3")

    workflow = get_workflow()

    # 调用 workflow 的新增素材图方法
    logger.info(f"[API] 调用 workflow.add_material_image - 会话: {session_id[:8]}...")
    result = await workflow.add_material_image(
        session_id=session_id,
        prompt=request.prompt,
        description=request.description,
        reference_images=request.reference_images
    )

    if not result.get("success"):
        logger.error(f"[API] 新增失败 - 错误: {result.get('error', '未知错误')}")
        raise HTTPException(status_code=400, detail=result.get("error", "新增失败"))

    logger.info(f"[API] 新增成功 - 新图片路径: {result.get('image_path', '')[:100]}... - 索引: {result.get('index')}")

    return MaterialResponse(
        success=True,
        message=result.get("message", "素材图已新增"),
        image_path=result.get("image_path"),
        index=result.get("index")
    )
