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
    "storyboard_outline": """<!-- description: 分镜大纲生成（步骤2：以剧本分集设计为上下文产出分镜导图与分镜列表） -->
你是专业的视频分镜专家。根据以下上下文为「本集」生成分镜大纲。

{{video_params_context}}

## 剧本上下文（本集分集设计 + 人物/场景设定 + 前后集衔接）
{{script_context}}{{extra_instruction}}

## 要求

- 按 max_segment_duration={{max_segment_duration}} 秒的节奏将本集切分为若干分镜（不过度分片，每个分镜内容密度高）
- mindmap 是 markdown 层级导图：`# 本集标题` → `## 幕/段` → `### 分镜标题`，层级不超过 3 层
- segments 与导图中的分镜一一对应：title=分镜标题，outline=该分镜的画面/动作/剧情概述（80-150 字，具体可拍，包含人物动作与环境细节）
- 人物外观、场景氛围严格遵循上下文设定，不得虚构与剧情因果冲突的内容

## 输出

只输出 JSON（不要其他内容、不要 markdown 代码块外的解释）：

{"mindmap": "# 本集标题\n## 第一幕\n### 分镜1标题\n### 分镜2标题", "segments": [{"index": 0, "title": "分镜标题", "outline": "分镜大纲..."}]}
""",
}


# 模块级单例
_prompt_manager: PromptManager | None = None


def get_prompt_manager() -> PromptManager:
    """获取 PromptManager 单例"""
    global _prompt_manager
    if _prompt_manager is None:
        _prompt_manager = PromptManager()
    return _prompt_manager
