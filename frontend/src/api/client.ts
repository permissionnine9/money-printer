/**
 * API 客户端
 */
import axios from 'axios'
import type {
  Session,
  SessionDetail,
  StepResponse,
  VideoParams,
  StoryboardSegment,
  SegmentPromptContext,
  MaterialPoolGroup,
  ImageModelConfig,
  PromptTemplate,
  LookbookLibraryGroup,
  MaterialListResponse,
  OrphanScanResponse,
} from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 600000,  // 10 分钟
  headers: {
    'Content-Type': 'application/json',
  },
})

// 请求拦截器
client.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// 响应拦截器
client.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    const message = error.response?.data?.detail || error.message || '请求失败'
    return Promise.reject(new Error(message))
  }
)

// 会话管理 API
export const sessionApi = {
  // 创建会话
  create: async (): Promise<Session> => {
    const { data } = await client.post('/sessions')
    return data
  },

  // 获取会话列表
  list: async (): Promise<{ sessions: Session[]; total: number }> => {
    const { data } = await client.get('/sessions')
    return data
  },

  // 获取会话详情
  get: async (sessionId: string): Promise<SessionDetail> => {
    const { data } = await client.get(`/sessions/${sessionId}`)
    return data
  },

  // 删除会话
  delete: async (sessionId: string): Promise<void> => {
    await client.delete(`/sessions/${sessionId}`)
  },
}

// 工作流步骤 API（视频 4 步）
export const stepApi = {
  // 步骤1：从剧本选集
  selectEpisode: async (
    sessionId: string,
    payload: { script_session_id: string; episode_id: string } & VideoParams
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/select-episode`, payload)
    return data
  },

  // 步骤2：生成分镜大纲（返回 run_id，AgentRunProgress 观流）
  generateStoryboardOutline: async (sessionId: string, extraPrompt?: string): Promise<string> => {
    const { data } = await client.post(`/steps/${sessionId}/storyboard-outline/generate`, {
      extra_prompt: extraPrompt,
    })
    const runId = data?.data?.run_id
    if (!runId) throw new Error('未获取到 run_id')
    return runId
  },

  // 步骤2：保存人工编辑的分镜大纲导图
  updateStoryboardOutline: async (
    sessionId: string,
    mindmap: string
  ): Promise<{ success: boolean; data: { mindmap: string } }> => {
    const { data } = await client.put(`/steps/${sessionId}/storyboard-outline`, { mindmap })
    return data
  },

  // 步骤3：更新分镜配置（分镜形式 / overlap）
  updateSegmentConfig: async (
    sessionId: string,
    index: number,
    config: { mode?: string; overlap?: number }
  ): Promise<{ success: boolean; data: { segment: StoryboardSegment } }> => {
    const { data } = await client.put(`/steps/${sessionId}/storyboard-segments/${index}/config`, config)
    return data
  },

  // 步骤3：素材池（选择弹窗分组数据：定妆照 / 本集素材 / 其他集素材）
  getMaterialPool: async (
    sessionId: string
  ): Promise<MaterialPoolGroup[]> => {
    const { data } = await client.get(`/steps/${sessionId}/material-pool`)
    return data?.data?.groups ?? []
  },

  // 步骤3：保存分镜参考素材图（全量覆盖；换图会清空该分镜已生成的提示词）
  updateSegmentReferenceImages: async (
    sessionId: string,
    index: number,
    referenceImages: { image_id: string; description: string }[]
  ): Promise<{ success: boolean; data: { segment: StoryboardSegment } }> => {
    const { data } = await client.put(
      `/steps/${sessionId}/storyboard-segments/${index}/reference-images`,
      { reference_images: referenceImages }
    )
    return data
  },

  // 步骤3：AI 生成分镜素材图 → run_id（LLM 需求理解 + 生图 + 归档 + 自动关联）
  generateSegmentMaterial: async (
    sessionId: string,
    index: number,
    payload: {
      user_prompt: string
      mentioned_image_ids: string[]
      reference_paths: string[]
      model_config_id?: string
    }
  ): Promise<string> => {
    const { data } = await client.post(
      `/steps/${sessionId}/storyboard-segments/${index}/generate-material`,
      payload
    )
    const runId = data?.data?.run_id
    if (!runId) throw new Error('未获取到 run_id')
    return runId
  },

  // 步骤3：删除素材池中的 AI 生成素材图（仅 mat_*；分镜中已引用处将失效）
  deleteMaterial: async (
    sessionId: string,
    imageId: string
  ): Promise<{ success: boolean; data: { deleted: boolean } }> => {
    const { data } = await client.delete(`/steps/${sessionId}/materials/${imageId}`)
    return data
  },

  // 步骤3：获取分镜提示词生成弹窗的上下文
  getSegmentPromptContext: async (
    sessionId: string,
    index: number
  ): Promise<SegmentPromptContext> => {
    const { data } = await client.get(`/steps/${sessionId}/storyboard-segments/${index}/prompt-context`)
    return data?.data
  },

  // 步骤3：生成分镜提示词（返回 run_id，仅全能参考模式）
  generateSegmentPrompt: async (sessionId: string, index: number): Promise<string> => {
    const { data } = await client.post(`/steps/${sessionId}/storyboard-segments/${index}/generate-prompt`, {})
    const runId = data?.data?.run_id
    if (!runId) throw new Error('未获取到 run_id')
    return runId
  },

  // 步骤3：完成/取消完成单个分镜的配置（≥1 个分镜完成即可进入步骤4）
  completeSegment: async (sessionId: string, index: number, completed = true): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/storyboard-segments/${index}/complete`, { completed })
    return data
  },

  // 步骤4：生成视频（勾选分镜子集拼接 timeline；缺省=全部已配置分镜）
  generateVideos: async (sessionId: string, segmentIndexes?: number[]): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/videos`, segmentIndexes ? { segment_indexes: segmentIndexes } : {})
    return data
  },

  // 步骤4两段式-阶段一：导入到 ComfyUI（上传素材+注入工作流暂存，不执行；段间重叠沿用分镜 overlap）
  importComfyUI: async (sessionId: string, segmentIndexes?: number[], globalPrompt?: string): Promise<StepResponse> => {
    const payload: Record<string, unknown> = {}
    if (segmentIndexes) payload.segment_indexes = segmentIndexes
    if (globalPrompt) payload.global_prompt = globalPrompt
    const { data } = await client.post(`/steps/${sessionId}/comfyui/import`, payload)
    return data
  },

  // 步骤4两段式-阶段二：开始生成（执行已导入的工作流）
  startComfyUIVideo: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/comfyui/start`, {})
    return data
  },

  // 步骤4：取消视频生成
  cancelVideos: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/cancel-videos`, {})
    return data
  },

  // 步骤4：恢复视频备份
  restoreVideosBackup: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/restore-videos-backup`, {})
    return data
  },
}

