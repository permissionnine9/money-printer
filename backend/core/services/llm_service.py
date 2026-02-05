"""LLM服务 - 使用盛算云 doubao-seed-1.8 进行脚本优化"""
import logging
import time
from openai import OpenAI

from backend.core.config import SHENGSUANYUN_API_KEY, SHENGSUANYUN_BASE_URL, SHENGSUANYUN_LLM_MODEL, MAX_SEGMENT_DURATION
from backend.core.models import VideoParams, ScriptSegment
from backend.core.utils.json_parser import parse_json_response

logger = logging.getLogger(__name__)


class LLMService:
    """LLM服务类"""

    def __init__(self):
        self.client = OpenAI(
            base_url=SHENGSUANYUN_BASE_URL,
            api_key=SHENGSUANYUN_API_KEY,
        )
        self.model = SHENGSUANYUN_LLM_MODEL
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
2. 设计{MAX_SEGMENT_DURATION}秒以内的转场，保障场景之间的连贯性
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

基于"完整脚本"将脚本分割成多个分片，每个分片时长不超过{MAX_SEGMENT_DURATION}秒，不要过度分片，保障内容密度高，并为每个分片设计详细的拍摄参数。

请以JSON格式返回结果:
{{
    "segments": [
        {{
            "index": 0,
            "content": "分片的具体内容描述",
            "duration": {MAX_SEGMENT_DURATION},
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

重要 - 首尾帧生成模式（三种选择）:

1. first_frame_mode（首帧模式）:
   - "generate": 全新生成，与前一分片无关联（场景完全切换、或第一个分片）
   - "generate_continuous": 需要生成，但要与前一分片尾帧保持视觉连贯（镜头切换但场景连续，如换角度拍同一场景）
   - "reuse_prev": 100%复用前一分片尾帧（同一镜头的连续动作，画面完全相同）

2. last_frame_mode（尾帧模式）:
   - "generate": 全新生成（场景即将切换、或最后一个分片）
   - "generate_continuous": 需要生成，但后一分片首帧会参考此帧保持连贯（镜头即将切换但场景连续）
   - "reuse_next": 此帧会被下一分片100%复用（配合下一分片的 reuse_prev）

选择指南:
- 同一镜头连续动作 → reuse_prev / reuse_next（100%相同的图）
- 换镜头但同场景（如切换拍摄角度）→ generate_continuous（需要连贯但画面不同）
- 完全切换场景 → generate（无需连贯）

注意:
- 第一个分片的 first_frame_mode 必须是 "generate"
- 最后一个分片的 last_frame_mode 必须是 "generate"
- generate_continuous 比 reuse 更常用，因为大多数相邻分片需要连贯但不是完全相同

其他注意事项:
- 分片之间要保持故事连贯性
- 转场要自然流畅
- 每个分片的描述要足够详细
- 所有参数要和总视频风格协调
- 仅返回JSON，不要包含其他内容"""

        logger.info("调用 LLM 生成分片脚本...")
        # 分片脚本生成需要较大的输出空间，使用 16384 tokens
        response_text = self._call_with_retry(prompt, temperature=0.6, operation_name="生成分片脚本", max_tokens=26384)

        result = parse_json_response(response_text)
        segments = [ScriptSegment(**seg) for seg in result.get("segments", [])]

        # 校验并修正首尾帧模式
        segments = self._validate_frame_modes(segments)

        logger.info(f"生成 {len(segments)} 个分片脚本")

        return segments

    def _validate_frame_modes(self, segments: list[ScriptSegment]) -> list[ScriptSegment]:
        """校验并修正首尾帧模式，确保边界条件正确

        有效的 first_frame_mode: "generate", "generate_continuous", "reuse_prev"
        有效的 last_frame_mode: "generate", "generate_continuous", "reuse_next"
        """
        if not segments:
            return segments

        valid_first_modes = {"generate", "generate_continuous", "reuse_prev"}
        valid_last_modes = {"generate", "generate_continuous", "reuse_next"}

        # 规范化无效值
        for segment in segments:
            if segment.first_frame_mode not in valid_first_modes:
                segment.first_frame_mode = "generate"
            if segment.last_frame_mode not in valid_last_modes:
                segment.last_frame_mode = "generate"

        # 第一个分片首帧必须是 generate（不能复用或连续）
        if segments[0].first_frame_mode in ("reuse_prev", "generate_continuous"):
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
分析脚本中出现的所有视觉元素，生成2-6张"设定稿/角色设定表"风格的素材图提示词。

⚠️ **重要提示**：素材图必须是"设定稿"风格！
- 必须包含：身高比例尺、尺寸标注、多角度展示、设计说明等设计稿元素
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
            "prompt": "[主角名称]的角色设定稿，多角度展示（正面、侧面、背面），[外貌描述]，[服装描述]，侧边带身高比例尺，角色设计参考图，{video_params.style}风格，白色背景",
            "description": "主要角色：[角色名称]，[简短描述]"
        }},
        {{
            "type": "character_minor",
            "prompt": "次要角色设定稿，[配角描述]，简化的多角度展示，身高对比图，{video_params.style}风格，白色背景",
            "description": "边缘角色：[角色列表]"
        }},
        {{
            "type": "props",
            "prompt": "道具设定稿：[物品描述]，多角度展示，带尺寸标注，[材质和外观]，详细的正交视图，{video_params.style}风格，白色背景",
            "description": "重要道具：[物品列表]"
        }},
        {{
            "type": "environment_main",
            "prompt": "场景概念设定稿：[场景描述]，带比例参考的布局概览，[光线和氛围]，关键区域标注，{video_params.style}风格",
            "description": "主场景：[场景名称]"
        }},
        {{
            "type": "environment_minor",
            "prompt": "副场景设计稿：[副场景描述]，简化布局，背景参考图，{video_params.style}风格",
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
                "prompt": f"高质量的{video_params.style}风格场景设定稿，细节丰富，专业设计",
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
                "prompt": f"高质量的{video_params.style}风格场景设定稿，细节丰富，专业设计",
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
    "first_frame": "首帧的详细中文提示词",
    "last_frame": "尾帧的详细中文提示词"
}}

提示词要求:
- 使用中文
- 首帧是动作开始时的状态{" - 必须与前一分片的结束状态保持视觉连贯" if prev_segment else ""}
- 尾帧是动作结束时的状态{" - 必须为后一分片的开始做好视觉铺垫" if next_segment else ""}
- 提示词会与素材图一起传入图生图模型，所以要描述如何基于素材图中的角色/物品进行变化
- 描述角色/物品的动作、姿态、表情变化，而不需要重复描述角色外观（外观会从素材图继承）
- 重点描述场景、动作、光线、构图等变化

【核心要求 - 在提示词中包含上下文信息】:
- 首帧提示词中必须包含：当前分片的起始状态描述{f"，以及从前一分片（{prev_segment.content[:60]}...）承接过来的状态" if prev_segment else ""}
- 尾帧提示词中必须包含：当前分片的结束状态描述{f"，以及为后一分片（{next_segment.content[:60]}...）做的铺垫" if next_segment else ""}
- 提示词要明确描述画面中角色/物体的具体位置、姿态、表情，便于图生图模型理解

【关键】确保相邻分片之间的画面连贯性：
- 如果前一分片结束时角色在某个位置/姿态，当前首帧应延续这个状态
- 如果后一分片开始时需要某个场景/状态，当前尾帧应为此做好铺垫

【重要】素材图是"设定稿"风格，包含标注信息（身高比例尺、尺寸标注等），首尾帧是用于视频的电影画面，绝对不能包含任何标注、文字、比例尺、尺寸标记等元素
- 在提示词中明确要求"这是一张电影片段的帧画面，要求电影画质，绝对不能包含任何标注、文字、比例尺、尺寸标记"
- 仅返回JSON"""

        logger.info(f"调用 LLM 生成分片 {segment.index} 首尾帧提示词（含上下文）...")
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
2. 每个分片时长不超过{MAX_SEGMENT_DURATION}秒
3. 如果有上下文，确保新生成的分片能够自然承接前文和后文
4. 保持与整体视频参数一致的风格和氛围
5. 为每个分片设计详细的拍摄参数

请以JSON格式返回结果:
{{
    "segments": [
        {{
            "content": "分片的具体内容描述",
            "duration": {MAX_SEGMENT_DURATION},
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
                duration=seg_data.get("duration", MAX_SEGMENT_DURATION),
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
