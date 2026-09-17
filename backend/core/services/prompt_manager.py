"""提示词管理器 - 以 markdown 文件形式保存可编辑的 LLM 提示词模板

提示词文件存放于 backend/prompts/ 目录，每个文件为一个模板。
文件首行支持 HTML 注释形式的描述: <!-- description: xxx -->
模板中的占位符使用双花括号语法: {{variable}}，渲染时做字符串替换
（不用 str.format，避免与提示词中的 JSON 花括号冲突）。
不做版本管理，保存即覆盖。
"""
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 提示词文件目录（backend/prompts/）
PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"

# 占位符语法: {{variable_name}}
_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(\w+)\s*\}\}")
# 首行描述注释
_DESCRIPTION_PATTERN = re.compile(r"^<!--\s*description:\s*(.+?)\s*-->", re.MULTILINE)


class PromptManager:
    """提示词模板管理器"""

    def __init__(self, prompts_dir: Path = PROMPTS_DIR):
        self.prompts_dir = Path(prompts_dir)
        self.prompts_dir.mkdir(parents=True, exist_ok=True)
        # 首次运行时写出默认模板（文件不存在才写）
        self._ensure_default_templates()

    # ==================== 模板读写 ====================

    def list_prompts(self) -> list[dict]:
        """列出全部提示词模板"""
        result = []
        for md_file in sorted(self.prompts_dir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            result.append({
                "name": md_file.stem,
                "description": self.extract_description(content),
                "updated_at": md_file.stat().st_mtime,
                "length": len(content),
            })
        return result

    def load_prompt(self, name: str) -> str | None:
        """读取提示词模板内容"""
        path = self._safe_path(name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def save_prompt(self, name: str, content: str) -> bool:
        """保存提示词模板（覆盖写）"""
        path = self._safe_path(name)
        path.write_text(content, encoding="utf-8")
        logger.info(f"[提示词管理] 已保存提示词模板: {name} ({len(content)} 字符)")
        return True

    def render(self, name: str, variables: dict) -> str:
        """渲染模板：将 {{var}} 占位符替换为变量值

        未提供的占位符替换为空字符串。
        """
        template = self.load_prompt(name)
        if template is None:
            raise FileNotFoundError(f"提示词模板不存在: {name}")

        def replace(match: re.Match) -> str:
            var = match.group(1)
            value = variables.get(var, "")
            return str(value) if value is not None else ""

        return _PLACEHOLDER_PATTERN.sub(replace, template)

    def extract_description(self, content: str) -> str:
        """从模板内容提取描述注释"""
        match = _DESCRIPTION_PATTERN.search(content)
        return match.group(1) if match else ""

    # ==================== 内部方法 ====================

    def _safe_path(self, name: str) -> Path:
        """校验名称合法性，防止路径穿越"""
        if not re.fullmatch(r"[\w-]+", name):
            raise ValueError(f"非法的提示词名称: {name}")
        return self.prompts_dir / f"{name}.md"

    def _ensure_default_templates(self) -> None:
        """确保默认模板存在（不存在则写出内置默认值）"""
        for name, default in DEFAULT_TEMPLATES.items():
            path = self.prompts_dir / f"{name}.md"
            if not path.exists():
                path.write_text(default, encoding="utf-8")
                logger.info(f"[提示词管理] 已写出默认提示词模板: {name}.md")


# ==================== 内置默认模板 ====================
# 首次运行时写出为 markdown 文件，之后以文件内容为准（可在网页上编辑）

DEFAULT_TEMPLATES: dict[str, str] = {
    "optimize_script": """<!-- description: 脚本优化 skill（步骤2：LLM 优化总脚本，丰富细节与转场设计） -->
你是一个专业的视频脚本优化专家。请根据以下原始脚本和视频参数，优化并生成高质量的视频总脚本。

{{video_params_context}}

原始脚本:
{{original_script}}{{extra_instruction}}

请完成以下任务:
1. 优化原始脚本，极大地丰富细节，使其更适合视频制作
2. 设计{{max_segment_duration}}秒以内的转场，保障场景之间的连贯性
3. 增强视觉描述，包括场景、动作、氛围等

注意：
- 这是总脚本优化，不需要分片
- 重点是丰富细节和提升质量
- 保持原有的故事线和核心内容

请直接返回优化后的完整脚本文本，不要JSON格式，不要其他说明。""",

    "mindmap": """<!-- description: 剧本思维导图生成 skill（步骤3：将剧本解构为层次分明的结构树） -->
你是一个专业的剧本结构分析师。请根据以下优化后的视频脚本，生成展示剧本结构的思维导图。

{{video_params_context}}

优化后的脚本:
{{optimized_script}}{{extra_instruction}}

## 任务说明
将剧本解构为一棵层次分明的结构树，用 markdown 标题层级表达：
- `# ` 一级标题：剧本主题/片名（1个根节点）
- `## ` 二级标题：主要结构分支（如：故事梗概、角色设定、场景设定、道具设定、情节结构、视觉风格等）
- `### ` 三级标题：分支下的子项（如具体角色名、具体场景名、具体情节幕/段落）
- `- ` 列表项：子项的关键要点（如角色外貌特征、场景氛围、情节节拍）

## 结构要求
1. 根节点为剧本主题
2. 至少包含以下分支：
   - 故事梗概（一句话+关键转折）
   - 角色设定（每个主要角色一个 ### 子节点，含外貌/服装/性格要点）
   - 场景设定（每个主要场景一个 ### 子节点，含环境/光线/氛围要点）
   - 道具设定（重要道具，含外观/材质要点，如无可省略）
   - 情节结构（按幕/段落划分，含各段落情节要点）
3. 层级不超过 4 级，要点简洁精准（每个要点不超过 30 字）
4. 角色与场景的视觉描述要具体（供后续生成素材设定图参考）
5. 仅返回 markdown 文本，不要代码块围栏，不要其他说明""",

    "segment_scripts": """<!-- description: 分片镜头脚本生成 skill（步骤5：将优化后脚本切割为分镜脚本） -->
你是一个专业的视频分镜专家。请根据以下优化后的视频脚本，生成专业详细的分片脚本。

{{video_params_context}}

完整脚本:
{{optimized_script}}{{extra_instruction}}

基于"完整脚本"将脚本分割成多个分片，每个分片时长不超过{{max_segment_duration}}秒，不要过度分片，保障内容密度高，并为每个分片设计详细的拍摄参数。

## 分片内容要求
每个分片必须包含以下五个核心要素，内容要具体、生动、专业：

**内容**：[描述这个镜头的具体内容，包括画面中的人物、场景、动作变化]
- 明确描述画面中的主体（人物/物体）
- 具体说明场景环境（时间、地点、光线条件）
- 详细阐述动作变化过程（从开始到结束的状态变化）

**动作**：[角色/物体的具体动作]
- 人物：具体动作姿态、移动轨迹、表情变化
- 物体：运动方式、速度、轨迹、状态变化
- 要体现动作的连贯性和目的性

**镜头运动**：[推荐的镜头运动方式]
- 推：缓慢推进/快速推进，突出细节或情绪
- 拉：缓慢拉出/快速拉出，展示环境或关系
- 摇：水平摇摄/垂直摇摄，跟随主体或展示空间
- 移：横移/纵移/环绕移动，创造动态视角
- 升降：升高/降低，改变观察角度
- 综合：多种运动的组合，如推+摇、移+升等

**构图**：[推荐的构图方式]
- 基础：中心构图、三分法、对称构图、对角线构图
- 进阶：框架构图、引导线构图、留白构图、层次构图
- 特殊：俯视构图、仰视构图、鸟瞰构图、微距构图
- 要考虑主体位置、背景层次、画面平衡

**氛围**：[画面的情感氛围]
- 情绪基调：温馨、紧张、神秘、欢快、悲伤、庄严等
- 视觉感受：明亮、昏暗、朦胧、清晰、压抑、开阔等
- 心理暗示：安全感、不确定感、期待感、危机感等

## 输出格式要求
请以JSON格式返回结果，确保每个分片包含以下字段:
{
    "segments": [
        {
            "index": 0,
            "content": "内容：描述这个镜头的具体内容，包括画面中的人物、场景、动作变化。动作：角色/物体的具体动作描述。镜头运动：推荐的镜头运动方式。构图：推荐的构图方式。氛围：画面的情感氛围描述。",
            "duration": {{max_segment_duration}},
            "action": "从内容中提取的动作关键词",
            "camera_movement": "从内容中提取的镜头运动方式",
            "composition": "从内容中提取的构图方式",
            "focus": "对焦和镜头效果建议",
            "atmosphere": "从内容中提取的氛围描述",
            "transition": "与下一分片的转场方式",
            "first_frame_mode": "generate 或 reuse_prev",
            "last_frame_mode": "generate 或 reuse_next"
        }
    ]
}

重要 - 首尾帧生成模式（多种选择）:

1. first_frame_mode（首帧模式）:
   - "generate": 全新生成，与前一分片无关联（场景完全切换、或第一个分片）
   - "generate_continuous": 需要生成，但要与前一分片尾帧保持视觉连贯（镜头切换但场景连续，如换角度拍同一场景）
   - "reuse_prev": 100%复用前一分片尾帧（同一镜头的连续动作，画面完全相同）
   - "all_reference": 全能参考模式，参考图使用素材图+前一分片尾帧+后一分片首帧等全部可用素材，最大程度保证视觉一致性

2. last_frame_mode（尾帧模式）:
   - "generate": 全新生成（场景即将切换、或最后一个分片）
   - "generate_continuous": 需要生成，但后一分片首帧会参考此帧保持连贯（镜头即将切换但场景连续）
   - "reuse_next": 此帧会被下一分片100%复用（配合下一分片的 reuse_prev）
   - "all_reference": 全能参考模式，参考图使用素材图+前一分片尾帧+后一分片首帧等全部可用素材

选择指南:
- 同一镜头连续动作 → reuse_prev / reuse_next（100%相同的图）
- 换镜头但同场景（如切换拍摄角度）→ generate_continuous（需要连贯但画面不同）
- 需要综合所有可用素材保持最强一致性 → all_reference（全能参考模式）
- 完全切换场景 → generate（无需连贯）

注意:
- 第一个分片的 first_frame_mode 必须是 "generate"
- 最后一个分片的 last_frame_mode 必须是 "generate"
- generate_continuous 比 reuse 更常用，因为大多数相邻分片需要连贯但不是完全相同

其他注意事项:
- 分片之间要保持故事连贯性
- 转场要自然流畅
- 每个分片的描述要足够详细，五个要素缺一不可
- 所有参数要和总视频风格协调
- content字段必须按顺序包含：内容、动作、镜头运动、构图、氛围
- 仅返回JSON，不要包含其他内容""",

    "frame_prompts": """<!-- description: 分片镜头首尾帧提示词生成 skill（步骤6：为每个分镜生成首/尾帧图片提示词） -->
你是一个专业的图片生成提示词专家。请为视频分片生成首帧和尾帧的图片提示词。

## 图片生成基础参数（必须包含在每个提示词中）
- 画面比例: {{aspect_ratio}}
- 画质要求: 电影级画质，2K高清，细节丰富
- 禁止元素: 绝对不能包含任何文字、标注、比例尺、尺寸标记、设计稿元素

## 当前分片信息
- 分片内容: {{segment_content}}
- 动作描述: {{segment_action}}
- 构图方式: {{segment_composition}}
- 氛围: {{segment_atmosphere}}

## 素材参考
素材图描述: {{material_description}}
（素材图用于保持角色/物品外观一致性，无需在提示词中重复描述角色外观细节）

{{continuity_hint}}{{extra_instruction}}

## 任务
生成首帧和尾帧的图片提示词，两帧之间需要体现动作或状态明显的变化。

## 提示词结构要求
每个提示词应简洁聚焦，包含以下三部分：
1. 【画面参数】风格、比例、画质要求（约20字）
2. 【画面描述】当前帧的具体视觉内容：角色姿态、动作状态、场景环境、光线氛围（约50-80字）
3. 【禁止项】明确禁止文字、标注等元素（约15字）

## 示例格式
"电影级画质，{{aspect_ratio}}画面。[具体的画面描述：谁在哪里做什么，什么姿态，什么光线氛围]。禁止出现任何文字、标注、比例尺。"

返回JSON格式:
{
    "first_frame": "首帧提示词（动作起始状态）",
    "last_frame": "尾帧提示词（动作结束状态）"
}

仅返回JSON，不要其他说明。""",
}


# 模块级单例
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """获取 PromptManager 单例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