// 生图模型管理 API
export const modelApi = {
  // 列出全部模型配置（可按类型过滤：image / chat）
  list: async (
    modelType?: 'image' | 'chat' | 'agent'
  ): Promise<{ success: boolean; data: { models: ImageModelConfig[] } }> => {
    const params = modelType ? { model_type: modelType } : {}
    const { data } = await client.get('/models', { params })
    return data
  },

  // 新增模型配置
  create: async (payload: {
    name: string
    api_key: string
    base_url: string
    model_id: string
    is_default?: boolean
    model_type?: 'image' | 'chat'
  }): Promise<{ success: boolean; data: { model: ImageModelConfig } }> => {
    const { data } = await client.post('/models', payload)
    return data
  },

  // 更新模型配置
  update: async (
    modelId: string,
    payload: {
      name: string
      api_key: string
      base_url: string
      model_id: string
      is_default?: boolean
      model_type?: 'image' | 'chat' | 'agent'
    }
  ): Promise<{ success: boolean; data: { model: ImageModelConfig } }> => {
    const { data } = await client.put(`/models/${modelId}`, payload)
    return data
  },

  // 设为默认模型
  setDefault: async (
    modelId: string
  ): Promise<{ success: boolean; message: string; data: { model: ImageModelConfig } }> => {
    const { data } = await client.post(`/models/${modelId}/set-default`)
    return data
  },

  // 删除模型配置
  remove: async (modelId: string): Promise<{ success: boolean; data: { deleted: boolean } }> => {
    const { data } = await client.delete(`/models/${modelId}`)
    return data
  },
}

