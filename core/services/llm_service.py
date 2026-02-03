"""LLM服务 - 使用盛算云 doubao-seed-1.8 进行脚本优化"""
import logging
import time
from openai import OpenAI

from core.config import SHENGSUANYUN_API_KEY, SHENGSUANYUN_BASE_URL
from core.models import VideoParams, ScriptSegment
from core.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务类"""

    def __init__(self):
        self.client = OpenAI(
            base_url=SHENGSUANYUN_BASE_URL,
            api_key=SHENGSUANYUN_API_KEY,
        )
        self.model = "bytedance/doubao-seed-1.8"
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

                if attempt > 0:
                    logger.info(f"{operation_name} 重试成功")

                return response_text

            except Exception as e:
                last_error = e
                error_msg = str(e)

                # 判断是否是可重试的错误
                is_retryable = any(keyword in error_msg.lower() for keyword in [
                    'ssl', 'connection', 'timeout', 'eof', 'network'
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

        prompt = f"""你是一个专业的视频脚本优化专家。请根据以下原始脚本和视频参数，优化并生成高质量的视频总脚本。

{video_params.to_prompt_context()}

原始脚本:
{original_script}{extra_instruction}

请完成以下任务:
1. 优化原始脚本，极大地丰富细节，使其更适合视频制作
2. 设计8秒以内的转场，保障场景之间的连贯性
3. 增强视觉描述，包括场景、动作、氛围等
4. 确保整体风格与指定的美学风格一致

注意：
- 这是总脚本优化，不需要分片
- 重点是丰富细节和提升质量
- 保持原有的故事线和核心内容

