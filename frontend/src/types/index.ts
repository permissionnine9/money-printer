/**
 * 类型定义
 */

// 步骤名称（与后端 STEPS 列表保持一致）
export const STEP_NAMES = [
  'submit_script_and_params',
  'optimize_script',
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
  'generate_material_images': 2,
  'generate_segment_scripts': 3,
  'generate_segment_frames': 4,
  'generate_videos': 5,
}

export interface VideoParams {
  resolution: string
  aspect_ratio: string
  language: string
  style: string
  perspective: string  // 与后端 VideoParams 保持一致
  max_segment_duration?: number  // 新增：最大分片时长（秒）
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
  first_frame_mode?: string  // 'generate' 或 'reuse_prev'
  last_frame_mode?: string   // 'generate' 或 'reuse_next'
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
