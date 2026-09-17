/**
 * 类型定义
 */

// 步骤名称（与后端 STEPS 列表保持一致，7步流程）
export const STEP_NAMES = [
  'submit_script_and_params',
  'optimize_script',
  'generate_mindmap',
  'generate_material_images',
  'generate_segment_scripts',
  'generate_segment_frames',
  'generate_videos',
] as const

export type StepName = typeof STEP_NAMES[number]

// 步骤名称到索引的映射
export const STEP_NAME_TO_INDEX: Record<StepName, number> = {
  'submit_script_and_params': 0,
  'optimize_script': 1,
  'generate_mindmap': 2,
  'generate_material_images': 3,
  'generate_segment_scripts': 4,
  'generate_segment_frames': 5,
  'generate_videos': 6,
}

export interface VideoParams {
  resolution: string
  aspect_ratio: string
  max_segment_duration?: number  // 最大分片时长（秒）
  overlap_seconds?: number  // 相邻分片重叠时长（秒），用于视频生成时段间过渡
}

export interface ScriptSegment {
  index: number  // 分片索引（必需）
  content: string
  duration: number
  action?: string
  camera_movement?: string
  composition?: string
  atmosphere?: string
  transition?: string
  focus?: string
  first_frame_mode?: string  // generate / generate_continuous / reuse_prev / use_video_snapshot / all_reference
  last_frame_mode?: string   // generate / generate_continuous / reuse_next / all_reference
  video_generation_mode?: string  // 'first_last_frame' 或 'first_frame_reference'
}

export interface MaterialImage {
  image_id: string
  image_path: string
  prompt: string
  description: string
  image_type?: string  // 'character' | 'props' | 'environment' | 'general'
  task_id?: string
  task_status?: string
}

export interface SegmentFrame {
  segment_index: number
  first_image_id: string
  first_image_path: string
  last_image_id: string
  last_image_path: string
  first_prompt?: string
  last_prompt?: string
  first_status?: string  // pending/completed/failed
  last_status?: string  // pending/completed/failed
}

export interface GeneratedVideo {
  segment_index: number
  video_id: string
  video_path: string
  duration: number
  prompt?: string
  task_status?: string  // pending/completed/failed/cancelled
}

// ComfyUI 整段生成的最终视频信息
export interface FinalVideo {
  video_path: string
  prompt_id: string
  mock: boolean
  overlap_seconds: number
  segment_count: number
}

// 会话资产（音频/图片素材）
export interface SessionAsset {
  asset_id: string
  session_id: string
  asset_type: 'audio' | 'image'
  name: string
  file_path: string
  meta: Record<string, any>
  created_at: string
}

// 生图/chat 模型配置
export interface ImageModelConfig {
  id: string
  name: string
  api_key: string
  base_url: string
  model_id: string
  is_default: boolean
  model_type: 'image' | 'chat'  // image=生图模型 chat=对话/LLM 模型
  created_at: string
  updated_at: string
}

// 提示词模板
export interface PromptTemplate {
  name: string
  description: string
  updated_at?: number
  length?: number
  content?: string
}

export interface Session {
  session_id: string
  created_at: string
  updated_at: string
  current_step: number  // 当前步骤索引（0-5）
  status: string
  completed_steps: string[]  // 已完成的步骤名称列表
}

export interface SessionDetail extends Session {
  step_results: Record<string, any>
}

export interface StepResponse {
  success: boolean
  message: string
  data?: any
}
