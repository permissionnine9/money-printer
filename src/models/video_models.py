"""视频创作相关的数据模型"""
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class WorkflowStatus(str, Enum):
    """工作流状态"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    COMPLETED = "completed"
    FAILED = "failed"


class VideoParams(BaseModel):
    """视频参数"""
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    language: str = Field(default="zh-CN", description="语言")
    style: str = Field(default="cinematic", description="美学风格")
    perspective: str = Field(default="third_person", description="视角")

    def to_prompt_context(self) -> str:
        """转换为提示词上下文"""
        return f"""视频参数:
- 分辨率: {self.resolution}
- 宽高比: {self.aspect_ratio}
- 语言: {self.language}
- 美学风格: {self.style}
- 视角: {self.perspective}"""


class ScriptSegment(BaseModel):
    """分片脚本"""
    index: int = Field(description="分片索引")
    content: str = Field(description="分片内容")
    duration: float = Field(default=8.0, description="时长（秒）", le=8.0)
    action: str = Field(default="", description="动作描述")
    camera_movement: str = Field(default="", description="相机运动")
    composition: str = Field(default="", description="构图")
    focus: str = Field(default="", description="对焦和镜头效果")
    atmosphere: str = Field(default="", description="氛围")
    transition: str = Field(default="", description="转场方式")
    # 首尾帧复用模式
    first_frame_mode: str = Field(
        default="generate",
        description="首帧模式: 'generate'(生成) 或 'reuse_prev'(复用前一分片尾帧)"
    )
    last_frame_mode: str = Field(
        default="generate",
        description="尾帧模式: 'generate'(生成) 或 'reuse_next'(被下一分片复用)"
    )

    def to_image_prompt(self, style: str) -> str:
        """转换为图片生成提示词"""
        parts = [self.content]
        if self.action:
            parts.append(f"动作: {self.action}")
        if self.composition:
            parts.append(f"构图: {self.composition}")
        if self.atmosphere:
            parts.append(f"氛围: {self.atmosphere}")
        parts.append(f"风格: {style}")
        return ", ".join(parts)

    def to_video_prompt(self) -> str:
        """转换为视频生成提示词"""
        parts = [self.content]
        if self.action:
            parts.append(f"动作: {self.action}")
        if self.camera_movement:
            parts.append(f"镜头运动: {self.camera_movement}")
        if self.focus:
            parts.append(f"镜头效果: {self.focus}")
        return ", ".join(parts)


class OptimizedScript(BaseModel):
    """优化后的脚本"""
    original_script: str = Field(description="原始脚本")
    optimized_script: str = Field(description="优化后的完整脚本")
    segments: list[ScriptSegment] = Field(default_factory=list, description="分片脚本列表")
    summary: str = Field(default="", description="脚本摘要")

    @property
    def total_duration(self) -> float:
        """计算总时长"""
        return sum(seg.duration for seg in self.segments)


class MaterialImageType(str, Enum):
    """素材图类型"""
    CHARACTER = "character"      # 角色设定图
    PROPS = "props"              # 物品/道具设定图
    ENVIRONMENT = "environment"  # 场景设定图
    GENERAL = "general"          # 通用素材图


class MaterialImage(BaseModel):
    """素材图片（设定稿风格）"""
    image_id: str = Field(description="图片ID")
    image_path: str = Field(description="图片本地路径或URL")
    prompt: str = Field(description="生成提示词")
    description: str = Field(default="", description="图片描述")
    image_type: str = Field(default="general", description="素材图类型: character/props/environment/general")
    task_id: str = Field(default="", description="异步任务ID（如有）")
    task_status: str = Field(default="completed", description="任务状态: pending/completed/failed")


class SegmentFrame(BaseModel):
    """分镜头首尾帧"""
    segment_index: int = Field(description="分片索引")
    first_image_id: str = Field(description="首帧图片ID")
    first_image_path: str = Field(description="首帧图片路径")
    last_image_id: str = Field(description="尾帧图片ID")
    last_image_path: str = Field(description="尾帧图片路径")
    first_prompt: str = Field(default="", description="首帧提示词")
    last_prompt: str = Field(default="", description="尾帧提示词")


class GeneratedVideo(BaseModel):
    """生成的视频"""
    segment_index: int = Field(description="分片索引")
    video_id: str = Field(description="视频ID")
    video_path: str = Field(description="视频本地路径")
    duration: float = Field(description="视频时长（秒）")
    prompt: str = Field(default="", description="生成提示词")


class WorkflowState(BaseModel):
    """工作流状态"""
    # 基本信息
    session_id: str = Field(description="会话ID")
    status: WorkflowStatus = Field(default=WorkflowStatus.PENDING, description="当前状态")
    current_step: str = Field(default="", description="当前步骤")

    # 输入数据
    original_script: str = Field(default="", description="原始脚本")
    video_params: Optional[VideoParams] = Field(default=None, description="视频参数")

    # 处理结果
    optimized_script: Optional[OptimizedScript] = Field(default=None, description="优化后的脚本")
    material_images: list[MaterialImage] = Field(default_factory=list, description="素材图片")
    segment_frames: list[SegmentFrame] = Field(default_factory=list, description="分镜头帧")
    generated_videos: list[GeneratedVideo] = Field(default_factory=list, description="生成的视频")

    # 人工交互
    pending_approval: str = Field(default="", description="待审批内容类型")
    approval_message: str = Field(default="", description="审批提示消息")
    user_feedback: str = Field(default="", description="用户反馈")

    # 错误处理
    error_message: str = Field(default="", description="错误消息")

    def get_approved_segments(self) -> list[ScriptSegment]:
        """获取已审批的分片"""
        if self.optimized_script:
            return self.optimized_script.segments
        return []
