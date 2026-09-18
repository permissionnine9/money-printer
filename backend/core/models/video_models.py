"""视频创作相关的数据模型"""
from pydantic import BaseModel, Field


class VideoParams(BaseModel):
    """视频参数"""
    resolution: str = Field(default="1080p", description="分辨率")
    aspect_ratio: str = Field(default="16:9", description="宽高比")
    max_segment_duration: int = Field(default=15, description="最大分片时长（秒），注意：当前即梦和wan2.2模型仅支持5秒或10秒视频生成", ge=5, le=30)
    overlap_seconds: float = Field(default=0.0, description="相邻分片之间的重叠时长（秒），用于视频生成时段间过渡衔接", ge=0, le=5)

    def to_prompt_context(self) -> str:
        """转换为提示词上下文"""
        return f"""视频参数:
- 分辨率: {self.resolution}
- 宽高比: {self.aspect_ratio}
- 最大分片时长: {self.max_segment_duration}秒"""


class SegmentReferenceImage(BaseModel):
    """分镜引用的素材图（全能参考模式；description 为分镜侧独立副本）"""
    image_id: str = Field(description="素材池 ID（mat_* 分集素材 / lookbook_lb_* 定妆照）")
    image_path: str = Field(default="", description="图片本地路径或URL（保存时从素材源刷新）")
    description: str = Field(default="", description="对图片描述（分镜侧独立编辑，默认带出库内描述）")


class StoryboardSegment(BaseModel):
    """分镜大纲产出的分镜（步骤3 分镜管理的基本单元）"""
    index: int = Field(description="分镜索引（从 0 开始）")
    title: str = Field(default="", description="分镜标题")
    outline: str = Field(default="", description="分镜大纲（画面/动作/剧情概述）")
    # 分镜形式：首帧/尾帧/全能参考/首尾帧（仅全能参考模式实现 overlap 与提示词生成逻辑）
    mode: str = Field(
        default="all_reference",
        description="""分镜形式:
        - 'first_frame': 首帧模式（关联逻辑暂未实现）
        - 'last_frame': 尾帧模式（关联逻辑暂未实现）
        - 'all_reference': 全能参考模式（支持 overlap 与分镜提示词生成）
        - 'first_last_frame': 首尾帧模式（关联逻辑暂未实现）""",
    )
    overlap: int = Field(default=1, ge=0, le=3, description="与上一分镜的重叠秒数（仅全能参考模式使用）")
    duration: int = Field(default=15, ge=5, le=30, description="建议时长（秒，大纲阶段 LLM 分析，第 3 步展示为参考）")
    prompt: str = Field(default="", description="已生成的分镜提示词（video-prompt skill 产出）")
    reference_images: list[SegmentReferenceImage] = Field(
        default_factory=list, description="参考素材图列表（仅全能参考模式使用）",
    )

