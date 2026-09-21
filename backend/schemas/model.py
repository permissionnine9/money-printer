"""模型管理请求 schema"""
from pydantic import BaseModel, Field


class ModelConfigRequest(BaseModel):
    """模型配置创建/更新请求"""
    name: str = Field(..., description="模型显示名称")
    api_key: str = Field(default="", description="API Key")
    base_url: str = Field(default="", description="API Base URL（OpenAI 兼容格式，如 https://api.example.com/v1）")
    model_id: str = Field(default="", description="模型 ID（服务商提供，一般为 厂商/模型名 格式）")
    is_default: bool = Field(default=False, description="是否设为该类型的默认模型")
    model_type: str = Field(default="image", description="模型类型：'image'（生图）、'chat'（对话/LLM）、'agent'（Agent SDK 端点，Anthropic 协议）")
    enabled: bool = Field(default=True, description="是否启用（停用后不参与默认模型解析与选择）")
