"""剧本工作流请求/响应模型"""
from typing import Optional

from pydantic import BaseModel, Field


# ==================== 会话 ====================

class CreateScriptSessionRequest(BaseModel):
    title: str = Field(default="", description="会话标题（可选）")


# ==================== 第 1 步：故事构思 ====================

class IdeationMessageRequest(BaseModel):
    message: str = Field(min_length=1, description="用户消息")


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
    episode_id: str = Field(pattern=r"^ep_\d+$", description="要重设计的集（如 ep_02）")
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


class EntityReferenceEpisode(BaseModel):
    episode_id: str = Field(description="引用该实体的集，如 ep_01")
    title: str = Field(default="", description="集标题")
    actions: list[str] = Field(default_factory=list, description="该实体在本集的引用方式")


class EntityReferencesResponse(BaseModel):
    entity_id: str
    episodes: list[EntityReferenceEpisode] = Field(default_factory=list)


# ==================== 第 4 步：定妆照 ====================

class LookbookGenerateRequest(BaseModel):
    entity_ids: list[str] = Field(min_length=1, description="勾选实体的 entity_id")
    style_prompt: str = Field(default="", description="视觉风格要求")
    model_config_id: Optional[str] = Field(default=None, description="生图模型配置ID（空=默认生图模型）")


class LookbookRegenerateRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, description="新 prompt（空=沿用原 prompt）")
    model_config_id: Optional[str] = None


# ==================== 视频会话入口 ====================

class CreateVideoSessionFromScriptRequest(BaseModel):
    script_session_id: str = Field(min_length=1)
    episode_id: str = Field(pattern=r"^ep_\d+$")
