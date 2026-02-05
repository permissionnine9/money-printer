"""视频创作工作流 V2 - 符合PRD的6步流程

工作流程（符合PRD）：
1. submit_script_and_params: 用户输入脚本 + 选定参数后提交
2. optimize_script: LLM优化脚本
3. generate_material_images: 生成素材图（1-2张）
4. generate_segment_scripts: 生成分片脚本
5. generate_segment_frames: 生成首尾帧
6. generate_videos: 生成视频
"""
import asyncio
import uuid
import logging

from backend.core.models import (
    VideoParams,
    ScriptSegment,
    MaterialImage,
    SegmentFrame,
)
from backend.core.config import SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP, SHENGSUANYUN_FRAME_IMAGE_MODEL
from backend.core.services import LLMService, ImageService, VideoService
from backend.core.persistence import SessionManager

logger = logging.getLogger(__name__)


class VideoCreationWorkflowV2:
    """视频创作工作流 V2 - 符合PRD的6步流程"""

    def __init__(
        self,
        db_path: str = "data/sessions.db",
        session_manager: SessionManager | None = None
    ):
        """初始化工作流

        Args:
            db_path: 数据库路径（当 session_manager 为 None 时使用）
            session_manager: 可选的 SessionManager 实例（用于依赖注入）
        """
        self.llm_service = LLMService()
        self.image_service = ImageService()
        self.video_service = VideoService()
        # 支持依赖注入，允许共享 SessionManager 实例
        self.session_manager = session_manager or SessionManager(db_path)
        logger.info("VideoCreationWorkflowV2 初始化完成")

    def create_session(self) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())
        self.session_manager.create_session(session_id)
        logger.info(f"创建会话: {session_id[:8]}...")
        return session_id

    def get_session_status(self, session_id: str) -> dict:
        """获取会话状态和进度"""
        return self.session_manager.get_session_summary(session_id)

    # ==================== 步骤 1: 提交脚本和参数 ====================
    def step_submit(
        self,
        session_id: str,
        original_script: str,
        video_params: dict
    ) -> dict:
        """步骤1：提交脚本和视频参数

        Args:
            session_id: 会话ID
            original_script: 原始脚本内容
            video_params: 视频参数字典

        Returns:
            执行结果
        """
        logger.info(f"[步骤1] 提交脚本和参数 - 会话: {session_id[:8]}...")

        if not original_script or not original_script.strip():
            return {"success": False, "error": "脚本内容不能为空"}

        # 保存结果
        result_data = {
            "original_script": original_script,
            "video_params": video_params,
            "script_length": len(original_script)
        }

        self.session_manager.save_step_result(session_id, "submit_script_and_params", result_data)
        logger.info(f"[步骤1] 完成 - 脚本长度: {len(original_script)} 字符")

        return {
            "success": True,
            "message": "脚本和参数已提交",
            "data": result_data
        }

    # ==================== 步骤 2: 优化脚本 ====================
    async def step_optimize_script(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤2：LLM优化视频长脚本

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：更多动作细节、特定风格等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤2] 优化脚本 - 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤2] 使用自定义提示词: {extra_prompt[:100]}...")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "optimize_script")
        if not can_execute:
            return {"success": False, "error": reason}

        # 获取脚本和参数
        submit_result = self.session_manager.get_step_result(session_id, "submit_script_and_params")
        original_script = submit_result['result_data']['original_script']
        params = submit_result['result_data']['video_params']

        try:
            video_params = VideoParams(**params)

            # LLM优化总脚本
            optimized_script = await self.llm_service.optimize_long_script(
                original_script,
                video_params,
                extra_prompt=extra_prompt
            )

            # 保存结果
            result_data = {
                "optimized_script": optimized_script,
                "video_params": params,
                "script_length": len(optimized_script)
            }

            self.session_manager.save_step_result(session_id, "optimize_script", result_data)
            logger.info(f"[步骤2] 完成 - 优化后脚本长度: {len(optimized_script)} 字符")

            return {
                "success": True,
                "message": "脚本优化完成",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤2] 失败: {str(e)}")
            return {"success": False, "error": f"脚本优化失败: {str(e)}"}

    # ==================== 步骤 3: 生成素材图 ====================
    async def step_generate_material_images(
        self,
        session_id: str,
        extra_prompt: str = "",
        reference_images: list[str] | None = None
    ) -> dict:
        """步骤3：生成素材图（设定稿风格：角色设定图、物品设定图、场景设定图）

        支持两种模式：
        1. 纯文生图：不提供参考图，使用默认模型生成
        2. 图生图：提供参考图，使用 gemini-3-pro-image-preview 模型，基于参考图生成

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：更鲜艳的颜色、卡通风格等）
            reference_images: 用户上传的参考图路径列表（可选，支持本地路径和URL）

        Returns:
            执行结果
        """
        logger.info(f"[步骤3] 生成素材图（设定稿）- 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤3] 使用自定义提示词: {extra_prompt[:100]}...")
        if reference_images:
            logger.info(f"[步骤3] 使用 {len(reference_images)} 张用户参考图")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "generate_material_images")
        if not can_execute:
            return {"success": False, "error": reason}

        # 获取优化后的脚本和参数
        script_result = self.session_manager.get_step_result(session_id, "optimize_script")
        optimized_script = script_result['result_data']['optimized_script']
        params = script_result['result_data']['video_params']

        try:
            video_params = VideoParams(**params)

            # 生成素材图提示词（包含 type: character/props/environment）
            prompts_data = await self.llm_service.generate_material_prompts(
                optimized_script,
                video_params,
                extra_prompt=extra_prompt
            )

            logger.info(f"[步骤3] LLM 生成了 {len(prompts_data)} 个素材图提示词")
            for i, p in enumerate(prompts_data):
                logger.info(f"  - {i+1}. [{p.get('type', 'general')}] {p.get('description', '')[:50]}...")

            # 生成素材图（如果有参考图，将使用 gemini-3-pro-image-preview 模型）
            images = await self.image_service.generate_material_images(
                prompts_data, video_params, reference_images=reference_images
            )

            # 统计结果
            completed_count = sum(1 for img in images if img.task_status == 'completed')
            failed_count = sum(1 for img in images if img.task_status == 'failed')

            # 按类型统计
            type_counts = {}
            for img in images:
                if img.task_status == 'completed':
                    t = img.image_type
                    type_counts[t] = type_counts.get(t, 0) + 1

            result_data = {
                "material_images": [img.model_dump() for img in images],
                "image_count": len(images),
                "type_counts": type_counts
            }

            if failed_count > 0:
                # 收集失败原因
                failed_reasons = [img.description for img in images if img.task_status == 'failed']
                for i, reason in enumerate(failed_reasons):
                    logger.error(f"[步骤3] 图片 {i+1} 失败原因: {reason}")

                self.session_manager.save_step_result(session_id, "generate_material_images", result_data, success=False)
                logger.error(f"[步骤3] 失败：{failed_count} 张图片生成失败")
                return {
                    "success": False,
                    "error": f"素材图生成失败：{failed_count} 张图片生成失败，原因: {'; '.join(failed_reasons)}"
                }

            # 保存成功结果
            self.session_manager.save_step_result(session_id, "generate_material_images", result_data, success=True)

            # 生成详细的成功消息
            type_names = {"character": "角色设定图", "props": "物品设定图", "environment": "场景设定图"}
            type_msg = ", ".join([f"{type_names.get(t, t)} {c}张" for t, c in type_counts.items()])
            logger.info(f"[步骤3] 完成 - 成功生成 {completed_count} 张素材图: {type_msg}")

            return {
                "success": True,
                "message": f"已生成 {completed_count} 张素材图（{type_msg}）",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤3] 失败: {str(e)}")
            return {"success": False, "error": f"素材图生成失败: {str(e)}"}

    # ==================== 步骤 4: 生成分片脚本 ====================
    async def step_generate_segment_scripts(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤4：生成分片脚本

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：更多动作细节、慢镜头等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤4] 生成分片脚本 - 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤4] 使用自定义提示词: {extra_prompt[:100]}...")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "generate_segment_scripts")
        if not can_execute:
            return {"success": False, "error": reason}

        # 获取优化后的脚本和参数
        script_result = self.session_manager.get_step_result(session_id, "optimize_script")
        optimized_script = script_result['result_data']['optimized_script']
        params = script_result['result_data']['video_params']

        try:
            video_params = VideoParams(**params)

            # 生成分片脚本
            segment_scripts = await self.llm_service.generate_segment_scripts(
                optimized_script,
                video_params,
                extra_prompt=extra_prompt
            )

            # 保存结果
            result_data = {
                "segment_scripts": [seg.model_dump() for seg in segment_scripts],
                "segment_count": len(segment_scripts)
            }

            self.session_manager.save_step_result(session_id, "generate_segment_scripts", result_data)
            logger.info(f"[步骤4] 完成 - 生成 {len(segment_scripts)} 个分片脚本")

            return {
                "success": True,
                "message": f"已生成 {len(segment_scripts)} 个分片脚本",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤4] 失败: {str(e)}")
            return {"success": False, "error": f"分片脚本生成失败: {str(e)}"}

    # ==================== 步骤 5: 生成首尾帧 ====================
    async def step_generate_segment_frames(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤5：生成首尾帧（支持三种模式：全新生成/连续生成/复用）

        三种首帧模式:
        1. generate: 全新生成，仅使用素材图作为参考
        2. generate_continuous: 连续生成，使用素材图+前一分片尾帧作为参考（保证视觉连贯）
        3. reuse_prev: 100%复用前一分片的尾帧（完全相同的图）

        优化策略:
        1. 分批处理：先生成所有尾帧和全新首帧，再生成需要连续的首帧
        2. 连续模式：将前一分片尾帧加入参考图，确保视觉连贯性
        3. 并发轮询：大幅提升生成速度

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：黄昏光线、俯拍角度等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤5] 生成首尾帧（支持三种模式）- 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤5] 使用自定义提示词: {extra_prompt[:100]}...")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "generate_segment_frames")
        if not can_execute:
            return {"success": False, "error": reason}

        # 获取素材图、分片脚本和参数
        material_result = self.session_manager.get_step_result(session_id, "generate_material_images")
        segments_result = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
        script_result = self.session_manager.get_step_result(session_id, "optimize_script")

        # 兼容旧数据：为缺失字段提供默认值
        raw_material_images = material_result['result_data']['material_images']
        material_images = []
        for idx, img in enumerate(raw_material_images):
            # 确保必填字段存在
            if 'image_id' not in img or not img['image_id']:
                img['image_id'] = f"legacy_{idx}"
            if 'task_id' not in img or img['task_id'] is None:
                img['task_id'] = ""
            if 'prompt' not in img:
                img['prompt'] = ""
            if 'image_type' not in img:
                img['image_type'] = "general"
            material_images.append(MaterialImage(**img))
        segment_scripts = [ScriptSegment(**seg) for seg in segments_result['result_data']['segment_scripts']]
        params = script_result['result_data']['video_params']

        try:
            video_params = VideoParams(**params)

            # 获取素材图描述（用于 LLM 生成提示词）
            material_desc = "; ".join([img.description for img in material_images if img.description])

            # 获取素材图 URL 列表（用于图生图）
            material_image_urls = [
                img.image_path for img in material_images
                if img.image_path and img.task_status == "completed"
            ]
            logger.info(f"[步骤5] 获取到 {len(material_image_urls)} 张素材图作为参考")

            # ========== 1. 并发生成所有分片的首尾帧提示词（带上下文） ==========
            logger.info(f"[步骤5] 并发生成 {len(segment_scripts)} 个分片的首尾帧提示词（含前后分片上下文）...")

            # 为每个分片准备前后分片上下文
            prompt_tasks = []
            for i, segment in enumerate(segment_scripts):
                prev_segment = segment_scripts[i - 1] if i > 0 else None
                next_segment = segment_scripts[i + 1] if i < len(segment_scripts) - 1 else None
                prompt_tasks.append(
                    self.llm_service.generate_frame_prompts(
                        segment, video_params, material_desc,
                        prev_segment=prev_segment,
                        next_segment=next_segment,
                        extra_prompt=extra_prompt
                    )
                )

            all_prompts = await asyncio.gather(*prompt_tasks, return_exceptions=True)

            # 检查提示词生成是否有错误
            prompts_map = {}  # {segment_index: (first_prompt, last_prompt)}
            for i, result in enumerate(all_prompts):
                if isinstance(result, Exception):
                    logger.error(f"分片 {segment_scripts[i].index} 提示词生成失败: {result}")
                    prompts_map[segment_scripts[i].index] = ("", "")
                else:
                    prompts_map[segment_scripts[i].index] = result

            # ========== 2. 构建需要生成的帧任务列表（支持三种模式） ==========
            # 分批处理：
            # 批次1：所有尾帧 + generate 首帧（不依赖其他帧，可并发）
            # 批次2：generate_continuous 首帧（需要前一分片尾帧作为参考）

            batch1_tasks = []  # 批次1：(segment_index, frame_type, prompt)
            batch2_tasks = []  # 批次2：(segment_index, frame_type, prompt, prev_seg_idx)

            # 统计
            reuse_count = 0
            continuous_count = 0
            generate_count = 0

            for segment in segment_scripts:
                idx = segment.index
                first_prompt, last_prompt = prompts_map.get(idx, ("", ""))

                # 首帧处理
                if segment.first_frame_mode == "reuse_prev" and idx > 0:
                    # 模式1：复用，不生成
                    reuse_count += 1
                    logger.info(f"[步骤5] 分片 {idx} 首帧将复用分片 {idx - 1} 的尾帧")
                elif segment.first_frame_mode == "generate_continuous" and idx > 0:
                    # 模式2：连续生成，需要前一帧作为参考
                    if first_prompt:
                        batch2_tasks.append((idx, "first", first_prompt, idx - 1))
                        continuous_count += 1
                        logger.info(f"[步骤5] 分片 {idx} 首帧将连续生成（参考分片 {idx - 1} 尾帧）")
                else:
                    # 模式3：全新生成，只使用素材图
                    if first_prompt:
                        batch1_tasks.append((idx, "first", first_prompt))
                        generate_count += 1

                # 尾帧处理（即使 reuse_next 也需要生成，因为是被复用方）
                if last_prompt:
                    batch1_tasks.append((idx, "last", last_prompt))
                    generate_count += 1

            logger.info(f"[步骤5] 任务统计: 全新生成 {generate_count} 张，连续生成 {continuous_count} 张，复用 {reuse_count} 张")

            # ========== 3. 批量提交和轮询（两批次处理） ==========
            generated_frames = {}  # {(idx, type): (id, path)}
            error_count = 0
            cancelled = False

            # ========== 3.1 批次1：生成所有尾帧 + generate 首帧 ==========
            if batch1_tasks:
                logger.info(f"[步骤5] [批次1] 开始生成 {len(batch1_tasks)} 张不依赖其他帧的图片...")
                submitted_batch1 = []  # [(seg_idx, frame_type, request_id)]

                # 间隔提交批次1的所有任务
                for i, (seg_idx, frame_type, prompt) in enumerate(batch1_tasks):
                    # 检查取消标志
                    if self.session_manager.is_step_cancelled(session_id, "generate_segment_frames"):
                        logger.info(f"[步骤5] 检测到取消请求，停止提交批次1任务（已提交 {len(submitted_batch1)}/{len(batch1_tasks)} 个）")
                        cancelled = True
                        break

                    # 间隔提交
                    if i > 0:
                        await asyncio.sleep(SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP)

                    logger.info(f"[步骤5] [批次1] 提交任务 {i + 1}/{len(batch1_tasks)}: 分片 {seg_idx} {frame_type}帧")

                    try:
                        # 构建提示词
                        i2i_prompt = self.image_service.build_frame_prompt(prompt, video_params, frame_type)
                        # 只提交任务，不等待完成（使用首尾帧专用模型，并发限制更宽松）
                        # 启用参考图压缩，避免素材图过大导致请求失败
                        submit_result = await self.image_service.submit_i2i_task(
                            i2i_prompt,
                            material_image_urls,
                            video_params,
                            model=SHENGSUANYUN_FRAME_IMAGE_MODEL,
                            compress_reference=True
                        )
                        if submit_result.get("success"):
                            request_id = submit_result["request_id"]
                            submitted_batch1.append((seg_idx, frame_type, request_id))
                            logger.info(f"[步骤5] [批次1] 分片 {seg_idx} {frame_type}帧任务已提交: {request_id}")
                        else:
                            logger.error(f"[步骤5] [批次1] 分片 {seg_idx} {frame_type}帧提交失败: {submit_result.get('error')}")
                            submitted_batch1.append((seg_idx, frame_type, None))
                    except Exception as e:
                        logger.error(f"[批次1] 分片 {seg_idx} {frame_type}帧提交失败: {e}")
                        submitted_batch1.append((seg_idx, frame_type, None))

                # 并发轮询批次1的所有任务
                if not cancelled and submitted_batch1:
                    logger.info(f"[步骤5] [批次1] 已提交 {len(submitted_batch1)} 个任务，开始并发轮询...")

                    async def poll_task(seg_idx: int, frame_type: str, request_id: str | None):
                        """轮询单个任务"""
                        if not request_id:
                            return (seg_idx, frame_type, "error", "")
                        try:
                            # 增加超时时间到180秒（3分钟），避免复杂图片生成超时
                            result = await self.image_service.poll_i2i_task(request_id, timeout=150, poll_interval=3)
                            if result.get("success"):
                                import uuid
                                image_id = str(uuid.uuid4())
                                return (seg_idx, frame_type, image_id, result.get("image_url", ""))
                            else:
                                return (seg_idx, frame_type, "error", "")
                        except Exception as e:
                            logger.error(f"轮询分片 {seg_idx} {frame_type}帧失败: {e}")
                            return (seg_idx, frame_type, "error", "")

                    # 并发执行所有轮询
                    poll_tasks = [poll_task(seg_idx, frame_type, req_id) for seg_idx, frame_type, req_id in submitted_batch1]
                    poll_results = await asyncio.gather(*poll_tasks)

                    # 处理批次1的结果
                    for seg_idx, frame_type, image_id, image_path in poll_results:
                        generated_frames[(seg_idx, frame_type)] = (image_id, image_path)
                        if image_path:
                            logger.info(f"[步骤5] [批次1] 分片 {seg_idx} {frame_type}帧生成成功")
                        else:
                            logger.error(f"[步骤5] [批次1] 分片 {seg_idx} {frame_type}帧生成失败")
                            error_count += 1

                    # 【重要】立即更新数据库状态，让前端能看到批次1的进度
                    intermediate_frames = self._build_intermediate_frames(segment_scripts, generated_frames, prompts_map)
                    intermediate_data = {
                        "segment_frames": [frame.model_dump() for frame in intermediate_frames],
                        "frame_count": len(intermediate_frames),
                        "generated_count": generate_count + continuous_count,
                        "reused_count": reuse_count,
                        "error_count": error_count,
                        "_generating": True,  # 仍在生成中
                        "_cancelled": cancelled,
                        "_success": False
                    }
                    self.session_manager.update_step_result(session_id, "generate_segment_frames", intermediate_data)
                    logger.info(f"[步骤5] [批次1] 进度已更新到数据库，前端可见")

            # ========== 3.2 批次2：生成 generate_continuous 首帧（参考前一分片尾帧） ==========
            if batch2_tasks and not cancelled:
                logger.info(f"[步骤5] [批次2] 开始生成 {len(batch2_tasks)} 张需要连续的首帧...")
                submitted_batch2 = []  # [(seg_idx, frame_type, request_id)]

                # 间隔提交批次2的所有任务
                for i, (seg_idx, frame_type, prompt, prev_seg_idx) in enumerate(batch2_tasks):
                    # 检查取消标志
                    if self.session_manager.is_step_cancelled(session_id, "generate_segment_frames"):
                        logger.info(f"[步骤5] 检测到取消请求，停止提交批次2任务（已提交 {len(submitted_batch2)}/{len(batch2_tasks)} 个）")
                        cancelled = True
                        break

                    # 间隔提交
                    if i > 0:
                        await asyncio.sleep(SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP)

                    logger.info(f"[步骤5] [批次2] 提交任务 {i + 1}/{len(batch2_tasks)}: 分片 {seg_idx} 首帧（参考分片 {prev_seg_idx} 尾帧）")

                    try:
                        # 获取前一分片的尾帧作为额外参考
                        prev_last_id, prev_last_path = generated_frames.get((prev_seg_idx, "last"), ("", ""))

                        # 构建参考图列表：素材图 + 前一分片尾帧
                        reference_images = list(material_image_urls)  # 复制素材图列表
                        if prev_last_path:
                            reference_images.append(prev_last_path)
                            logger.info(f"[步骤5] [批次2] 添加前一分片尾帧作为参考: {prev_last_path}")
                        else:
                            logger.warning(f"[步骤5] [批次2] 警告：分片 {prev_seg_idx} 尾帧不可用，仅使用素材图")

                        # 构建提示词
                        i2i_prompt = self.image_service.build_frame_prompt(prompt, video_params, frame_type)

                        # 提交任务（使用扩展的参考图列表，使用首尾帧专用模型）
                        # 启用参考图压缩，避免素材图过大导致请求失败
                        submit_result = await self.image_service.submit_i2i_task(
                            i2i_prompt,
                            reference_images,
                            video_params,
                            model=SHENGSUANYUN_FRAME_IMAGE_MODEL,
                            compress_reference=True
                        )
                        if submit_result.get("success"):
                            request_id = submit_result["request_id"]
                            submitted_batch2.append((seg_idx, frame_type, request_id))
                            logger.info(f"[步骤5] [批次2] 分片 {seg_idx} 首帧任务已提交: {request_id}")
                        else:
                            logger.error(f"[步骤5] [批次2] 分片 {seg_idx} 首帧提交失败: {submit_result.get('error')}")
                            submitted_batch2.append((seg_idx, frame_type, None))
                    except Exception as e:
                        logger.error(f"[批次2] 分片 {seg_idx} 首帧提交失败: {e}")
                        submitted_batch2.append((seg_idx, frame_type, None))

                # 并发轮询批次2的所有任务
                if not cancelled and submitted_batch2:
                    logger.info(f"[步骤5] [批次2] 已提交 {len(submitted_batch2)} 个任务，开始并发轮询...")

                    poll_tasks = [poll_task(seg_idx, frame_type, req_id) for seg_idx, frame_type, req_id in submitted_batch2]
                    poll_results = await asyncio.gather(*poll_tasks)

                    # 处理批次2的结果
                    for seg_idx, frame_type, image_id, image_path in poll_results:
                        generated_frames[(seg_idx, frame_type)] = (image_id, image_path)
                        if image_path:
                            logger.info(f"[步骤5] [批次2] 分片 {seg_idx} {frame_type}帧生成成功")
                        else:
                            logger.error(f"[步骤5] [批次2] 分片 {seg_idx} {frame_type}帧生成失败")
                            error_count += 1

                    # 【重要】立即更新数据库状态，让前端能看到批次2的进度
                    intermediate_frames = self._build_intermediate_frames(segment_scripts, generated_frames, prompts_map)
                    intermediate_data = {
                        "segment_frames": [frame.model_dump() for frame in intermediate_frames],
                        "frame_count": len(intermediate_frames),
                        "generated_count": generate_count + continuous_count,
                        "reused_count": reuse_count,
                        "error_count": error_count,
                        "_generating": True,  # 仍在生成中
                        "_cancelled": cancelled,
                        "_success": False
                    }
                    self.session_manager.update_step_result(session_id, "generate_segment_frames", intermediate_data)
                    logger.info(f"[步骤5] [批次2] 进度已更新到数据库，前端可见")

            # 如果被取消且没有生成任何帧，直接返回
            if cancelled and len(generated_frames) == 0:
                logger.info(f"[步骤5] 任务已取消，没有提交任何任务")
                result_data = {
                    "segment_frames": [],
                    "frame_count": 0,
                    "generated_count": 0,
                    "reused_count": 0,
                    "error_count": 0,
                    "_generating": False,
                    "_cancelled": True,
                    "_success": False
                }
                self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data, success=False)
                return {
                    "success": False,
                    "error": "首尾帧生成已取消",
                    "data": result_data
                }

            # ========== 4. 构建最终 SegmentFrame 列表（处理复用和连续） ==========
            segment_frames = []
            for segment in segment_scripts:
                idx = segment.index
                first_prompt, last_prompt = prompts_map.get(idx, ("", ""))

                # 获取首帧
                if segment.first_frame_mode == "reuse_prev" and idx > 0:
                    # 复用前一分片尾帧
                    first_id, first_path = generated_frames.get((idx - 1, "last"), ("", ""))
                    logger.info(f"[步骤5] 分片 {idx} 首帧复用自分片 {idx - 1} 尾帧: {first_path}")
                else:
                    first_id, first_path = generated_frames.get((idx, "first"), ("", ""))

                # 获取尾帧
                last_id, last_path = generated_frames.get((idx, "last"), ("", ""))

                # 确定状态
                first_status = "completed" if first_path else "failed"
                last_status = "completed" if last_path else "failed"

                segment_frames.append(SegmentFrame(
                    segment_index=idx,
                    first_image_id=first_id,
                    first_image_path=first_path,
                    last_image_id=last_id,
                    last_image_path=last_path,
                    first_prompt=first_prompt,
                    last_prompt=last_prompt,
                    first_status=first_status,
                    last_status=last_status
                ))

            # ========== 5. 保存结果 ==========
            # 统计实际完成的帧数（排除未生成的）
            actual_generated = len([f for f in segment_frames if f.first_image_path or f.last_image_path])
            total_generated = generate_count + continuous_count  # 总生成数

            result_data = {
                "segment_frames": [frame.model_dump() for frame in segment_frames],
                "frame_count": len(segment_frames),
                "generated_count": total_generated,  # 全新生成 + 连续生成的总数
                "reused_count": reuse_count,
                "error_count": error_count,
                "_generating": False,  # 标记生成完成
                "_cancelled": cancelled,  # 标记是否被取消
                "_success": (not cancelled) and (error_count == 0)  # 根据是否取消和是否有错误判断成功状态
            }

            # 如果被取消
            if cancelled:
                self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data, success=False)
                logger.warning(f"[步骤5] 任务已取消 - 已生成 {actual_generated} 组，未完成 {len(segment_frames) - actual_generated} 组")
                return {
                    "success": False,
                    "error": f"首尾帧生成已取消（已完成 {actual_generated}/{len(segment_frames)} 组）",
                    "data": result_data
                }

            # 如果有错误
            if error_count > 0:
                self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data, success=False)
                logger.error(f"[步骤5] 部分失败 - {error_count} 张帧生成失败")
                return {
                    "success": False,
                    "error": f"首尾帧生成部分失败：{error_count} 张图片生成失败",
                    "data": result_data
                }

            # 全部成功
            self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data)
            logger.info(f"[步骤5] 完成 - 全新生成 {generate_count} 张，连续生成 {continuous_count} 张，复用 {reuse_count} 张，共 {len(segment_frames)} 组首尾帧")

            message_parts = []
            if generate_count > 0:
                message_parts.append(f"全新生成 {generate_count} 张")
            if continuous_count > 0:
                message_parts.append(f"连续生成 {continuous_count} 张")
            if reuse_count > 0:
                message_parts.append(f"复用 {reuse_count} 张")

            message = f"已生成 {len(segment_frames)} 组首尾帧（{', '.join(message_parts)}）"

            return {
                "success": True,
                "message": message,
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤5] 失败: {str(e)}")
            return {"success": False, "error": f"首尾帧生成失败: {str(e)}"}

    # ==================== 步骤 6: 生成视频 ====================
    async def step_generate_videos(self, session_id: str, extra_prompt: str = "") -> dict:
        """步骤6：生成视频

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：流畅过渡、电影感等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤6] 生成视频 - 会话: {session_id[:8]}...")
        if extra_prompt:
            logger.info(f"[步骤6] 使用自定义提示词: {extra_prompt[:100]}...")

        # 检查前置步骤
        can_execute, reason = self.session_manager.can_execute_step(session_id, "generate_videos")
        if not can_execute:
            return {"success": False, "error": reason}

        # 获取首尾帧、分片脚本和参数
        frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
        segments_result = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
        script_result = self.session_manager.get_step_result(session_id, "optimize_script")

        segment_frames = [SegmentFrame(**frame) for frame in frames_result['result_data']['segment_frames']]
        segment_scripts = [ScriptSegment(**seg) for seg in segments_result['result_data']['segment_scripts']]
        params = script_result['result_data']['video_params']

        # 获取优化后的总脚本，作为视频生成的上下文
        optimized_script = script_result['result_data'].get('optimized_script', '')

        try:
            video_params = VideoParams(**params)
            total_segments = len(segment_scripts)

            videos = []
            for segment in segment_scripts:
                # 检查是否被取消
                if self.session_manager.is_step_cancelled(session_id, "generate_videos"):
                    logger.warning(f"[步骤6] 视频生成已被用户取消 - 会话: {session_id[:8]}...")
                    # 保存当前进度（已生成的视频）
                    success_count = sum(1 for v in videos if v.task_status == "completed")
                    failed_count = sum(1 for v in videos if v.task_status == "failed")

                    result_data = {
                        "generated_videos": [v.model_dump() for v in videos],
                        "video_count": len(videos),
                        "success_count": success_count,
                        "failed_count": failed_count,
                        "_generating": False,
                        "_success": False,
                        "_cancelled": True
                    }
                    self.session_manager.save_step_result(session_id, "generate_videos", result_data, success=False)
                    logger.info(f"[步骤6] 已停止 - 已生成 {success_count}/{total_segments} 个视频")

                    return {
                        "success": False,
                        "error": f"视频生成已取消（已生成 {success_count}/{total_segments} 个视频）",
                        "data": result_data
                    }

                # 找到对应的首尾帧
                frame = next(
                    (f for f in segment_frames if f.segment_index == segment.index),
                    None
                )

                if not frame or not frame.first_image_path:
                    return {"success": False, "error": f"分片 {segment.index} 缺少首尾帧"}

                # 生成视频，传递优化后的总脚本作为上下文
                video = await self.video_service.generate_video_from_frames(
                    segment,
                    frame.first_image_path,
                    frame.last_image_path,
                    video_params,
                    optimized_script=optimized_script,
                    total_segments=total_segments,
                    extra_prompt=extra_prompt,
                )

                # 确保设置 task_status
                if not hasattr(video, 'task_status') or not video.task_status:
                    # 根据 video_path 判断状态
                    if video.video_path and not video.video_path.startswith("生成失败"):
                        video.task_status = "completed"
                    elif video.video_path and video.video_path.startswith("生成失败"):
                        video.task_status = "failed"
                    else:
                        video.task_status = "pending"

                videos.append(video)

                # 每生成一个视频后，保存当前进度（这样前端可以看到实时进度）
                success_count = sum(1 for v in videos if v.task_status == "completed")
                failed_count = sum(1 for v in videos if v.task_status == "failed")

                intermediate_data = {
                    "generated_videos": [v.model_dump() for v in videos],
                    "video_count": len(videos),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "_generating": True,  # 仍在生成中
                    "_success": False
                }
                # 不推进 current_step，仅更新数据
                self.session_manager.update_step_result(session_id, "generate_videos", intermediate_data)
                logger.info(f"[步骤6] 进度更新: {len(videos)}/{total_segments} 个视频已处理")

            # 统计成功和失败
            success_count = sum(1 for v in videos if v.task_status == "completed")
            failed_count = sum(1 for v in videos if v.task_status == "failed")

            # 保存结果
            result_data = {
                "generated_videos": [v.model_dump() for v in videos],
                "video_count": len(videos),
                "success_count": success_count,
                "failed_count": failed_count,
                "_generating": False,  # 标记生成完成
                "_success": failed_count == 0  # 根据是否有错误判断成功状态
            }

            if failed_count > 0:
                self.session_manager.save_step_result(session_id, "generate_videos", result_data, success=False)
                logger.error(f"[步骤6] 部分失败 - {failed_count} 个视频生成失败")
                return {
                    "success": False,
                    "error": f"视频生成部分失败：{failed_count} 个视频生成失败",
                    "data": result_data
                }

            self.session_manager.save_step_result(session_id, "generate_videos", result_data)

            # 更新会话状态为已完成
            self.session_manager.update_session_status(session_id, "completed")
            logger.info(f"[步骤6] 完成 - 生成 {len(videos)} 个视频片段")

            return {
                "success": True,
                "message": f"已生成 {len(videos)} 个视频片段",
                "data": result_data
            }

        except Exception as e:
            logger.error(f"[步骤6] 失败: {str(e)}")
            return {"success": False, "error": f"视频生成失败: {str(e)}"}

    # ==================== 分片脚本编辑方法 ====================

    def update_segment(self, session_id: str, segment_index: int, segment_data: dict) -> dict:
        """更新分片脚本

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            segment_data: 分片数据字典

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 更新分片 {segment_index} - 会话: {session_id[:8]}...")

        success = self.session_manager.update_segment_script(session_id, segment_index, segment_data)

        if success:
            return {
                "success": True,
                "message": f"分片 {segment_index + 1} 已更新",
                "segment_index": segment_index
            }
        else:
            return {
                "success": False,
                "error": f"更新分片 {segment_index + 1} 失败"
            }

    def delete_segment(self, session_id: str, segment_index: int) -> dict:
        """删除分片

        Args:
            session_id: 会话ID
            segment_index: 分片索引

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 删除分片 {segment_index} - 会话: {session_id[:8]}...")

        success = self.session_manager.delete_segment(session_id, segment_index)

        if success:
            return {
                "success": True,
                "message": f"分片 {segment_index + 1} 已删除"
            }
        else:
            return {
                "success": False,
                "error": f"删除分片 {segment_index + 1} 失败"
            }

    def add_segment(self, session_id: str, segment_data: dict, insert_after: int = -1) -> dict:
        """新增分片

        Args:
            session_id: 会话ID
            segment_data: 分片数据字典
            insert_after: 插入位置（-1表示末尾）

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 新增分片 (位置: {insert_after}) - 会话: {session_id[:8]}...")

        success = self.session_manager.add_segment(session_id, segment_data, insert_after)

        if success:
            return {
                "success": True,
                "message": "新分片已添加"
            }
        else:
            return {
                "success": False,
                "error": "添加分片失败"
            }

    def replace_frame(self, session_id: str, segment_index: int, frame_type: str, uploaded_file_path: str) -> dict:
        """替换首/尾帧图片（用户上传）

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            frame_type: 帧类型 ("first" 或 "last")
            uploaded_file_path: 上传文件的临时路径

        Returns:
            执行结果
        """
        import shutil
        import uuid
        from pathlib import Path
        from backend.core.config import IMAGES_DIR

        logger.info(f"[编辑] 替换{frame_type}帧 - 分片 {segment_index} - 会话: {session_id[:8]}...")

        if frame_type not in ("first", "last"):
            return {"success": False, "error": "无效的帧类型"}

        if not uploaded_file_path or not Path(uploaded_file_path).exists():
            return {"success": False, "error": "上传文件不存在"}

        try:
            # 生成新的图片ID和路径
            image_id = str(uuid.uuid4())
            ext = Path(uploaded_file_path).suffix or ".png"
            new_path = IMAGES_DIR / f"frame_{segment_index}_{frame_type}_{image_id}{ext}"

            # 复制文件到目标路径
            shutil.copy2(uploaded_file_path, new_path)

            # 更新数据库
            success = self.session_manager.update_segment_frame(
                session_id, segment_index, frame_type, str(new_path), image_id
            )

            if success:
                # 检查所有帧是否都已成功生成，如果是则更新步骤状态
                step_completed = self.session_manager.check_and_update_frames_step_status(session_id)
                if step_completed:
                    logger.info(f"[编辑] 所有首尾帧已生成完成，步骤5状态已更新为成功")

                frame_type_cn = "首" if frame_type == "first" else "尾"
                return {
                    "success": True,
                    "message": f"分片 {segment_index + 1} 的{frame_type_cn}帧已替换",
                    "image_path": str(new_path),
                    "step_completed": step_completed
                }
            else:
                return {"success": False, "error": "更新帧信息失败"}

        except Exception as e:
            logger.error(f"替换帧失败: {e}")
            return {"success": False, "error": f"替换帧失败: {str(e)}"}

    async def regenerate_frame(
        self,
        session_id: str,
        segment_index: int,
        frame_type: str,
        custom_prompt: str = "",
        reference_images: list[str] | None = None
    ) -> dict:
        """重新生成单个首/尾帧

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            frame_type: 帧类型 ("first" 或 "last")
            custom_prompt: 自定义提示词，如果提供则使用此提示词，否则由LLM自动生成
            reference_images: 参考图列表（可选），如果提供则仅使用指定的参考图，否则使用所有素材图

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 重新生成{frame_type}帧 - 分片 {segment_index} - 会话: {session_id[:8]}...")

        if frame_type not in ("first", "last"):
            return {"success": False, "error": "无效的帧类型"}

        try:
            # 获取分片脚本和参数
            segments_result = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
            script_result = self.session_manager.get_step_result(session_id, "optimize_script")
            material_result = self.session_manager.get_step_result(session_id, "generate_material_images")

            if not segments_result or not script_result:
                return {"success": False, "error": "缺少必要的步骤数据"}

            segment_scripts_data = segments_result['result_data'].get('segment_scripts', [])
            params = script_result['result_data']['video_params']

            # 找到对应的分片脚本及其前后分片
            segment_data = None
            prev_segment_data = None
            next_segment_data = None

            for i, seg in enumerate(segment_scripts_data):
                if seg.get('index') == segment_index:
                    segment_data = seg
                    if i > 0:
                        prev_segment_data = segment_scripts_data[i - 1]
                    if i < len(segment_scripts_data) - 1:
                        next_segment_data = segment_scripts_data[i + 1]
                    break

            if not segment_data:
                return {"success": False, "error": f"找不到分片 {segment_index}"}

            video_params = VideoParams(**params)
            segment = ScriptSegment(**segment_data)
            prev_segment = ScriptSegment(**prev_segment_data) if prev_segment_data else None
            next_segment = ScriptSegment(**next_segment_data) if next_segment_data else None

            # 获取素材图描述和URL
            material_desc = ""
            material_image_urls = []
            if material_result:
                # 兼容旧数据：为缺失字段提供默认值
                raw_material_images = material_result['result_data'].get('material_images', [])
                material_images_list = []
                for idx, img in enumerate(raw_material_images):
                    # 确保必填字段存在
                    if 'image_id' not in img or not img['image_id']:
                        img['image_id'] = f"legacy_{idx}"
                    if 'task_id' not in img or img['task_id'] is None:
                        img['task_id'] = ""
                    if 'prompt' not in img:
                        img['prompt'] = ""
                    if 'image_type' not in img:
                        img['image_type'] = "general"
                    material_images_list.append(MaterialImage(**img))
                material_desc = "; ".join([img.description for img in material_images_list if img.description])

                # 如果用户指定了参考图列表，则使用用户指定的；否则使用所有素材图
                if reference_images is not None:
                    material_image_urls = reference_images
                    logger.info(f"[编辑] 使用用户指定的 {len(reference_images)} 张参考图")
                else:
                    material_image_urls = [
                        img.image_path for img in material_images_list
                        if img.image_path and img.task_status == "completed"
                    ]
                    logger.info(f"[编辑] 使用全部 {len(material_image_urls)} 张素材图作为参考")

            # 确定提示词
            if custom_prompt and custom_prompt.strip():
                # 使用自定义提示词
                prompt = custom_prompt.strip()
                logger.info(f"[编辑] 使用自定义提示词: {prompt[:50]}...")
            else:
                # 生成提示词（带上下文）
                first_prompt, last_prompt = await self.llm_service.generate_frame_prompts(
                    segment,
                    video_params,
                    material_desc,
                    prev_segment=prev_segment,
                    next_segment=next_segment
                )
                # 选择需要的提示词
                prompt = first_prompt if frame_type == "first" else last_prompt
                logger.info(f"[编辑] 使用LLM生成的提示词: {prompt[:50]}...")

            # 生成单张图片（使用图生图，传入素材图作为参考，使用首尾帧专用模型）
            # 启用参考图压缩，避免素材图过大导致请求失败
            image_id, image_path = await self.image_service.generate_single_image(
                prompt,
                video_params,
                prefix=f"frame_{segment_index}_{frame_type}",
                reference_images=material_image_urls,  # 传入素材图作为参考
                frame_type=frame_type,  # 传递帧类型，用于在提示词中强调
                model=SHENGSUANYUN_FRAME_IMAGE_MODEL,  # 使用首尾帧专用模型
                compress_reference=True  # 启用参考图压缩
            )

            if not image_path:
                return {"success": False, "error": "图片生成失败"}

            # 更新数据库
            success = self.session_manager.update_segment_frame(
                session_id, segment_index, frame_type, image_path, image_id, prompt
            )

            if success:
                # 检查所有帧是否都已成功生成，如果是则更新步骤状态
                step_completed = self.session_manager.check_and_update_frames_step_status(session_id)
                if step_completed:
                    logger.info(f"[编辑] 所有首尾帧已生成完成，步骤5状态已更新为成功")

                frame_type_cn = "首" if frame_type == "first" else "尾"
                return {
                    "success": True,
                    "message": f"分片 {segment_index + 1} 的{frame_type_cn}帧已重新生成",
                    "image_path": image_path,
                    "step_completed": step_completed
                }
            else:
                return {"success": False, "error": "更新帧信息失败"}

        except Exception as e:
            logger.error(f"重新生成帧失败: {e}")
            return {"success": False, "error": f"重新生成帧失败: {str(e)}"}

    def reuse_adjacent_frame(
        self,
        session_id: str,
        segment_index: int,
        frame_type: str
    ) -> dict:
        """复用相邻分片的帧

        - 首帧(first): 复用上一分片(segment_index-1)的尾帧
        - 尾帧(last): 复用下一分片(segment_index+1)的首帧

        Args:
            session_id: 会话ID
            segment_index: 当前分片索引
            frame_type: 帧类型 ("first" 或 "last")

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 复用相邻帧 - 分片 {segment_index} {frame_type}帧 - 会话: {session_id[:8]}...")

        if frame_type not in ("first", "last"):
            return {"success": False, "error": "无效的帧类型"}

        try:
            # 获取当前首尾帧数据
            frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
            if not frames_result:
                return {"success": False, "error": "缺少首尾帧数据"}

            segment_frames = frames_result['result_data'].get('segment_frames', [])

            # 确定源分片索引
            if frame_type == "first":
                # 首帧复用上一分片的尾帧
                source_index = segment_index - 1
                if source_index < 0:
                    return {"success": False, "error": "第一个分片无法复用上一分片的尾帧"}
                source_frame_type = "last"
            else:
                # 尾帧复用下一分片的首帧
                source_index = segment_index + 1
                if source_index >= len(segment_frames):
                    return {"success": False, "error": "最后一个分片无法复用下一分片的首帧"}
                source_frame_type = "first"

            # 找到源分片的帧数据
            source_frame = None
            for frame in segment_frames:
                if frame.get('segment_index') == source_index:
                    source_frame = frame
                    break

            if not source_frame:
                return {"success": False, "error": f"找不到分片 {source_index} 的帧数据"}

            # 获取源帧的路径和ID
            if source_frame_type == "first":
                source_path = source_frame.get('first_image_path', '')
                source_id = source_frame.get('first_image_id', '')
            else:
                source_path = source_frame.get('last_image_path', '')
                source_id = source_frame.get('last_image_id', '')

            if not source_path:
                return {"success": False, "error": f"分片 {source_index} 的{source_frame_type}帧不存在"}

            # 更新目标分片的帧（直接复用，不复制文件）
            success = self.session_manager.update_segment_frame(
                session_id, segment_index, frame_type, source_path, source_id
            )

            if success:
                # 检查所有帧是否都已成功生成，如果是则更新步骤状态
                step_completed = self.session_manager.check_and_update_frames_step_status(session_id)
                if step_completed:
                    logger.info(f"[编辑] 所有首尾帧已生成完成，步骤5状态已更新为成功")

                source_desc = f"分片 {source_index + 1} 的{'尾' if source_frame_type == 'last' else '首'}帧"
                return {
                    "success": True,
                    "message": f"已将 {source_desc} 复用为分片 {segment_index + 1} 的{'首' if frame_type == 'first' else '尾'}帧",
                    "image_path": source_path,
                    "step_completed": step_completed
                }
            else:
                return {"success": False, "error": "更新帧信息失败"}

        except Exception as e:
            logger.error(f"复用相邻帧失败: {e}")
            return {"success": False, "error": f"复用相邻帧失败: {str(e)}"}

    def copy_frame_from(
        self,
        session_id: str,
        target_segment_index: int,
        target_frame_type: str,
        source_segment_index: int,
        source_frame_type: str
    ) -> dict:
        """从任意分片复制帧

        Args:
            session_id: 会话ID
            target_segment_index: 目标分片索引
            target_frame_type: 目标帧类型 ("first" 或 "last")
            source_segment_index: 源分片索引
            source_frame_type: 源帧类型 ("first" 或 "last")

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 复制帧 - 从分片 {source_segment_index} {source_frame_type}帧 到分片 {target_segment_index} {target_frame_type}帧 - 会话: {session_id[:8]}...")

        if target_frame_type not in ("first", "last"):
            return {"success": False, "error": "无效的目标帧类型"}
        if source_frame_type not in ("first", "last"):
            return {"success": False, "error": "无效的源帧类型"}

        try:
            # 获取当前首尾帧数据
            frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
            if not frames_result:
                return {"success": False, "error": "缺少首尾帧数据"}

            segment_frames = frames_result['result_data'].get('segment_frames', [])

            # 验证索引有效性
            if source_segment_index < 0 or source_segment_index >= len(segment_frames):
                return {"success": False, "error": f"无效的源分片索引: {source_segment_index}"}
            if target_segment_index < 0 or target_segment_index >= len(segment_frames):
                return {"success": False, "error": f"无效的目标分片索引: {target_segment_index}"}

            # 找到源分片的帧数据
            source_frame = None
            for frame in segment_frames:
                if frame.get('segment_index') == source_segment_index:
                    source_frame = frame
                    break

            if not source_frame:
                return {"success": False, "error": f"找不到分片 {source_segment_index} 的帧数据"}

            # 获取源帧的路径和ID
            if source_frame_type == "first":
                source_path = source_frame.get('first_image_path', '')
                source_id = source_frame.get('first_image_id', '')
                source_status = source_frame.get('first_status', '')
            else:
                source_path = source_frame.get('last_image_path', '')
                source_id = source_frame.get('last_image_id', '')
                source_status = source_frame.get('last_status', '')

            if not source_path or source_status != 'completed':
                return {"success": False, "error": f"分片 {source_segment_index + 1} 的{'首' if source_frame_type == 'first' else '尾'}帧未完成或不存在"}

            # 更新目标分片的帧（直接复用，不复制文件）
            success = self.session_manager.update_segment_frame(
                session_id, target_segment_index, target_frame_type, source_path, source_id
            )

            if success:
                # 检查所有帧是否都已成功生成，如果是则更新步骤状态
                step_completed = self.session_manager.check_and_update_frames_step_status(session_id)
                if step_completed:
                    logger.info(f"[编辑] 所有首尾帧已生成完成，步骤5状态已更新为成功")

                source_desc = f"分片 {source_segment_index + 1} 的{'首' if source_frame_type == 'first' else '尾'}帧"
                target_desc = f"分片 {target_segment_index + 1} 的{'首' if target_frame_type == 'first' else '尾'}帧"
                return {
                    "success": True,
                    "message": f"已将 {source_desc} 复制为 {target_desc}",
                    "image_path": source_path,
                    "step_completed": step_completed
                }
            else:
                return {"success": False, "error": "更新帧信息失败"}

        except Exception as e:
            logger.error(f"复制帧失败: {e}")
            return {"success": False, "error": f"复制帧失败: {str(e)}"}

    def get_adjacent_frame_info(self, session_id: str, segment_index: int) -> dict:
        """获取相邻分片的帧信息（用于前端显示）

        Args:
            session_id: 会话ID
            segment_index: 当前分片索引

        Returns:
            {
                "prev_last_frame": {"path": str, "exists": bool},  # 上一分片尾帧
                "next_first_frame": {"path": str, "exists": bool}, # 下一分片首帧
                "total_segments": int
            }
        """
        try:
            frames_result = self.session_manager.get_step_result(session_id, "generate_segment_frames")
            if not frames_result:
                return {
                    "prev_last_frame": {"path": "", "exists": False},
                    "next_first_frame": {"path": "", "exists": False},
                    "total_segments": 0
                }

            segment_frames = frames_result['result_data'].get('segment_frames', [])
            total = len(segment_frames)

            # 上一分片尾帧
            prev_last = {"path": "", "exists": False}
            if segment_index > 0:
                for frame in segment_frames:
                    if frame.get('segment_index') == segment_index - 1:
                        path = frame.get('last_image_path', '')
                        prev_last = {"path": path, "exists": bool(path)}
                        break

            # 下一分片首帧
            next_first = {"path": "", "exists": False}
            if segment_index < total - 1:
                for frame in segment_frames:
                    if frame.get('segment_index') == segment_index + 1:
                        path = frame.get('first_image_path', '')
                        next_first = {"path": path, "exists": bool(path)}
                        break

            return {
                "prev_last_frame": prev_last,
                "next_first_frame": next_first,
                "total_segments": total
            }

        except Exception as e:
            logger.error(f"获取相邻帧信息失败: {e}")
            return {
                "prev_last_frame": {"path": "", "exists": False},
                "next_first_frame": {"path": "", "exists": False},
                "total_segments": 0
            }

    # ==================== 素材图编辑方法 ====================

    async def edit_material_image(
        self,
        session_id: str,
        image_index: int,
        prompt: str,
        description: str | None = None,
        reference_images: list[str] | None = None,
        original_image_path: str | None = None
    ) -> dict:
        """编辑单个素材图

        使用 gemini-3-pro-image-preview 模型基于参考图进行编辑。
        支持用户完全控制参考图列表，包括是否使用原素材图。

        Args:
            session_id: 会话ID
            image_index: 素材图索引（在 material_images 列表中的位置）
            prompt: 编辑/生成提示词（用于图生图的指令）
            description: 素材图描述（用于后续步骤生成首尾帧时参考），可选
            reference_images: 用户选择的参考图路径列表（可选），用于图生图编辑
            original_image_path: 原素材图路径（可选），当reference_images为空时作为保底使用

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 编辑素材图 {image_index} - 会话: {session_id[:8]}...")
        logger.info(f"[编辑] 提示词: {prompt[:100]}...")
        if reference_images:
            logger.info(f"[编辑] 使用 {len(reference_images)} 张用户选择的参考图")

        try:
            # 获取素材图数据和视频参数
            material_result = self.session_manager.get_step_result(session_id, "generate_material_images")
            script_result = self.session_manager.get_step_result(session_id, "optimize_script")

            if not material_result or not script_result:
                return {"success": False, "error": "缺少必要的步骤数据"}

            material_images = material_result['result_data'].get('material_images', [])
            params = script_result['result_data']['video_params']

            if image_index < 0 or image_index >= len(material_images):
                return {"success": False, "error": f"无效的图片索引: {image_index}"}

            # 获取原素材图信息
            original_image = material_images[image_index]
            db_original_path = original_image.get('image_path', '')

            # 确定最终使用的原图路径
            final_original_path = original_image_path or db_original_path

            if not final_original_path:
                return {"success": False, "error": "原始图片路径不存在"}

            video_params = VideoParams(**params)

            # 使用 ImageService 编辑图片（直接使用完整提示词）
            result = await self.image_service.edit_material_image(
                original_image_path=final_original_path,
                prompt=prompt,
                video_params=video_params,
                reference_images=reference_images
            )

            if not result.get("success"):
                return {"success": False, "error": result.get("error", "编辑失败")}

            new_image_url = result.get("image_url", "")

            update_data = {
                "image_path": new_image_url,
                "prompt": prompt,
                "task_id": "",
                "task_status": "completed"
            }
            # 如果用户提供了描述，则更新描述字段
            if description is not None:
                update_data["description"] = description

            success = self.session_manager.update_material_image(
                session_id, image_index, update_data
            )

            if success:
                return {
                    "success": True,
                    "message": f"素材图 {image_index + 1} 已编辑完成",
                    "image_path": new_image_url
                }
            else:
                return {"success": False, "error": "更新素材图信息失败"}

        except Exception as e:
            logger.error(f"编辑素材图失败: {e}")
            return {"success": False, "error": f"编辑素材图失败: {str(e)}"}

    async def add_material_image(
        self,
        session_id: str,
        prompt: str,
        description: str | None = None,
        reference_images: list[str] | None = None
    ) -> dict:
        """新增一个素材图

        使用 gemini-3-pro-image-preview 模型生成新的素材图并添加到列表末尾。
        支持纯文生图模式和图生图模式（提供参考图时）。

        Args:
            session_id: 会话ID
            prompt: 生成提示词，描述想要生成的素材图
            description: 素材图描述（可选）
            reference_images: 参考图路径列表（可选），用于图生图生成

        Returns:
            执行结果，包含 success, message, image_path, index
        """
        logger.info(f"[新增] 新增素材图 - 会话: {session_id[:8]}...")
        logger.info(f"[新增] 提示词: {prompt[:100]}...")
        if reference_images:
            logger.info(f"[新增] 使用 {len(reference_images)} 张参考图")

        try:
            # 获取素材图数据和视频参数
            material_result = self.session_manager.get_step_result(session_id, "generate_material_images")
            script_result = self.session_manager.get_step_result(session_id, "optimize_script")

            if not material_result or not script_result:
                return {"success": False, "error": "缺少必要的步骤数据"}

            material_images = material_result['result_data'].get('material_images', [])
            params = script_result['result_data']['video_params']
            video_params = VideoParams(**params)

            # 构建生成提示词（保持设定稿风格）
            full_prompt = f"""生成一张设计参考图/设定稿: {prompt}

要求:
- 高质量、细节丰富的设定稿/概念设计
- 清晰展示角色/物品/场景的设计细节
- 保持设定稿风格：如有身高比例尺、尺寸标注、多角度展示等设计稿元素，应当保留
- 输出专业的设计参考图/设定稿"""

            # 判断是否有参考图，决定使用文生图还是图生图
            if reference_images and len(reference_images) > 0:
                # 有参考图：使用图生图模式（gemini-3-pro-image-preview）
                logger.info(f"[新增] 使用图生图模式（gemini-3-pro-image-preview），参考图: {len(reference_images)} 张")
                result = await self.image_service.edit_material_image(
                    original_image_path=reference_images[0],  # 第一张参考图作为原图
                    prompt=full_prompt,
                    video_params=video_params,
                    reference_images=reference_images
                )
            else:
                # 无参考图：使用文生图模式（gemini-3-pro-image-preview）
                logger.info(f"[新增] 使用纯文生图模式（gemini-3-pro-image-preview）")
                result = await self.image_service._generate_image(
                    prompt=full_prompt,
                    video_params=video_params
                )

            if not result.get("success"):
                return {"success": False, "error": result.get("error", "生成失败")}

            new_image_url = result.get("image_url", "")

            # 创建新的素材图数据（包含 MaterialImage 所需的所有字段）
            # 注意：description 和 prompt 是两个不同的概念：
            # - prompt: 生成/编辑图片的指令
            # - description: 素材图的内容描述（用于后续步骤生成首尾帧时参考）
            new_material = {
                "image_id": str(uuid.uuid4()),
                "image_path": new_image_url,
                "prompt": prompt,
                "description": description or "",  # 不再用 prompt 填充，让用户明确提供描述
                "image_type": "general",
                "task_id": "",
                "task_status": "completed"
            }

            # 添加到素材图列表末尾
            material_images.append(new_material)
            new_index = len(material_images) - 1

            # 保存更新
            material_result['result_data']['material_images'] = material_images
            self.session_manager.save_step_result(
                session_id, "generate_material_images", material_result['result_data'], success=True
            )

            return {
                "success": True,
                "message": f"素材图已新增（索引: {new_index + 1}）",
                "image_path": new_image_url,
                "index": new_index
            }

        except Exception as e:
            logger.error(f"新增素材图失败: {e}")
            return {"success": False, "error": f"新增素材图失败: {str(e)}"}

    async def batch_regenerate_segments(
        self, session_id: str, segment_indices: list[int], extra_prompt: str = ""
    ) -> dict:
        """批量重新生成选中的分片

        Args:
            session_id: 会话ID
            segment_indices: 要重新生成的分片索引列表
            extra_prompt: 用户额外的自定义提示词

        Returns:
            包含 success 和 message 的字典
        """
        try:
            # 获取步骤1的结果（视频参数）
            step1_result = self.session_manager.get_step_result(session_id, "submit_script_and_params")
            if not step1_result:
                return {"success": False, "error": "未找到视频参数"}

            video_params_data = step1_result['result_data']['video_params']
            video_params = VideoParams(**video_params_data)

            # 获取步骤4的结果（所有分片）
            step4_result = self.session_manager.get_step_result(session_id, "generate_segment_scripts")
            if not step4_result:
                return {"success": False, "error": "未找到分片脚本"}

            result_data = step4_result['result_data']
            all_segments = result_data.get('segment_scripts', [])

            # 验证索引有效性
            if not all_segments:
                return {"success": False, "error": "当前没有分片脚本"}

            invalid_indices = [i for i in segment_indices if i < 0 or i >= len(all_segments)]
            if invalid_indices:
                return {"success": False, "error": f"无效的分片索引: {invalid_indices}"}

            # 转换为 ScriptSegment 对象
            segment_objects = [
                ScriptSegment(
                    index=seg.get('index', idx),
                    content=seg.get('content', ''),
                    duration=seg.get('duration', 5),
                    action=seg.get('action'),
                    camera_movement=seg.get('camera_movement'),
                    composition=seg.get('composition'),
                    focus=seg.get('focus'),
                    atmosphere=seg.get('atmosphere'),
                    transition=seg.get('transition'),
                    first_frame_mode=seg.get('first_frame_mode', 'generate'),
                    last_frame_mode=seg.get('last_frame_mode', 'generate')
                )
                for idx, seg in enumerate(all_segments)
            ]

            logger.info(f"批量重新生成分片，选中索引: {segment_indices}")

            # 调用 LLM Service 批量重新生成
            new_segments = await self.llm_service.batch_regenerate_segments(
                all_segments=segment_objects,
                selected_indices=segment_indices,
                video_params=video_params,
                extra_prompt=extra_prompt
            )

            # 构建新的分片列表：替换选中分片，保留未选中分片
            selected_indices_set = set(segment_indices)
            result_segments = []

            # 找到前一个未选中分片的索引（如果存在）
            prev_unselected_idx = None
            for i in range(min(segment_indices) - 1, -1, -1):
                if i not in selected_indices_set:
                    prev_unselected_idx = i
                    break

            # 找到后一个未选中分片的索引（如果存在）
            next_unselected_idx = None
            for i in range(max(segment_indices) + 1, len(segment_objects)):
                if i not in selected_indices_set:
                    next_unselected_idx = i
                    break

            # 添加选中区域之前的分片
            for i in range(min(segment_indices)):
                if i not in selected_indices_set:
                    seg = segment_objects[i]
                    # 如果是紧邻选中区域的前一个分片，更新其 last_frame_mode
                    if i == prev_unselected_idx and new_segments:
                        first_new_seg = new_segments[0]
                        if first_new_seg.first_frame_mode == "reuse_prev":
                            seg.last_frame_mode = "reuse_next"
                        else:
                            # 如果新分片不复用前一帧，前一分片也不应该复用
                            seg.last_frame_mode = "generate"
                    result_segments.append(seg)

            # 添加新生成的分片
            result_segments.extend(new_segments)

            # 添加选中区域之后的分片
            for i in range(max(segment_indices) + 1, len(segment_objects)):
                if i not in selected_indices_set:
                    seg = segment_objects[i]
                    # 如果是紧邻选中区域的后一个分片，更新其 first_frame_mode
                    if i == next_unselected_idx and new_segments:
                        last_new_seg = new_segments[-1]
                        if last_new_seg.last_frame_mode == "reuse_next":
                            seg.first_frame_mode = "reuse_prev"
                        else:
                            # 如果新分片不复用后一帧，后一分片也不应该复用
                            seg.first_frame_mode = "generate"
                    result_segments.append(seg)

            # 重新分配索引
            for idx, seg in enumerate(result_segments):
                seg.index = idx

            # 转换为字典格式保存
            segment_dicts = [
                {
                    "index": seg.index,
                    "content": seg.content,
                    "duration": seg.duration,
                    "action": seg.action,
                    "camera_movement": seg.camera_movement,
                    "composition": seg.composition,
                    "focus": seg.focus,
                    "atmosphere": seg.atmosphere,
                    "transition": seg.transition,
                    "first_frame_mode": seg.first_frame_mode,
                    "last_frame_mode": seg.last_frame_mode
                }
                for seg in result_segments
            ]

            # 更新步骤4的结果
            result_data['segment_scripts'] = segment_dicts
            result_data['segment_count'] = len(segment_dicts)

            self.session_manager.update_step_result(
                session_id, "generate_segment_scripts", result_data
            )

            # 清空后续步骤（步骤5、步骤6）
            self.session_manager.clear_steps_after(session_id, "generate_segment_scripts")

            logger.info(f"批量重新生成完成，原 {len(segment_indices)} 个分片变为 {len(new_segments)} 个分片，总分片数: {len(segment_dicts)}")

            return {
                "success": True,
                "message": f"批量重新生成成功：原 {len(segment_indices)} 个分片变为 {len(new_segments)} 个分片",
                "original_count": len(segment_indices),
                "new_count": len(new_segments),
                "total_count": len(segment_dicts)
            }

        except Exception as e:
            logger.error(f"批量重新生成分片失败: {e}")
            return {"success": False, "error": f"批量重新生成分片失败: {str(e)}"}

    # ==================== 私有辅助方法 ====================

    def _build_intermediate_frames(
        self,
        segment_scripts: list,
        generated_frames: dict,
        prompts_map: dict
    ) -> list[SegmentFrame]:
        """构建中间状态的帧数据列表

        用于在首尾帧生成过程中实时更新进度到数据库，让前端轮询时能看到单个帧的完成状态。

        Args:
            segment_scripts: 分片脚本列表
            generated_frames: 已生成的帧字典 {(seg_idx, frame_type): (image_id, image_path)}
            prompts_map: 提示词映射 {segment_index: (first_prompt, last_prompt)}

        Returns:
            SegmentFrame 对象列表
        """
        segment_frames = []
        for segment in segment_scripts:
            idx = segment.index
            first_prompt, last_prompt = prompts_map.get(idx, ("", ""))

            # 获取首帧
            if segment.first_frame_mode == "reuse_prev" and idx > 0:
                # 复用前一分片尾帧
                first_id, first_path = generated_frames.get((idx - 1, "last"), ("", ""))
            else:
                first_id, first_path = generated_frames.get((idx, "first"), ("", ""))

            # 获取尾帧
            last_id, last_path = generated_frames.get((idx, "last"), ("", ""))

            # 确定状态：completed（已完成）、pending（生成中）、failed（失败）
            # 如果有路径则为 completed，如果该帧在 generated_frames 中但路径为空则为 failed，否则为 pending
            if first_path:
                first_status = "completed"
            elif (idx, "first") in generated_frames or (segment.first_frame_mode == "reuse_prev" and (idx - 1, "last") in generated_frames):
                first_status = "failed" if not first_path else "pending"
            else:
                first_status = "pending"

            if last_path:
                last_status = "completed"
            elif (idx, "last") in generated_frames:
                last_status = "failed" if not last_path else "pending"
            else:
                last_status = "pending"

            segment_frames.append(SegmentFrame(
                segment_index=idx,
                first_image_id=first_id,
                first_image_path=first_path,
                last_image_id=last_id,
                last_image_path=last_path,
                first_prompt=first_prompt,
                last_prompt=last_prompt,
                first_status=first_status,
                last_status=last_status
            ))

        return segment_frames