// 提示词管理 API（分片镜头 skill 提示词）
export const promptApi = {
  // 列出全部提示词模板
  list: async (): Promise<{ success: boolean; data: { prompts: PromptTemplate[] } }> => {
    const { data } = await client.get('/prompts')
    return data
  },

  // 获取单个提示词内容
  get: async (
    name: string
  ): Promise<{ success: boolean; data: { prompt: PromptTemplate } }> => {
    const { data } = await client.get(`/prompts/${name}`)
    return data
  },

  // 保存提示词（markdown 覆盖写）
  save: async (
    name: string,
    content: string
  ): Promise<{ success: boolean }> => {
    const { data } = await client.put(`/prompts/${name}`, { content })
    return data
  },
}

export const uploadApi = {
  // 上传图片
  uploadImage: async (file: File): Promise<{ file_path: string; url: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await client.post('/uploads/image', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })
    return data
  },
}


// ==================== 剧本工作流 API（/script-sessions） ====================

import type {
  ScriptSessionDetail,
  ScriptEntity,
  Episode,
  LookbookImage,
  EntityType,
  EntityReferences,
} from '@/types'

// 剧本会话管理
export const scriptSessionApi = {
  create: async (): Promise<ScriptSessionDetail> => {
    const { data } = await client.post('/script-sessions', {})
    return data.data
  },

  list: async (): Promise<{ sessions: ScriptSessionDetail[]; total: number }> => {
    const { data } = await client.get('/script-sessions')
    return data.data
  },

  get: async (sessionId: string): Promise<ScriptSessionDetail> => {
    const { data } = await client.get(`/script-sessions/${sessionId}`)
    return data.data
  },

  delete: async (sessionId: string): Promise<void> => {
    await client.delete(`/script-sessions/${sessionId}`)
  },
}

// 剧本 4 步（SSE 端点走 sse.ts，这里只放普通请求）
export const scriptStepApi = {
  // 第 1 步：人工编辑故事逻辑
  updateStoryLogic: async (sessionId: string, storyLogic: string): Promise<any> => {
    const { data } = await client.put(`/script-sessions/${sessionId}/ideation`, {
      story_logic: storyLogic,
    })
    return data.data
  },

  // 第 1 步：手动设定剧名（manual 锁定，AI 收敛不再覆盖）
  setStoryTitle: async (sessionId: string, title: string): Promise<any> => {
    const { data } = await client.put(`/script-sessions/${sessionId}/ideation/title`, { title })
    return data.data
  },

  // 第 1 步：采纳文本为故事逻辑并完成步骤（不经 LLM 收敛）
  adoptStoryLogic: async (sessionId: string, storyLogic: string): Promise<any> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/ideation/adopt`, {
      story_logic: storyLogic,
    })
    return data.data
  },

  // 第 2 步：人工编辑大纲
  updateOutline: async (sessionId: string, mindmap: string): Promise<any> => {
    const { data } = await client.put(`/script-sessions/${sessionId}/outline`, { mindmap })
    return data.data
  },

  // 第 3 步：生成（全量/单集重设计）→ { run_id }（SSE 观流走 agentRunApi）
  generateEpisodes: async (sessionId: string, extraInstruction?: string): Promise<string> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/episodes/generate`, {
      extra_instruction: extraInstruction || '',
    })
    return data.data.run_id
  },

  regenerateEpisode: async (sessionId: string, episodeId: string, extraInstruction?: string): Promise<string> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/episodes/regenerate`, {
      episode_id: episodeId,
      extra_instruction: extraInstruction || '',
    })
    return data.data.run_id
  },

  // 第 3 步：分集 CRUD
  listEpisodes: async (sessionId: string): Promise<Episode[]> => {
    const { data } = await client.get(`/script-sessions/${sessionId}/episodes`)
    return data.data.episodes
  },

  updateEpisode: async (sessionId: string, episodeId: string, fields: Partial<Episode>): Promise<Episode> => {
    const { data } = await client.put(`/script-sessions/${sessionId}/episodes/${episodeId}`, fields)
    return data.data
  },

  // 第 4 步：定妆照
  generateLookbook: async (
    sessionId: string,
    entityIds: string[],
    stylePrompt?: string,
    modelConfigId?: string
  ): Promise<string> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/lookbook/generate`, {
      entity_ids: entityIds,
      style_prompt: stylePrompt || '',
      model_config_id: modelConfigId,
    })
    return data.data.run_id
  },

  completeLookbook: async (sessionId: string): Promise<any> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/lookbook/complete`)
    return data.data
  },

  listLookbook: async (
    sessionId: string,
    entityId?: string,
    taskStatus?: string
  ): Promise<LookbookImage[]> => {
    const params: any = {}
    if (entityId) params.entity_id = entityId
    if (taskStatus) params.task_status = taskStatus
    const { data } = await client.get(`/script-sessions/${sessionId}/lookbook`, { params })
    return data.data.images
  },

  regenerateLookbookImage: async (
    sessionId: string,
    imageId: string,
    prompt?: string,
    modelConfigId?: string
  ): Promise<string> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/lookbook/${imageId}/regenerate`, {
      prompt,
      model_config_id: modelConfigId,
    })
    return data.data.run_id
  },

  deleteLookbookImage: async (sessionId: string, imageId: string): Promise<void> => {
    await client.delete(`/script-sessions/${sessionId}/lookbook/${imageId}`)
  },

  // 素材库：全部剧本会话的已完成定妆照（含本剧本历史素材），按会话分组
  getLookbookLibrary: async (sessionId: string): Promise<LookbookLibraryGroup[]> => {
    const { data } = await client.get(`/script-sessions/${sessionId}/lookbook/library`)
    return data.data.groups
  },

  // 从素材库复制素材到当前会话并锚定到实体
  importLookbookImage: async (sessionId: string, entityId: string, sourceImageId: string): Promise<LookbookImage> => {
    const { data } = await client.post(`/script-sessions/${sessionId}/lookbook/import`, {
      entity_id: entityId,
      source_image_id: sourceImageId,
    })
    return data.data.image
  },
}

