"""LLM服务 - 脚本优化/思维导图/分片/首尾帧提示词等 LLM 调用（模型由系统配置或模型管理默认 chat 模型决定）"""
import logging
import time
from openai import OpenAI

from backend.core.config import SHENGSUANYUN_API_KEY, SHENGSUANYUN_BASE_URL, SHENGSUANYUN_LLM_MODEL
from backend.core.models import VideoParams, ScriptSegment
from backend.core.utils.json_parser import parse_json_response
from backend.core.services.prompt_manager import get_prompt_manager

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务类"""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ):
        """初始化 LLM 服务

        Args:
            api_key: 可选 API Key（默认使用盛算云系统配置）
            base_url: 可选 OpenAI 兼容 Base URL（默认使用盛算云系统配置）
            model: 可选模型 ID（默认 doubao-seed-1.8；模型管理中设默认 chat 模型后由工作流注入）
        """
        self.client = OpenAI(
            base_url=base_url or SHENGSUANYUN_BASE_URL,
            api_key=api_key or SHENGSUANYUN_API_KEY,
        )
        self.model = model or SHENGSUANYUN_LLM_MODEL
        self.max_retries = 2
        self.retry_delay = 2  # 秒

    def _call_with_retry(self, prompt: str, temperature: float, operation_name: str, max_tokens: int = 16384) -> str:
        """带重试机制的API调用

        Args:
            prompt: 提示词
            temperature: 温度参数
            operation_name: 操作名称（用于日志）
            max_tokens: 最大输出 token 数，默认 16384

        Returns:
            响应文本

        Raises:
            Exception: 所有重试失败后抛出异常
        """
        last_error = None

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    logger.info(f"重试 {operation_name}... (第 {attempt + 1}/{self.max_retries} 次)")

                logger.info(f"[LLM] 使用模型: {self.model}")
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=temperature,
                    top_p=0.7,
                    max_tokens=max_tokens,
                    stream=True,
                )

                response_text = ""
                for chunk in completion:
                    if chunk.choices and chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        response_text += content

                # 空响应视为可重试错误（部分网关/思考型模型间歇性返回空流）
                if not response_text.strip():
                    raise Exception("empty stream response (响应文本为空)")

                if attempt > 0:
                    logger.info(f"{operation_name} 重试成功")

                return response_text

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 判断是否是可重试的错误
                is_retryable = any(keyword in error_msg.lower() for keyword in [
                    'ssl', 'connection', 'timeout', 'eof', 'network', 'empty stream response'
                ])

                if not is_retryable or attempt == self.max_retries - 1:
                    # 不可重试的错误或已达到最大重试次数
                    logger.error(f"{operation_name} 失败: {error_msg}")
                    raise

                logger.warning(f"{operation_name} 遇到网络错误: {error_msg}")

                # 等待后重试
                if attempt < self.max_retries - 1:
                    delay = self.retry_delay * (attempt + 1)  # 递增延迟
                    logger.info(f"等待 {delay} 秒后重试...")
                    time.sleep(delay)

        # 理论上不会到这里，因为上面的循环会抛出异常
        raise last_error

    async def optimize_long_script(
        self,
        original_script: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> str:
        """优化视频长脚本（总脚本），不生成分片

        Args:
            original_script: 原始脚本
            video_params: 视频参数
            extra_prompt: 额外的提示词，用于增加控制力（如：更多动作细节、特定风格等）
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在优化脚本时充分考虑以上要求。"

        # 提示词模板外置于 backend/prompts/optimize_script.md，可在网页上编辑
        prompt = get_prompt_manager().render("optimize_script", {
            "video_params_context": video_params.to_prompt_context(),
            "original_script": original_script,
            "extra_instruction": extra_instruction,
            "max_segment_duration": video_params.max_segment_duration,
        })

        logger.info("调用 LLM 优化脚本...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name="优化脚本")
        logger.info("脚本优化完成")
        return response_text.strip()

    async def generate_mindmap(
        self,
        optimized_script: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> str:
        """基于优化后的脚本生成剧本结构思维导图（markdown 层级文本）

        思维导图以 markdown 标题层级表达剧本结构，供前端 markmap 渲染，
        也作为后续素材图生成的结构化依据。

        Args:
            optimized_script: 优化后的脚本
            video_params: 视频参数
            extra_prompt: 额外的提示词

        Returns:
            思维导图 markdown 文本（# 标题为根，## 为分支，### 为子分支，- 为要点）
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成思维导图时充分考虑以上要求。"

        # 提示词模板外置于 backend/prompts/mindmap.md，可在网页上编辑
        prompt = get_prompt_manager().render("mindmap", {
            "video_params_context": video_params.to_prompt_context(),
            "optimized_script": optimized_script,
            "extra_instruction": extra_instruction,
        })

        logger.info("调用 LLM 生成剧本思维导图...")
        response_text = self._call_with_retry(prompt, temperature=0.5, operation_name="生成思维导图")
        mindmap = response_text.strip()

        # 去除 LLM 可能附加的代码块围栏
        if mindmap.startswith("```"):
            lines = mindmap.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            mindmap = "\n".join(lines).strip()

        logger.info(f"思维导图生成完成（{len(mindmap)} 字符）")
        return mindmap

    async def generate_segment_scripts(
        self,
        optimized_script: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> list[ScriptSegment]:
        """基于优化后的总脚本生成分片脚本（使用盛算云 API）

        提示词模板外置于 backend/prompts/segment_scripts.md，可在网页上编辑。

        Args:
            optimized_script: 优化后的脚本
            video_params: 视频参数
            extra_prompt: 额外的提示词，用于增加控制力
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成分片时充分考虑以上要求。"

        prompt = get_prompt_manager().render("segment_scripts", {
            "video_params_context": video_params.to_prompt_context(),
            "optimized_script": optimized_script,
            "extra_instruction": extra_instruction,
            "max_segment_duration": video_params.max_segment_duration,
        })

        logger.info("调用 LLM 生成分片脚本...")
        # 分片脚本生成需要较大的输出空间，使用 16384 tokens
        response_text = self._call_with_retry(prompt, temperature=0.6, operation_name="生成分片脚本", max_tokens=26384)

        # 添加调试日志，查看LLM返回的内容
        logger.debug(f"LLM原始响应: {response_text[:500]}...")

        result = parse_json_response(response_text)
        segments = [ScriptSegment(**seg) for seg in result.get("segments", [])]

        # 校验并修正首尾帧模式
        segments = self._validate_frame_modes(segments)

        logger.info(f"生成 {len(segments)} 个分片脚本")

        return segments

    def _validate_frame_modes(self, segments: list[ScriptSegment]) -> list[ScriptSegment]:
        """校验并修正首尾帧模式，确保边界条件正确

        有效的 first_frame_mode: "generate", "generate_continuous", "reuse_prev", "use_video_snapshot", "all_reference"
        有效的 last_frame_mode: "generate", "generate_continuous", "reuse_next", "all_reference"
        """
        if not segments:
            return segments

        valid_first_modes = {"generate", "generate_continuous", "reuse_prev", "use_video_snapshot", "all_reference"}
        valid_last_modes = {"generate", "generate_continuous", "reuse_next", "all_reference"}

        # 规范化无效值
        for segment in segments:
            if segment.first_frame_mode not in valid_first_modes:
                segment.first_frame_mode = "generate"
            if segment.last_frame_mode not in valid_last_modes:
                segment.last_frame_mode = "generate"

        # 第一个分片首帧必须是 generate（不能复用、连续或使用视频快照）
        if segments[0].first_frame_mode in ("reuse_prev", "generate_continuous", "use_video_snapshot"):
            segments[0].first_frame_mode = "generate"

        # 最后一个分片尾帧必须是 generate（不能被复用或标记连续）
        if segments[-1].last_frame_mode in ("reuse_next", "generate_continuous"):
            segments[-1].last_frame_mode = "generate"

        # 确保复用模式的一致性（reuse_prev 和 reuse_next 必须配对）
        for i, segment in enumerate(segments):
            # 如果当前分片首帧是复用前一分片，那么前一分片尾帧应该标记为被复用
            if segment.first_frame_mode == "reuse_prev" and i > 0:
                segments[i - 1].last_frame_mode = "reuse_next"

            # 如果当前分片尾帧是被复用，那么下一分片首帧应该标记为复用
            if segment.last_frame_mode == "reuse_next" and i < len(segments) - 1:
                segments[i + 1].first_frame_mode = "reuse_prev"

        # 确保 generate_continuous 的一致性（双向标记）
        for i, segment in enumerate(segments):
            # 如果当前首帧需要连续，前一分片尾帧也应该标记为连续（如果不是reuse）
            if segment.first_frame_mode == "generate_continuous" and i > 0:
                if segments[i - 1].last_frame_mode == "generate":
                    segments[i - 1].last_frame_mode = "generate_continuous"

            # 如果当前尾帧标记为连续，下一分片首帧也应该标记为连续（如果不是reuse）
            if segment.last_frame_mode == "generate_continuous" and i < len(segments) - 1:
                if segments[i + 1].first_frame_mode == "generate":
                    segments[i + 1].first_frame_mode = "generate_continuous"

        return segments

    async def generate_material_prompts(
        self,
        mindmap_markdown: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> list[dict]:
        """生成素材图片的提示词（基于剧本结构思维导图）

        生成"设定稿"风格的素材图，包含：
        1. 角色设定图：所有角色的多角度展示，带身高比例尺
        2. 物品设定图：重要道具/物品，带尺寸标注
        3. 场景设定图：主要场景的概览

        Args:
            mindmap_markdown: 剧本结构思维导图（markdown 层级文本，步骤3产物）
            video_params: 视频参数
            extra_prompt: 额外的提示词，用于增加控制力（如：更鲜艳的颜色、卡通风格等）
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成素材图提示词时充分体现以上要求，将这些要求融入到每个 prompt 中。"

        prompt = f"""你是一个专业的动画/影视概念设计师。请根据以下剧本结构思维导图，生成"设定稿/角色设定表"风格的素材图提示词。

{video_params.to_prompt_context()}

剧本结构思维导图（markdown 层级）:
{mindmap_markdown}{extra_instruction}

## 任务说明
基于思维导图中的角色设定、场景设定、道具设定分支，生成2-6张"设定稿/角色设定表"风格的素材图提示词。
思维导图中的视觉要点（外貌/服装/环境/光线/材质描述）应直接融入对应素材图的 prompt。

## 任务说明
分析脚本中出现的所有视觉元素，生成2-6张"设定稿/角色设定表"风格的素材图提示词。

⚠️ **重要提示**：素材图必须是"设定稿"风格！
- 必须包含：身高比例尺、尺寸标注、多角度展示、设计说明等设计稿元素，标注语言必须为中文
- 这些元素是素材图的核心特征，用于确保后续首尾帧生成时的角色/物品一致性
- 无论是否有参考图（文生图或图生图），都必须保持设定稿风格

### 素材图类型及要求：

**⚠️ 核心原则：素材图必须是"设定稿/角色设定表"风格！**
- 必须包含：身高比例尺、尺寸标注、多角度展示（正面/侧面/背面）、设计说明
- 这些设计稿元素是素材图的核心特征，用于确保后续生成的一致性
- 无论是否有参考图，都必须保持设定稿风格

**1. 主要角色设定图（type: "character_main"）**
- 展示脚本中所有**主要角色**（主角、重要配角）
- 必须包含：多角度展示（正面/侧面/背面）、身高比例尺、外貌特征标注
- 描述：外貌特征、服装、发型、表情、姿态
- 使用中文术语："角色设定稿"、"多角度展示"、"身高比例尺"

**2. 边缘角色设定图（type: "character_minor"）** *(如需要)*
- 展示脚本中的**次要角色**（龙套、背景人物、群众）
- 可简化为单角度，但仍需设定稿风格
- 如果次要角色很少或不重要，可省略此项

**3. 物品/道具设定图（type: "props"）** *(如需要)*
- 展示脚本中出现的**重要物品、道具、工具**
- 必须包含：尺寸标注、多角度展示、材质说明
- 描述：外观、材质、特征、功能
- 使用中文术语："道具设定稿"、"尺寸标注"、"多角度展示"
- 如果物品很少或不重要，可省略此项

**4. 主场景设定图（type: "environment_main"）** *(如需要)*
- 展示脚本中**最主要的场景**（核心场景、主场地）
- 包含：空间布局示意、比例参考、关键区域标注
- 描述：空间布局、光线、氛围、色调、关键元素
- 使用中文术语："场景概念设定稿"、"布局概览"

**5. 副场景设定图（type: "environment_minor"）** *(如需要)*
- 展示脚本中的**次要场景**（过渡场景、背景场景）
- 简化描述，但保持设定稿风格
- 如果副场景不重要，可省略此项

### 返回JSON格式示例:
{{
    "prompts": [
        {{
            "type": "character_main",
            "prompt": "[主角名称]的角色设定稿，多角度展示（正面、侧面、背面），[外貌描述]，[服装描述]，侧边带身高比例尺，角色设计参考图，白色背景",
            "description": "主要角色：[角色名称]，[简短描述]"
        }},
        {{
            "type": "character_minor",
            "prompt": "次要角色设定稿，[配角描述]，简化的多角度展示，身高对比图，白色背景",
            "description": "边缘角色：[角色列表]"
        }},
        {{
            "type": "props",
            "prompt": "道具设定稿：[物品描述]，多角度展示，带尺寸标注，[材质和外观]，详细的正交视图，白色背景",
            "description": "重要道具：[物品列表]"
        }},
        {{
            "type": "environment_main",
            "prompt": "场景概念设定稿：[场景描述]，带比例参考的布局概览，[光线和氛围]，关键区域标注",
            "description": "主场景：[场景名称]"
        }},
        {{
            "type": "environment_minor",
            "prompt": "副场景设计稿：[副场景描述]，简化布局，背景参考图",
            "description": "副场景：[场景名称]"
        }}
    ]
}}

### 重要要求:
1. **必须使用全中文描述**，不要使用任何英文
2. **根据脚本实际情况选择类型**：
   - 至少包含1张（通常是主要角色或主场景）
   - 最多5张（覆盖所有类型）
   - 如果某类型元素不存在或不重要，直接省略
3. **必须保持设定稿风格**（无论是否有参考图）：
   - 必须使用"角色设定稿"、"设计稿"、"多角度展示"等设定稿术语
   - 必须包含"身高比例尺"、"尺寸标注"、"多角度"等标注元素
   - 角色图必须包含多角度展示（正面/侧面/背面）
   - 物品图必须包含尺寸标注
4. **确保描述清晰具体**：包含足够的细节让AI理解要生成什么
5. **仅返回JSON**，不要有其他文字"""

        logger.info("调用 LLM 生成素材图提示词...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name="生成素材图提示词")

        # 解析 JSON 响应
        result = parse_json_response(response_text, default={})
        prompts_data = result.get("prompts", [])

        # 如果解析失败或没有 prompts 数据，生成一个基础的默认提示词
        if not prompts_data:
            logger.warning("无法解析素材图提示词JSON，使用默认提示词")
            # 使用简化的默认提示词，而不是原始响应文本
            prompts_data = [{
                "prompt": f"高质量的场景设定稿，细节丰富，专业设计",
                "description": "默认素材图"
            }]

        prompts = [
            {
                "prompt": p.get("prompt", "").strip(),
                "description": p.get("description", "").strip(),
                "type": p.get("type", "general").strip()  # 保留 type 字段
            }
            for p in prompts_data
            if p.get("prompt", "").strip()  # 只保留有有效 prompt 的项
        ]

        # 如果过滤后没有有效 prompt，使用默认值
        if not prompts:
            prompts = [{
                "prompt": f"高质量的场景设定稿，细节丰富，专业设计",
                "description": "默认素材图",
                "type": "general"
            }]

        logger.info(f"生成 {len(prompts)} 个素材图提示词")

        return prompts

    async def generate_frame_prompts(
        self,
        segment: ScriptSegment,
        video_params: VideoParams,
        material_description: str,
        prev_segment: ScriptSegment | None = None,
        next_segment: ScriptSegment | None = None,
        extra_prompt: str = ""
    ) -> tuple[str, str]:
        """生成分镜头首尾帧的提示词（用于图生图模式）

        Args:
            segment: 当前分片脚本
            video_params: 视频参数
            material_description: 素材图描述
            prev_segment: 前一个分片脚本（用于保持首帧与前一分片尾帧的连贯性）
            next_segment: 后一个分片脚本（用于保持尾帧与后一分片首帧的连贯性）
            extra_prompt: 额外的提示词，用于增加控制力（如：黄昏光线、俯拍角度等）
        """
        # 构建连贯性提示（仅供LLM参考，不要求出现在最终提示词中）
        continuity_hint = ""
        if prev_segment:
            continuity_hint += f"【参考-首帧连贯性】前一分片结束状态: {prev_segment.action}，氛围: {prev_segment.atmosphere}\n"
        if next_segment:
            continuity_hint += f"【参考-尾帧连贯性】后一分片开始状态: {next_segment.action}，氛围: {next_segment.atmosphere}\n"

        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n用户额外要求: {extra_prompt}"

        # 提示词模板外置于 backend/prompts/frame_prompts.md，可在网页上编辑
        prompt = get_prompt_manager().render("frame_prompts", {
            "aspect_ratio": video_params.aspect_ratio,
            "segment_content": segment.content,
            "segment_action": segment.action,
            "segment_composition": segment.composition,
            "segment_atmosphere": segment.atmosphere,
            "material_description": material_description,
            "continuity_hint": continuity_hint,
            "extra_instruction": extra_instruction,
        })

        logger.info(f"调用 LLM 生成分片 {segment.index} 首尾帧提示词...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name=f"生成分片{segment.index}首尾帧提示词")

        result = parse_json_response(response_text)
        logger.info(f"分片 {segment.index} 首尾帧提示词生成完成")

        return result.get("first_frame", ""), result.get("last_frame", "")

    async def batch_regenerate_segments(
        self,
        all_segments: list[ScriptSegment],
        selected_indices: list[int],
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> list[ScriptSegment]:
        """批量重新生成选中的分片脚本

        Args:
            all_segments: 所有分片列表
            selected_indices: 要重新生成的分片索引列表
            video_params: 视频参数
            extra_prompt: 用户额外的自定义提示词

        Returns:
            重新生成后的分片列表（数量可能变化）
        """
        # 提取上下文：选中分片前后的未选中分片
        selected_indices_set = set(selected_indices)

        # 找到选中区域的前一个未选中分片（上文）
        prev_context = None
        for i in range(min(selected_indices) - 1, -1, -1):
            if i not in selected_indices_set:
                prev_context = all_segments[i]
                break

        # 找到选中区域的后一个未选中分片（下文）
        next_context = None
        for i in range(max(selected_indices) + 1, len(all_segments)):
            if i not in selected_indices_set:
                next_context = all_segments[i]
                break

        # 获取选中分片的内容
        selected_segments = [all_segments[i] for i in sorted(selected_indices)]
        selected_content = "\n\n".join([
            f"分片{seg.index + 1}: {seg.content} (时长: {seg.duration}秒)"
            for seg in selected_segments
        ])

        # 构建上下文说明
        context_info = ""
        if prev_context:
            context_info += f"\n\n【前文上下文】（保持连贯）\n前一个分片内容: {prev_context.content}\n（新生成的第一个分片应该自然承接这个内容）"

        if next_context:
            context_info += f"\n\n【后文上下文】（保持连贯）\n后一个分片内容: {next_context.content}\n（新生成的最后一个分片应该自然过渡到这个内容）"

        # 构建用户自定义要求
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户特别要求\n{extra_prompt}\n请在重新生成分片时严格遵循以上要求。"

        prompt = f"""你是一个专业的视频分镜专家。用户选中了以下分片，希望重新生成这部分内容。

{video_params.to_prompt_context()}

【当前选中的分片】:
{selected_content}{context_info}{extra_instruction}

请基于以上信息，重新生成这部分的分片脚本。注意：
1. 你可以改变分片数量（增加或减少），以更好地表达内容
2. 每个分片时长不超过{video_params.max_segment_duration}秒
3. 如果有上下文，确保新生成的分片能够自然承接前文和后文
4. 保持与整体视频参数一致的风格和氛围
5. 为每个分片设计详细的拍摄参数

请以JSON格式返回结果:
{{
    "segments": [
        {{
            "content": "分片的具体内容描述",
            "duration": {video_params.max_segment_duration},
            "action": "角色或物体的动作描述",
            "camera_movement": "相机运动方式(如: 缓慢推进、横移、俯拍等)",
            "composition": "构图方式(如: 中心构图、三分法、对角线等)",
            "focus": "对焦和镜头效果(如: 浅景深、全景深、柔焦等)",
            "atmosphere": "氛围描述(如: 温馨、紧张、神秘等)",
            "transition": "与下一分片的转场方式(如: 淡入淡出、切换、溶解等)",
            "first_frame_mode": "generate 或 reuse_prev",
            "last_frame_mode": "generate 或 reuse_next"
        }}
    ]
}}

首尾帧生成模式（三种选择）:
1. first_frame_mode:
   - "generate": 全新生成，与前一分片无关联
   - "generate_continuous": 需要生成，但要与前一分片尾帧保持视觉连贯
   - "reuse_prev": 100%复用前一分片尾帧
2. last_frame_mode:
   - "generate": 全新生成
   - "generate_continuous": 需要生成，但后一分片首帧会参考此帧保持连贯
   - "reuse_next": 此帧会被下一分片100%复用

只返回JSON，不要有任何其他说明。"""

        logger.info(f"批量重新生成 {len(selected_indices)} 个分片...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name="批量重新生成分片")

        result = parse_json_response(response_text)
        segments_data = result.get("segments", [])

        # 转换为 ScriptSegment 对象（不设置 index，由调用方重新分配）
        new_segments = []
        for seg_data in segments_data:
            segment = ScriptSegment(
                index=0,  # 临时索引，后续会重新分配
                content=seg_data.get("content", ""),
                duration=seg_data.get("duration", video_params.max_segment_duration),
                action=seg_data.get("action"),
                camera_movement=seg_data.get("camera_movement"),
                composition=seg_data.get("composition"),
                focus=seg_data.get("focus"),
                atmosphere=seg_data.get("atmosphere"),
                transition=seg_data.get("transition"),
                first_frame_mode=seg_data.get("first_frame_mode", "generate"),
                last_frame_mode=seg_data.get("last_frame_mode", "generate")
            )
            new_segments.append(segment)

        logger.info(f"批量重新生成完成，原 {len(selected_segments)} 个分片变为 {len(new_segments)} 个分片")
        return new_segments

    async def optimize_segment_prompt_with_images(
        self,
        first_frame_path: str,
        last_frame_path: str,
        optimized_script: str,
        video_params: VideoParams,
        current_segment: ScriptSegment,
        custom_requirement: str = ""
    ) -> str:
        """基于首尾帧图片和上下文优化分片提示词

        使用多模态能力分析首尾帧图片，结合脚本和参数，生成优化的分片文案。

        Args:
            first_frame_path: 首帧图片路径（本地路径或URL）
            last_frame_path: 尾帧图片路径（本地路径或URL）
            optimized_script: 优化后的总脚本（第二步产物）
            video_params: 视频参数
            current_segment: 当前分片脚本
            custom_requirement: 用户自定义要求

        Returns:
            优化后的分片提示词文案
        """
        import base64
        import os

        def encode_image_to_base64(image_path: str) -> str | None:
            """将图片转换为 base64 编码"""
            if not image_path:
                return None

            # 如果是URL，直接返回URL
            if image_path.startswith('http://') or image_path.startswith('https://'):
                return None  # 返回None表示使用URL模式

            # 处理相对路径
            if not os.path.isabs(image_path):
                # 尝试从项目根目录解析
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
                image_path = os.path.join(project_root, image_path)

            if not os.path.exists(image_path):
                logger.warning(f"图片文件不存在: {image_path}")
                return None

            try:
                with open(image_path, "rb") as f:
                    return base64.b64encode(f.read()).decode("utf-8")
            except Exception as e:
                logger.error(f"读取图片失败: {e}")
                return None

        def get_image_url(image_path: str) -> str | None:
            """获取图片URL（如果是网络图片）"""
            if image_path and (image_path.startswith('http://') or image_path.startswith('https://')):
                return image_path
            return None

        # 构建图片消息内容
        content_parts = []

        # 首帧图片
        first_frame_base64 = encode_image_to_base64(first_frame_path)
        first_frame_url = get_image_url(first_frame_path)
        if first_frame_base64:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{first_frame_base64}"}
            })
        elif first_frame_url:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": first_frame_url}
            })

        # 尾帧图片
        last_frame_base64 = encode_image_to_base64(last_frame_path)
        last_frame_url = get_image_url(last_frame_path)
        if last_frame_base64:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{last_frame_base64}"}
            })
        elif last_frame_url:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": last_frame_url}
            })

        # 构建自定义要求部分
        custom_instruction = ""
        if custom_requirement:
            custom_instruction = f"\n\n## 用户特别要求\n{custom_requirement}\n请在生成分片文案时严格遵循以上要求。"

        # 构建文本提示
        text_prompt = f"""你是一个专业的视频分镜脚本优化专家。请仔细分析以下首帧和尾帧图片，结合视频脚本和参数，生成优化的分镜脚本文案。

## 视频参数
{video_params.to_prompt_context()}

## 优化后的总脚本（上下文参考）
{optimized_script[:2000]}{"..." if len(optimized_script) > 2000 else ""}

## 当前分片信息
- 分片索引：{current_segment.index + 1}
- 时长：{current_segment.duration} 秒（重要！生成的内容必须能在这个时长内完成）
- 当前原始视频脚本内容：{current_segment.content}
- 动作：{current_segment.action or '未指定'}
- 镜头运动：{current_segment.camera_movement or '未指定'}
- 构图：{current_segment.composition or '未指定'}
- 氛围：{current_segment.atmosphere or '未指定'}

## 用户自定义要求
{custom_instruction}

## 任务
请分析上面的两张图片：
1. 第一张是首帧图片，代表这个分片的开始画面
2. 第二张是尾帧图片，代表这个分片的结束画面

基于图片内容和上下文，生成一个优化的分镜脚本文案，要求：
1. **准确描述图片中的实际内容**（人物、场景、动作、氛围等）
2. **确保动作/变化能在 {current_segment.duration} 秒内由首帧过渡到尾帧并完成**（这是关键！）
3. **保持与总脚本风格一致**
4. **提供详细的镜头参数建议**

## 输出格式
请直接输出优化后的分片文案，格式如下：

**内容**：[描述这个镜头的具体内容，包括画面中的人物、场景、动作变化]

**动作**：[角色/物体的具体动作]

**镜头运动**：[推荐的镜头运动方式]

**构图**：[推荐的构图方式]

**氛围**：[画面的情感氛围]

直接输出以上内容，不要有其他说明。"""

        # 添加文本部分
        content_parts.append({"type": "text", "text": text_prompt})

        logger.info(f"调用 LLM 优化分片 {current_segment.index} 的提示词（含图片分析）...")

        try:
            # 使用多模态消息格式
            completion = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content_parts}],
                temperature=0.7,
                top_p=0.7,
                max_tokens=2048,
                stream=True,
            )

            response_text = ""
            for chunk in completion:
                if chunk.choices and chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    response_text += content

            logger.info(f"分片 {current_segment.index} 提示词优化完成")
            return response_text.strip()

        except Exception as e:
            logger.error(f"优化分片提示词失败: {e}")
            raise
