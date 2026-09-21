"""剧本工作流请求/响应模型"""
from typing import Optional

from pydantic import BaseModel, Field

from backend.core.persistence.workspace_store import ENTITY_ID_PATTERN, EPISODE_ID_PATTERN


# ==================== 会话 ====================

class CreateScriptSessionRequest(BaseModel):
    title: str = Field(default="", description="会话标题（可选）")


# ==================== 第 1 步：故事构思 ====================

class IdeationMessageRequest(BaseModel):
    message: str = Field(min_length=1, description="用户消息")


class IdeationAdoptRequest(BaseModel):
    story_logic: str = Field(min_length=1, description="采纳为故事逻辑的文本")


class IdeationTitleRequest(BaseModel):
    title: str = Field(default="", description="剧名（置空解除锁定）")


# ==================== 第 2 步：故事大纲 ====================

class OutlineGenerateRequest(BaseModel):
    episode_count: int = Field(default=0, ge=0, description="集数（0=由 agent 按故事规模决定）")
    total_word_count: int = Field(default=0, ge=0, description="全剧总字数目标")
    scene_count: int = Field(default=0, ge=0, description="主要场景数量")
    extra_prompt: str = Field(default="", description="补充要求")


class OutlineUpdateRequest(BaseModel):
    mindmap: str = Field(min_length=1, description="人工编辑后的 markdown 大纲")


# ==================== 第 3 步：分集设计 ====================

class EpisodesGenerateRequest(BaseModel):
    extra_instruction: str = Field(default="", description="补充要求")


class EpisodeRegenerateRequest(BaseModel):
    episode_id: str = Field(pattern=EPISODE_ID_PATTERN, description="要重设计的集（如 ep_02）")
    extra_instruction: str = Field(default="")


class EpisodeUpdateRequest(BaseModel):
    title: Optional[str] = None
    logline: Optional[str] = None
    conflict_chain: Optional[str] = None
    causality_chain: Optional[str] = None
    ending_summary: Optional[str] = None
    story_progress: Optional[str] = None
    character_ids: Optional[list[str]] = None
    scene_ids: Optional[list[str]] = None
    clue_refs: Optional[list[dict]] = None
    foreshadow_refs: Optional[list[dict]] = None


# ==================== 实体 ====================

class EntityUpsertRequest(BaseModel):
    entity_type: str = Field(pattern=r"^(character|scene|clue|foreshadow)$")
    name: str = Field(min_length=1)
    description: str = Field(default="")
    meta: dict = Field(default_factory=dict)


# ==================== 第 4 步：定妆照 ====================

class LookbookGenerateRequest(BaseModel):
    entity_ids: list[str] = Field(min_length=1, description="勾选实体的 entity_id")
    style_prompt: str = Field(default="", description="视觉风格要求")
    model_config_id: Optional[str] = Field(default=None, description="生图模型配置ID（空=默认生图模型）")


class LookbookRegenerateRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, description="新 prompt（空=沿用原 prompt）")
    model_config_id: Optional[str] = None


class LookbookImportRequest(BaseModel):
    entity_id: str = Field(pattern=ENTITY_ID_PATTERN, description="目标实体（当前会话）")
    source_image_id: str = Field(min_length=1, description="素材库源图 image_id（全局唯一）")