请直接返回优化后的完整脚本文本，不要JSON格式，不要其他说明。"""

        logger.info("调用 LLM 优化脚本...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name="优化脚本")
        logger.info("脚本优化完成")
        return response_text.strip()

    async def generate_segment_scripts(
        self,
        optimized_script: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> list[ScriptSegment]:
        """基于优化后的总脚本生成分片脚本（使用盛算云 API）

        Args:
            optimized_script: 优化后的脚本
            video_params: 视频参数
            extra_prompt: 额外的提示词，用于增加控制力
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成分片时充分考虑以上要求。"

        prompt = f"""你是一个专业的视频分镜专家。请根据以下优化后的视频脚本，生成详细的分片脚本。

{video_params.to_prompt_context()}

完整脚本:
{optimized_script}{extra_instruction}

基于“完整脚本”将脚本分割成多个分片，每个分片时长不超过8秒，不要过度分片，保障内容密度高，并为每个分片设计详细的拍摄参数。

请以JSON格式返回结果:
{{
    "segments": [
        {{
            "index": 0,
            "content": "分片的具体内容描述",
            "duration": 6.0,
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

重要 - 首尾帧复用策略:
对于每个分片，判断是否需要画面连续:
1. first_frame_mode:
   - "reuse_prev": 当前分片与前一分片需要100%画面连续(如同一场景的连续动作)
   - "generate": 发生场景切换、视角大变化、或是第一个分片

2. last_frame_mode:
   - "reuse_next": 下一分片需要复用当前尾帧实现画面连续
   - "generate": 下一分片不复用或是最后一个分片

注意:
- 第一个分片的 first_frame_mode 必须是 "generate"
- 最后一个分片的 last_frame_mode 必须是 "generate"
- 只有在画面需要100%连续时才设为复用（如同一场景内的连续动作）
- 场景切换、视角变化时应该使用 "generate"

其他注意事项:
- 分片之间要保持故事连贯性
- 转场要自然流畅
- 每个分片的描述要足够详细
- 所有参数要和总视频风格协调
- 仅返回JSON，不要包含其他内容"""

        logger.info("调用 LLM 生成分片脚本...")
        # 分片脚本生成需要较大的输出空间，使用 16384 tokens
        response_text = self._call_with_retry(prompt, temperature=0.6, operation_name="生成分片脚本", max_tokens=16384)

        result = parse_json_response(response_text)
        segments = [ScriptSegment(**seg) for seg in result.get("segments", [])]

        # 校验并修正首尾帧模式
        segments = self._validate_frame_modes(segments)

        logger.info(f"生成 {len(segments)} 个分片脚本")

        return segments

    def _validate_frame_modes(self, segments: list[ScriptSegment]) -> list[ScriptSegment]:
        """校验并修正首尾帧模式，确保边界条件正确"""
        if not segments:
            return segments

        # 第一个分片首帧必须生成
        segments[0].first_frame_mode = "generate"

        # 最后一个分片尾帧必须生成
        segments[-1].last_frame_mode = "generate"

        # 确保复用模式的一致性
        for i, segment in enumerate(segments):
            # 如果当前分片首帧是复用前一分片，那么前一分片尾帧应该标记为被复用
            if segment.first_frame_mode == "reuse_prev" and i > 0:
                segments[i - 1].last_frame_mode = "reuse_next"

            # 如果当前分片尾帧是被复用，那么下一分片首帧应该标记为复用
            if segment.last_frame_mode == "reuse_next" and i < len(segments) - 1:
                segments[i + 1].first_frame_mode = "reuse_prev"

        return segments

    async def generate_material_prompts(
        self,
        optimized_script: str,
        video_params: VideoParams,
        extra_prompt: str = ""
    ) -> list[dict]:
        """生成素材图片的提示词（基于优化后的总脚本）

        生成"设定稿"风格的素材图，包含：
        1. 角色设定图：所有角色的多角度展示，带身高比例尺
        2. 物品设定图：重要道具/物品，带尺寸标注
        3. 场景设定图：主要场景的概览

        Args:
            optimized_script: 优化后的脚本
            video_params: 视频参数
            extra_prompt: 额外的提示词，用于增加控制力（如：更鲜艳的颜色、卡通风格等）
        """
        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成素材图提示词时充分体现以上要求，将这些要求融入到每个 prompt 中。"

        prompt = f"""你是一个专业的动画/影视概念设计师。请根据以下视频脚本，生成"设定稿/角色设定表"风格的素材图提示词。

{video_params.to_prompt_context()}

完整脚本:
{optimized_script}{extra_instruction}

## 任务说明
分析脚本中出现的所有视觉元素，生成2-5张"设定稿/参考图"风格的素材图提示词。

⚠️ **重要提示**：如果用户提供了参考图，生成的提示词应该侧重于描述**内容和风格**，避免过多的设计稿元素（如标尺、标注、多角度展示等），因为这些元素在图生图模式下可能会干扰生成效果。

### 素材图类型及要求：

**1. 主要角色设定图（type: "character_main"）**
- 展示脚本中所有**主要角色**（主角、重要配角）
- 描述：外貌特征、服装、发型、表情、姿态
- 风格统一，突出角色个性
- 如有参考图：侧重描述角色特点和动作，减少"model sheet"等设计稿术语

**2. 边缘角色设定图（type: "character_minor"）** *(如需要)*
- 展示脚本中的**次要角色**（龙套、背景人物、群众）
- 简化描述，可以群组展示
- 如果次要角色很少或不重要，可省略此项

**3. 物品/道具设定图（type: "props"）** *(如需要)*
- 展示脚本中出现的**重要物品、道具、工具**
- 描述：外观、材质、特征、功能
- 如有参考图：侧重描述物品外观和用途，避免"size annotations"等标注术语
- 如果物品很少或不重要，可省略此项

**4. 主场景设定图（type: "environment_main"）** *(如需要)*
- 展示脚本中**最主要的场景**（核心场景、主场地）
- 描述：空间布局、光线、氛围、色调、关键元素
- 如有参考图：侧重场景氛围和视觉风格

**5. 副场景设定图（type: "environment_minor"）** *(如需要)*
- 展示脚本中的**次要场景**（过渡场景、背景场景）
- 简化描述
- 如果副场景不重要，可省略此项

### 返回JSON格式示例:
{{
    "prompts": [
        {{
            "type": "character_main",
            "prompt": "A detailed character design of [主角名称], [外貌描述], [服装描述], [姿态和表情], [风格特征], {video_params.style} style, high quality illustration",
            "description": "主要角色：[角色名称]，[简短描述]"
        }},
        {{
            "type": "character_minor",
            "prompt": "Minor characters from the scene, [配角描述], simple design, {video_params.style} style",
            "description": "边缘角色：[角色列表]"
        }},
        {{
            "type": "props",
            "prompt": "Important props and items: [物品描述], [材质和外观], detailed illustration, {video_params.style} style",
            "description": "重要道具：[物品列表]"
        }},
        {{
            "type": "environment_main",
            "prompt": "Main environment concept: [场景描述], [光线和氛围], establishing shot, {video_params.style} style",
            "description": "主场景：[场景名称]"
        }},
        {{
            "type": "environment_minor",
            "prompt": "Secondary environment: [副场景描述], background setting, {video_params.style} style",
            "description": "副场景：[场景名称]"
        }}
    ]
}}

### 重要要求:
1. **prompt必须使用英文**，description使用中文
2. **根据脚本实际情况选择类型**：
   - 至少包含1张（通常是主要角色或主场景）
   - 最多5张（覆盖所有类型）
   - 如果某类型元素不存在或不重要，直接省略
3. **如果用户提供了参考图（图生图模式）**：
   - 避免使用 "model sheet", "design sheet", "height scale ruler", "size annotations", "multiple angles" 等设计稿术语
   - 侧重描述**视觉特征、风格、氛围**
   - 使用 "detailed illustration", "concept art", "high quality" 等通用术语
4. **如果没有参考图（文生图模式）**：
   - 可以使用 "character design sheet", "model sheet style" 等术语
   - 可以包含 "multiple views", "height comparison" 等要求
5. **确保描述清晰具体**：包含足够的细节让AI理解要生成什么
6. **仅返回JSON**，不要有其他文字"""

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
                "prompt": f"A high quality {video_params.style} style scene, detailed, professional",
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
                "prompt": f"A high quality {video_params.style} style scene, detailed, professional",
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
        # 构建上下文信息
        context_info = ""

        if prev_segment:
            context_info += f"""
## 前一分片（分片 {prev_segment.index}）的信息 - 用于确保当前首帧与前一分片尾帧的连贯性:
- 内容: {prev_segment.content}
- 动作: {prev_segment.action}
- 氛围: {prev_segment.atmosphere}
- 镜头运动: {prev_segment.camera_movement}
【重要】当前分片的首帧应该承接前一分片的结束状态，保持画面的自然过渡。
"""

        if next_segment:
            context_info += f"""
## 后一分片（分片 {next_segment.index}）的信息 - 用于确保当前尾帧能自然过渡到后一分片:
- 内容: {next_segment.content}
- 动作: {next_segment.action}
- 氛围: {next_segment.atmosphere}
- 镜头运动: {next_segment.camera_movement}
【重要】当前分片的尾帧应该为后一分片的开始做好铺垫，保持画面的自然过渡，或者故事递进。
"""

        extra_instruction = ""
        if extra_prompt:
            extra_instruction = f"\n\n## 用户额外要求\n{extra_prompt}\n请在生成首尾帧提示词时充分体现以上要求，将这些要求融入到提示词中。"

        prompt = f"""你是一个专业的分镜头图片提示词专家。请为以下分片脚本生成首帧和尾帧的图片提示词。

{video_params.to_prompt_context()}

素材图描述（图片将作为参考图传入图生图模型）: {material_description}

## 当前分片（分片 {segment.index}）内容:
- 内容: {segment.content}
- 动作: {segment.action}
- 相机运动: {segment.camera_movement}
- 构图: {segment.composition}
- 氛围: {segment.atmosphere}
{context_info}{extra_instruction}

请生成首帧(first_frame)和尾帧(last_frame)的图片提示词，两帧之间要有明显的动作或状态变化。

返回JSON格式:
{{
    "first_frame": "首帧的详细英文提示词",
    "last_frame": "尾帧的详细英文提示词"
}}

提示词要求:
- 使用英文
- 首帧是动作开始时的状态{" - 必须与前一分片的结束状态保持视觉连贯" if prev_segment else ""}
- 尾帧是动作结束时的状态{" - 必须为后一分片的开始做好视觉铺垫" if next_segment else ""}
- 提示词会与素材图一起传入图生图模型，所以要描述如何基于素材图中的角色/物品进行变化
- 描述角色/物品的动作、姿态、表情变化，而不需要重复描述角色外观（外观会从素材图继承）
- 重点描述场景、动作、光线、构图等变化

【核心要求 - 在提示词中包含上下文信息】:
- 首帧提示词中必须包含：当前分片的起始状态描述{f"，以及从前一分片（{prev_segment.content[:50]}...）承接过来的状态" if prev_segment else ""}
- 尾帧提示词中必须包含：当前分片的结束状态描述{f"，以及为后一分片（{next_segment.content[:50]}...）做的铺垫" if next_segment else ""}
- 提示词要明确描述画面中角色/物体的具体位置、姿态、表情，便于图生图模型理解

【关键】确保相邻分片之间的画面连贯性：
- 如果前一分片结束时角色在某个位置/姿态，当前首帧应延续这个状态
- 如果后一分片开始时需要某个场景/状态，当前尾帧应为此做好铺垫

【重要】素材图是"设定稿"风格，包含标注信息（身高比例尺、尺寸标注等），首尾帧是用于视频的电影画面，绝对不能包含任何标注、文字、比例尺、尺寸标记等元素
- 在提示词中明确要求"cinematic frame, no annotations, no text, no labels, no rulers, no measurements"
- 仅返回JSON"""

        logger.info(f"调用 LLM 生成分片 {segment.index} 首尾帧提示词（含上下文）...")
        response_text = self._call_with_retry(prompt, temperature=0.7, operation_name=f"生成分片{segment.index}首尾帧提示词")

        result = parse_json_response(response_text)
        logger.info(f"分片 {segment.index} 首尾帧提示词生成完成")

        return result.get("first_frame", ""), result.get("last_frame", "")
