/**
 * API 客户端
 */
import axios from 'axios'
import type {
  Session,
  SessionDetail,
  StepResponse,
  VideoParams,
  ScriptSegment,
  SessionAsset,
  ImageModelConfig,
  PromptTemplate,
} from '@/types'

const client = axios.create({
  baseURL: '/api/v1',
  timeout: 300000,  // 5分钟
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

// 工作流步骤 API
export const stepApi = {
  // 步骤1：提交脚本
  submitScript: async (
    sessionId: string,
    script: string,
    params: VideoParams
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/submit`, {
      script,
      ...params,
    })
    return data
  },

  // 步骤1：重新提交脚本（修改脚本和参数，重置后续步骤）
  resubmitScript: async (
    sessionId: string,
    script: string,
    params: VideoParams
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/resubmit`, {
      script,
      ...params,
    })
    return data
  },

  // 步骤2：优化脚本（useOriginal=true 直接采用原始脚本，跳过 LLM）
  optimizeScript: async (sessionId: string, extraPrompt?: string, useOriginal?: boolean): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/optimize`, {
      extra_prompt: extraPrompt,
      use_original: useOriginal,
    })
    return data
  },

  // 步骤2：重新优化脚本（重置后续步骤；useOriginal=true 直接采用原始脚本）
  reoptimizeScript: async (sessionId: string, extraPrompt?: string, useOriginal?: boolean): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/reoptimize`, {
      extra_prompt: extraPrompt,
      use_original: useOriginal,
    })
    return data
  },

  // 步骤3：生成思维导图
  generateMindmap: async (sessionId: string, extraPrompt?: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/mindmap`, {
      extra_prompt: extraPrompt,
    })
    return data
  },

  // 步骤3：重新生成思维导图（重置后续步骤）
  regenerateMindmap: async (sessionId: string, extraPrompt?: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-mindmap`, {
      extra_prompt: extraPrompt,
    })
    return data
  },

  // 步骤3：人工修改思维导图并保存
  updateMindmap: async (sessionId: string, mindmap: string): Promise<StepResponse> => {
    const { data } = await client.put(`/steps/${sessionId}/mindmap`, { mindmap })
    return data
  },

  // 步骤4：生成素材图（支持选择生图模型配置）
  generateMaterials: async (
    sessionId: string,
    extraPrompt?: string,
    referenceImages?: string[],
    modelConfigId?: string
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/materials`, {
      extra_prompt: extraPrompt,
      reference_images: referenceImages,
      model_config_id: modelConfigId,
    })
    return data
  },

  // 步骤4：生成分片脚本
  generateSegments: async (sessionId: string, extraPrompt?: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/segments`, {
      extra_prompt: extraPrompt,
    })
    return data
  },

  // 步骤5：生成首尾帧
  generateFrames: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/frames`, {})
    return data
  },

  // 步骤6：生成视频
  generateVideos: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/videos`, {})
    return data
  },

  // 步骤4：重新生成素材图（清空后续步骤）
  regenerateMaterials: async (
    sessionId: string,
    extraPrompt?: string,
    referenceImages?: string[],
    modelConfigId?: string
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-materials`, {
      extra_prompt: extraPrompt,
      reference_images: referenceImages,
      model_config_id: modelConfigId,
    })
    return data
  },

  // 步骤4：重新生成分片脚本（清空后续步骤）
  regenerateSegments: async (sessionId: string, extraPrompt?: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-segments`, {
      extra_prompt: extraPrompt,
    })
    return data
  },

  // 步骤5：重新生成首尾帧（清空后续步骤）
  regenerateFrames: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-frames`, {})
    return data
  },

  // 步骤6：重新生成视频
  regenerateVideos: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-videos`, {})
    return data
  },

  // 步骤5：取消首尾帧生成
  cancelFrames: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/cancel-frames`, {})
    return data
  },

  // 步骤5：重置首尾帧状态为未开始
  resetFrames: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/reset-frames`, {})
    return data
  },

  // 步骤6：取消视频生成
  cancelVideos: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/cancel-videos`, {})
    return data
  },

  // 步骤6：恢复视频备份
  restoreVideosBackup: async (sessionId: string): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/restore-videos-backup`, {})
    return data
  },

  // 步骤6：重新生成单个视频
  regenerateSingleVideo: async (sessionId: string, segmentIndex: number): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/regenerate-single-video/${segmentIndex}`, {})
    return data
  },

  // 优化分片提示词（基于首尾帧图片和上下文）
  optimizeSegmentPrompt: async (
    sessionId: string,
    segmentIndex: number,
    customRequirement?: string
  ): Promise<StepResponse> => {
    const { data } = await client.post(`/steps/${sessionId}/optimize-segment-prompt/${segmentIndex}`, {
      custom_requirement: customRequirement,
    })
    return data
  },
}

// 分片编辑 API
export const segmentApi = {
  // 更新分片
  update: async (
    sessionId: string,
    index: number,
    segment: ScriptSegment
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.put(`/segments/${sessionId}/${index}`, segment)
    return data
  },

  // 删除分片
  delete: async (
    sessionId: string,
    index: number
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.delete(`/segments/${sessionId}/${index}`)
    return data
  },

  // 添加分片
  add: async (
    sessionId: string,
    segment: Omit<ScriptSegment, 'index'>,
    insertAfter: number = -1
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.post(`/segments/${sessionId}/add`, {
      ...segment,
      insert_after: insertAfter,
    })
    return data
  },

  // 批量重新生成分片
  batchRegenerate: async (
    sessionId: string,
    segmentIndices: number[],
    extraPrompt?: string
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.post(`/segments/${sessionId}/batch-regenerate`, {
      segment_indices: segmentIndices,
      extra_prompt: extraPrompt,
    })
    return data
  },
}

// 首尾帧管理 API
export const frameApi = {
  // 重新生成首尾帧
  regenerate: async (
    sessionId: string,
    segmentIndex: number,
    frameType: 'first' | 'last',
    customPrompt?: string,
    referenceImages?: string[]
  ): Promise<{ success: boolean; message: string; frame_path?: string }> => {
    const { data } = await client.post(
      `/frames/${sessionId}/${segmentIndex}/regenerate`,
      {
        frame_type: frameType,
        custom_prompt: customPrompt,
        reference_images: referenceImages,
      }
    )
    return data
  },

  // 上传首尾帧
  upload: async (
    sessionId: string,
    segmentIndex: number,
    frameType: 'first' | 'last',
    imagePath: string
  ): Promise<{ success: boolean; message: string; frame_path?: string }> => {
    const { data } = await client.post(
      `/frames/${sessionId}/${segmentIndex}/upload`,
      { frame_type: frameType, image_path: imagePath }
    )
    return data
  },

  // 复用帧（支持选择任意分片的帧）
  reuse: async (
    sessionId: string,
    segmentIndex: number,
    frameType: 'first' | 'last',
    sourceSegmentIndex?: number,
    sourceFrameType?: 'first' | 'last'
  ): Promise<{ success: boolean; message: string; frame_path?: string }> => {
    const { data } = await client.post(
      `/frames/${sessionId}/${segmentIndex}/reuse`,
      {
        frame_type: frameType,
        source_segment_index: sourceSegmentIndex,
        source_frame_type: sourceFrameType,
      }
    )
    return data
  },

  // 使用上一个分片视频的结尾快照作为首帧
  useVideoSnapshot: async (
    sessionId: string,
    segmentIndex: number
  ): Promise<{ success: boolean; message: string; frame_path?: string; step_completed?: boolean }> => {
    const { data } = await client.post(
      `/frames/${sessionId}/${segmentIndex}/use-video-snapshot`
    )
    return data
  },

  // 检查步骤6是否已完成
  checkCompletion: async (
    sessionId: string
  ): Promise<{ success: boolean; message: string; step_completed?: boolean }> => {
    const { data } = await client.post(
      `/frames/${sessionId}/check-completion`
    )
    return data
  },

  // 更新相邻分片之间的 overlap 参数
  updateOverlap: async (
    sessionId: string,
    overlapSeconds: number
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.put(`/frames/${sessionId}/overlap`, {
      overlap_seconds: overlapSeconds,
    })
    return data
  },
}

// 会话资产管理 API（素材管理台：音频/图片素材）
export const assetApi = {
  // 列出会话资产（可按类型过滤）
  list: async (
    sessionId: string,
    assetType?: 'audio' | 'image'
  ): Promise<{ success: boolean; assets: SessionAsset[] }> => {
    const params = assetType ? { asset_type: assetType } : {}
    const { data } = await client.get(`/assets/${sessionId}`, { params })
    return data
  },

  // 上传资产（音频/图片）
  upload: async (
    sessionId: string,
    assetType: 'audio' | 'image',
    file: File
  ): Promise<{ success: boolean; message: string; asset: SessionAsset }> => {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await client.post(`/assets/${sessionId}/upload`, formData, {
      params: { asset_type: assetType },
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return data
  },

  // 删除资产
  remove: async (
    sessionId: string,
    assetId: string
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.delete(`/assets/${sessionId}/${assetId}`)
    return data
  },
}

// 生图模型管理 API
export const modelApi = {
  // 列出全部模型配置（可按类型过滤：image / chat）
  list: async (
    modelType?: 'image' | 'chat'
  ): Promise<{ success: boolean; models: ImageModelConfig[] }> => {
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
  }): Promise<{ success: boolean; message: string; model: ImageModelConfig }> => {
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
      model_type?: 'image' | 'chat'
    }
  ): Promise<{ success: boolean; message: string; model: ImageModelConfig }> => {
    const { data } = await client.put(`/models/${modelId}`, payload)
    return data
  },

  // 设为默认模型
  setDefault: async (
    modelId: string
  ): Promise<{ success: boolean; message: string; model: ImageModelConfig }> => {
    const { data } = await client.post(`/models/${modelId}/set-default`)
    return data
  },

  // 删除模型配置
  remove: async (modelId: string): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.delete(`/models/${modelId}`)
    return data
  },
}

// 提示词管理 API（分片镜头 skill 提示词）
export const promptApi = {
  // 列出全部提示词模板
  list: async (): Promise<{ success: boolean; prompts: PromptTemplate[] }> => {
    const { data } = await client.get('/prompts')
    return data
  },

  // 获取单个提示词内容
  get: async (
    name: string
  ): Promise<{ success: boolean; prompt: PromptTemplate }> => {
    const { data } = await client.get(`/prompts/${name}`)
    return data
  },

  // 保存提示词（markdown 覆盖写）
  save: async (
    name: string,
    content: string
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.put(`/prompts/${name}`, { content })
    return data
  },
}

// 素材图管理 API
export const materialApi = {
  // 编辑素材图（使用图生图）
  edit: async (
    sessionId: string,
    index: number,
    prompt: string,
    description?: string,
    referenceImages?: string[],
    originalImagePath?: string
  ): Promise<{ success: boolean; message: string; image_path?: string }> => {
    const { data } = await client.post(`/materials/${sessionId}/${index}/edit`, {
      prompt,
      description,
      reference_images: referenceImages,
      original_image_path: originalImagePath,
    })
    return data
  },

  // 重新生成素材图
  regenerate: async (
    sessionId: string,
    index: number,
    customPrompt?: string
  ): Promise<{ success: boolean; message: string; image_path?: string }> => {
    const { data } = await client.post(`/materials/${sessionId}/${index}/regenerate`, {
      custom_prompt: customPrompt,
    })
    return data
  },

  // 删除素材图
  delete: async (
    sessionId: string,
    index: number
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.delete(`/materials/${sessionId}/${index}`)
    return data
  },

  // 仅更新素材图描述（不重新生成图片）
  updateDescription: async (
    sessionId: string,
    index: number,
    description: string
  ): Promise<{ success: boolean; message: string }> => {
    const { data } = await client.put(`/materials/${sessionId}/${index}/description`, {
      description,
    })
    return data
  },

  // 新增素材图
  add: async (
    sessionId: string,
    prompt: string,
    description?: string,
    referenceImages?: string[]
  ): Promise<{ success: boolean; message: string; image_path?: string; index?: number }> => {
    const { data } = await client.post(`/materials/${sessionId}/add`, {
      prompt,
      description,
      reference_images: referenceImages,
    })
    return data
  },
}

// 文件上传 API
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

export default client
