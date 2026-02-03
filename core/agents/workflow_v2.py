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

from core.models import (
    VideoParams,
    ScriptSegment,
    MaterialImage,
    SegmentFrame,
)
from core.config import SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP
from core.services import LLMService, ImageService, VideoService
from core.persistence import SessionManager

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
        """步骤5：生成首尾帧（并发+复用优化）

        优化策略:
        1. 并发生成所有需要的帧，大幅提升速度
        2. 相邻分片如果需要100%画面连续，复用帧而非重复生成

        Args:
            session_id: 会话ID
            extra_prompt: 自定义提示词，用于增加控制力（如：黄昏光线、俯拍角度等）

        Returns:
            执行结果
        """
        logger.info(f"[步骤5] 生成首尾帧（并发+复用优化）- 会话: {session_id[:8]}...")
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

        material_images = [MaterialImage(**img) for img in material_result['result_data']['material_images']]
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

            # ========== 2. 构建需要生成的帧任务列表（考虑复用） ==========
            pending_tasks = []  # 记录待生成的任务信息 (segment_index, frame_type, prompt)

            # 统计复用情况
            reuse_count = 0
            generate_count = 0

            for segment in segment_scripts:
                idx = segment.index
                first_prompt, last_prompt = prompts_map.get(idx, ("", ""))

                # 首帧处理
                if segment.first_frame_mode == "reuse_prev" and idx > 0:
                    # 标记为复用，不生成
                    reuse_count += 1
                    logger.info(f"[步骤5] 分片 {idx} 首帧将复用分片 {idx - 1} 的尾帧")
                else:
                    # 需要生成（使用图生图，传入素材图作为参考）
                    if first_prompt:
                        pending_tasks.append((idx, "first", first_prompt))
                        generate_count += 1

                # 尾帧处理（即使 reuse_next 也需要生成，因为是被复用方）
                if last_prompt:
                    pending_tasks.append((idx, "last", last_prompt))
                    generate_count += 1

            logger.info(f"[步骤5] 需要生成 {generate_count} 张帧图片，复用 {reuse_count} 张")

            # ========== 3. 间隔提交所有任务（并发执行） ==========
            logger.info(f"[步骤5] 开始提交 {len(pending_tasks)} 个图片生成任务（间隔 {SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP} 秒）...")
            submitted_tasks = []  # [(seg_idx, frame_type, request_id)]

            # 3.1 间隔提交所有任务
            for i, (seg_idx, frame_type, prompt) in enumerate(pending_tasks):
                # 间隔提交（第一个任务不需要等待）
                if i > 0:
                    await asyncio.sleep(SHENGSUANYUN_IMAGE2IMAGE_REQUEST_TIME_GAP)

                logger.info(f"[步骤5] 提交任务 {i + 1}/{len(pending_tasks)}: 分片 {seg_idx} {frame_type}帧")

                try:
                    # 构建提示词
                    i2i_prompt = self.image_service.build_frame_prompt(prompt, video_params, frame_type)
                    # 只提交任务，不等待完成
                    submit_result = await self.image_service.submit_i2i_task(
                        i2i_prompt,
                        material_image_urls,
                        video_params
                    )
                    if submit_result.get("success"):
                        request_id = submit_result["request_id"]
                        submitted_tasks.append((seg_idx, frame_type, request_id))
                        logger.info(f"[步骤5] 分片 {seg_idx} {frame_type}帧任务已提交: {request_id}")
                    else:
                        logger.error(f"[步骤5] 分片 {seg_idx} {frame_type}帧提交失败: {submit_result.get('error')}")
                        submitted_tasks.append((seg_idx, frame_type, None))
                except Exception as e:
                    logger.error(f"分片 {seg_idx} {frame_type}帧提交失败: {e}")
                    submitted_tasks.append((seg_idx, frame_type, None))

            logger.info(f"[步骤5] 所有任务已提交，开始并发轮询 {len(submitted_tasks)} 个任务...")

            # 3.2 并发轮询所有任务
            async def poll_task(seg_idx: int, frame_type: str, request_id: str | None):
                """轮询单个任务"""
                if not request_id:
                    return (seg_idx, frame_type, "error", "")
                try:
                    result = await self.image_service.poll_i2i_task(request_id)
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
            poll_tasks = [poll_task(seg_idx, frame_type, req_id) for seg_idx, frame_type, req_id in submitted_tasks]
            poll_results = await asyncio.gather(*poll_tasks)

            # 3.3 处理结果
            generated_frames = {}  # {(idx, type): (id, path)}
            error_count = 0

            for seg_idx, frame_type, image_id, image_path in poll_results:
                generated_frames[(seg_idx, frame_type)] = (image_id, image_path)
                if image_path:
                    logger.info(f"[步骤5] 分片 {seg_idx} {frame_type}帧生成成功")
                else:
                    logger.error(f"[步骤5] 分片 {seg_idx} {frame_type}帧生成失败")
                    error_count += 1

            # ========== 4. 处理结果已在上面完成 ==========

            # ========== 5. 构建最终 SegmentFrame 列表（处理复用） ==========
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

                segment_frames.append(SegmentFrame(
                    segment_index=idx,
                    first_image_id=first_id,
                    first_image_path=first_path,
                    last_image_id=last_id,
                    last_image_path=last_path,
                    first_prompt=first_prompt,
                    last_prompt=last_prompt
                ))

            # ========== 6. 保存结果 ==========
            result_data = {
                "segment_frames": [frame.model_dump() for frame in segment_frames],
                "frame_count": len(segment_frames),
                "generated_count": generate_count,
                "reused_count": reuse_count,
                "error_count": error_count
            }

            if error_count > 0:
                self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data, success=False)
                logger.error(f"[步骤5] 部分失败 - {error_count} 张帧生成失败")
                return {
                    "success": False,
                    "error": f"首尾帧生成部分失败：{error_count} 张图片生成失败",
                    "data": result_data
                }

            self.session_manager.save_step_result(session_id, "generate_segment_frames", result_data)
            logger.info(f"[步骤5] 完成 - 生成 {generate_count} 张，复用 {reuse_count} 张，共 {len(segment_frames)} 组首尾帧")

            return {
                "success": True,
                "message": f"已生成 {len(segment_frames)} 组首尾帧（生成 {generate_count} 张，复用 {reuse_count} 张）",
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

                videos.append(video)

            # 统计成功和失败
            success_count = sum(1 for v in videos if v.video_path and not v.video_path.startswith("生成失败"))
            failed_count = len(videos) - success_count

            # 保存结果
            result_data = {
                "generated_videos": [v.model_dump() for v in videos],
                "video_count": len(videos),
                "success_count": success_count,
                "failed_count": failed_count,
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
        from core.config import IMAGES_DIR

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
        custom_prompt: str = ""
    ) -> dict:
        """重新生成单个首/尾帧

        Args:
            session_id: 会话ID
            segment_index: 分片索引
            frame_type: 帧类型 ("first" 或 "last")
            custom_prompt: 自定义提示词，如果提供则使用此提示词，否则由LLM自动生成

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
                material_images = [MaterialImage(**img) for img in material_result['result_data'].get('material_images', [])]
                material_desc = "; ".join([img.description for img in material_images if img.description])
                material_image_urls = [
                    img.image_path for img in material_images
                    if img.image_path and img.task_status == "completed"
                ]

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

            # 生成单张图片（使用图生图，传入素材图作为参考）
            image_id, image_path = await self.image_service.generate_single_image(
                prompt,
                video_params,
                prefix=f"frame_{segment_index}_{frame_type}",
                reference_images=material_image_urls,  # 传入素材图作为参考
                frame_type=frame_type  # 传递帧类型，用于在提示词中强调
            )

            if not image_path:
                return {"success": False, "error": "图片生成失败"}

            # 更新数据库
            success = self.session_manager.update_segment_frame(
                session_id, segment_index, frame_type, image_path, image_id
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
        edit_prompt: str,
        reference_images: list[str] | None = None,
        original_image_path: str | None = None
    ) -> dict:
        """编辑单个素材图

        使用 gemini-3-pro-image-preview 模型基于参考图进行编辑。
        支持用户完全控制参考图列表，包括是否使用原素材图。

        Args:
            session_id: 会话ID
            image_index: 素材图索引（在 material_images 列表中的位置）
            edit_prompt: 编辑提示词，描述想要做的修改
            reference_images: 用户选择的参考图路径列表（可选），用于图生图编辑
            original_image_path: 原素材图路径（可选），当reference_images为空时作为保底使用

        Returns:
            执行结果
        """
        logger.info(f"[编辑] 编辑素材图 {image_index} - 会话: {session_id[:8]}...")
        logger.info(f"[编辑] 编辑提示词: {edit_prompt[:100]}...")
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

            # 获取原素材图信息（用于更新数据库）
            original_image = material_images[image_index]
            db_original_path = original_image.get('image_path', '')
            db_original_prompt = original_image.get('prompt', '')  # 获取原始提示词

            # 重复编辑时，先移除之前的编辑提示词部分，避免叠加
            # 只保留原始基础提示词部分，用于传给 image_service 和保存到数据库
            base_prompt = db_original_prompt
            if ' | 编辑: ' in base_prompt:
                base_prompt = base_prompt.split(' | 编辑: ')[0]

            # 确定最终使用的原图路径
            # 优先使用传入的original_image_path，否则使用数据库中的路径
            final_original_path = original_image_path or db_original_path

            if not final_original_path:
                return {"success": False, "error": "原始图片路径不存在"}

            video_params = VideoParams(**params)

            # 使用 ImageService 编辑图片
            # reference_images: 用户选择的参考图（可能包含也可能不包含原图）
            # original_image_path: 保底用的原图路径，当reference_images为空时使用
            # original_prompt: 清理后的原始生成提示词，用于保持上下文（不含之前的编辑历史）
            result = await self.image_service.edit_material_image(
                original_image_path=final_original_path,
                edit_prompt=edit_prompt,
                video_params=video_params,
                reference_images=reference_images,
                original_prompt=base_prompt  # 传递清理后的原始提示词
            )

            if not result.get("success"):
                return {"success": False, "error": result.get("error", "编辑失败")}

            new_image_url = result.get("image_url", "")

            update_data = {
                "image_path": new_image_url,
                "prompt": f"{base_prompt} | 编辑: {edit_prompt}",
                "task_status": "completed"
            }

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

        使用即梦 v40 模型（bytedance/jimeng_v40）生成新的素材图并添加到列表末尾。
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

            # 构建生成提示词
            full_prompt = f"""生成一张设计参考图: {prompt}

要求:
- 高质量、细节丰富的插画风格
- 清晰展示角色/物品/场景的设计细节
- 避免添加文字标注、标签、标尺或测量标记
- 输出干净的设计参考图"""

            # 判断是否有参考图，决定使用文生图还是图生图
            if reference_images and len(reference_images) > 0:
                # 有参考图：使用图生图模式（即梦 v40）
                logger.info(f"[新增] 使用图生图模式（即梦 v40），参考图: {len(reference_images)} 张")
                result = await self.image_service.edit_material_image(
                    original_image_path=reference_images[0],  # 第一张参考图作为原图
                    edit_prompt=prompt,
                    video_params=video_params,
                    reference_images=reference_images,
                    original_prompt=None  # 新增素材图没有原始提示词
                )
            else:
                # 无参考图：使用文生图模式（gpt-image-1.5）
                logger.info(f"[新增] 使用纯文生图模式（gpt-image-1.5）")
                result = await self.image_service._generate_image(
                    prompt=full_prompt,
                    video_params=video_params
                )

            if not result.get("success"):
                return {"success": False, "error": result.get("error", "生成失败")}

            new_image_url = result.get("image_url", "")

            # 创建新的素材图数据
            new_material = {
                "image_path": new_image_url,
                "prompt": prompt,
                "description": description or prompt[:50],
                "task_status": "completed",
                "task_id": None
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
