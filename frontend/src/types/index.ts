/**
 * 类型定义
 */

// ==================== 视频工作流（4步） ====================

export const STEP_NAMES = [
  'select_episode',
  'storyboard_outline',
  'segment_management',
  'generate_videos',
] as const

export type StepName = typeof STEP_NAMES[number]

// 步骤名称到索引的映射
export const STEP_NAME_TO_INDEX: Record<StepName, number> = {
  'select_episode': 0,
  'storyboard_outline': 1,
  'segment_management': 2,
  'generate_videos': 3,
}

// ==================== 剧本工作流（4步） ====================

export const SCRIPT_STEP_NAMES = [
  'story_ideation',
  'story_outline',
  'episode_design',
  'lookbook_images',
] as const

export type ScriptStepName = typeof SCRIPT_STEP_NAMES[number]

export const SCRIPT_STEP_NAME_TO_INDEX: Record<ScriptStepName, number> = {
  'story_ideation': 0,
  'story_outline': 1,
  'episode_design': 2,
  'lookbook_images': 3,
}

// 实体类型：character/scene/clue/foreshadow
export type EntityType = 'character' | 'scene' | 'clue' | 'foreshadow'

export interface ScriptEntity {
  entity_id: string  // chr_001 / scn_001 / clu_001 / fs_001
  script_session_id: string
  entity_type: EntityType
  name: string
  description: string
  meta: Record<string, any>
  lookbook_image_id?: string
  lookbook_image_path?: string
  created_at: string
  updated_at: string
}

// 实体引用（线索/伏笔在分集中的动作）
export interface EntityRef {
  entity_id: string
  action: 'plant' | 'develop' | 'reveal' | 'payoff'
}

// 实体引用集（某实体出现在哪几集、做了什么动作）
export interface EntityReferenceEpisode {
  episode_id: string
  title: string
  actions: string[]
}

export interface EntityReferences {
  entity_id: string
  episodes: EntityReferenceEpisode[]
}

export interface Episode {
  episode_id: string  // ep_01
  script_session_id: string
  title: string
  logline: string
  story_progress: string  // 本集节点进展
  conflict_chain: string
  causality_chain: string
  ending_summary: string
  character_ids: string[]
  scene_ids: string[]
  clue_refs: EntityRef[]
  foreshadow_refs: EntityRef[]
  meta: Record<string, any>
  created_at: string
  updated_at: string
}

// 定妆照（状态机：pending/processing/completed/failed）
export interface LookbookImage {
  image_id: string
  script_session_id: string
  entity_id: string
  prompt: string
  description: string
  image_path: string
  task_id?: string
  task_status: string
  meta?: Record<string, any>
  created_at: string
  updated_at: string
}

// 构思对话消息（刷新还原用副本）
export interface IdeationMessage {
  role: 'user' | 'assistant'
  content: string
  kind?: 'story_logic'
}

export interface ScriptSessionDetail {
  session_id: string
  created_at: string
  updated_at: string
  current_step: string  // 步骤名
  status: string
  workflow_type?: string
  completed_steps: string[]
  step_results: Record<string, any>
}

// ==================== Agent 运行事件（SSE） ====================

export interface AgentEvent {
  type: 'thinking' | 'text_delta' | 'tool_use' | 'tool_result' | 'result' | 'error' | 'connected' | 'final' | 'done'
  seq?: number
  delta?: string
  id?: string
  tool?: string
  input?: Record<string, any>
  result_preview?: string
  text?: string
  session_id?: string
  usage?: { input_tokens: number; output_tokens: number }
  message?: string
  label?: string
  last_seq?: number
  // final 事件（SSE 直跑形态）
  data?: any
  // done 事件（run 观流形态）
  success?: boolean
  error?: string | null
  result?: any
}

// ==================== 视频工作流数据 ====================

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

// 分镜（分镜大纲产出、分镜管理的基本单元）
export interface StoryboardSegment {
  index: number  // 分镜索引（从 0 开始）
  title: string
  outline: string  // 分镜大纲
  mode: 'first_frame' | 'last_frame' | 'all_reference' | 'first_last_frame'  // 分镜形式
  overlap: number  // 与上一分镜重叠秒数（0-3，仅全能参考模式使用）
  duration?: number  // 建议时长（秒，大纲阶段 LLM 分析，仅作参考）
  prompt: string   // 已生成的分镜提示词
}

// 分镜提示词生成弹窗的上下文
export interface SegmentPromptContext {
  episode_title: string
  story_outline: string
  episode_context: string
  video_params: VideoParams
  segment: StoryboardSegment
  prev_segment: StoryboardSegment | null
  overlap: number
  effective_overlap: number
  overlap_rule: string
}

export interface MaterialImage {
  image_id: string
  image_path: string
  prompt: string
  description: string
  image_type?: string  // 'detail_scene' | 'aux_scene' | 'aux_character' | 'props' | 'lookbook' | ...
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

// 生图/chat/agent 模型配置
export interface ImageModelConfig {
  id: string
  name: string
  api_key: string
  base_url: string
  model_id: string
  is_default: boolean
  model_type: 'image' | 'chat' | 'agent'  // image=生图 chat=对话/LLM agent=Agent SDK 端点（Anthropic 协议）
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
  current_step: number  // 当前步骤索引
  status: string
  completed_steps: string[]  // 已完成的步骤名称列表
  legacy?: boolean  // 旧版 5/7 步会话（不兼容，隐藏或提示）
  script_session_id?: string | null
  source_episode_id?: string | null
}

export interface SessionDetail extends Session {
  step_results: Record<string, any>
}

export interface StepResponse {
  success: boolean
  message: string
  data?: any
}