// 剧本实体库
export const entityApi = {
  list: async (sessionId: string, entityType?: EntityType): Promise<ScriptEntity[]> => {
    const params = entityType ? { entity_type: entityType } : {}
    const { data } = await client.get(`/script-sessions/${sessionId}/entities`, { params })
    return data.data.entities
  },

  // 实体引用集：该实体出现在哪几集（episode_id + title + actions）
  getReferences: async (sessionId: string, entityId: string): Promise<EntityReferences> => {
    const { data } = await client.get(`/script-sessions/${sessionId}/entities/${entityId}/references`)
    return data.data ?? data
  },
}

// Agent run（通用：剧本/视频共用）
export const agentRunApi = {
  cancel: async (runId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.post(`/agent-runs/${runId}/cancel`)
    return data
  },
}

// 系统设置：远程 ComfyUI SSH 连接信息（hosts.json + 隧道重连）
export interface ComfyUIConnection {
  host: string
  port: number | null
  user: string
  password_set: boolean
  connected: boolean
}

export const settingsApi = {
  getComfyUIConnection: async (): Promise<ComfyUIConnection> => {
    const { data } = await client.get(`/settings/comfyui-connection`)
    return data
  },
  updateComfyUIConnection: async (payload: {
    host: string; port: number; user: string; password?: string;
  }): Promise<{ connected: boolean; message: string }> => {
    const { data } = await client.put(`/settings/comfyui-connection`, payload, { timeout: 60000 })
    return data
  },
}

// ==================== 素材管理 API（/materials） ====================

export const materialApi = {
  // 素材列表（kind: lookbook 定妆照 / episode 分集素材图 / upload 上传参考图 / video 视频）
  list: async (kind: string): Promise<MaterialListResponse> => {
    const { data } = await client.get('/materials', { params: { kind } })
    return data.data
  },

  // 删除生成图素材（被分镜/实体引用中时后端返回 409）
  deleteImage: async (imageId: string): Promise<{ deleted: boolean; file_deleted: boolean }> => {
    const { data } = await client.delete(`/materials/image/${imageId}`)
    return data.data
  },

  // 孤儿文件扫描（无 DB 记录且无引用的磁盘文件）
  scanOrphans: async (): Promise<OrphanScanResponse> => {
    const { data } = await client.get('/materials/orphans')
    return data.data
  },

  // 批量删除素材文件（被引用的拒删，返回逐条结果）
  deleteFiles: async (
    paths: string[]
  ): Promise<{ deleted: string[]; failed: { path: string; reason: string }[] }> => {
    const { data } = await client.post('/materials/files/delete', { paths })
    return data.data
  },
}

export default client
