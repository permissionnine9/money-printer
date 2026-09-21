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

// 素材库条目（跨剧本会话/本剧本历史的已完成定妆照）
export interface LookbookLibraryItem {
  image_id: string
  image_path: string
  description: string
  entity_id: string
  entity_name: string // 空串 = 源实体已不存在（重建/删除）
  entity_exists: boolean
  created_at: string
}

export interface LookbookLibraryGroup {
  key: string // 'current' | 源 session_id
  label: string
  session_id: string
  is_current: boolean
  materials: LookbookLibraryItem[]
}

// 构思对话消息（刷新还原用副本）
export interface IdeationMessage {
  role: 'user' | 'assistant'
  content: string
  kind?: 'story_logic'
}

export interface ScriptSessionDetail {
  session_id: string
  title?: string  // 剧本名（大纲根节点，未生成大纲时为空）
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
  type: 'thinking' | 'text_delta' | 'tool_use' | 'tool_result' | 'result' | 'error' | 'connected' | 'final' | 'done' | 'prompt' | 'queued' | 'started'
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
  // queued 事件（入队时前面待执行的任务数）
  queue_position?: number
  // prompt 事件（本次 run 最终渲染的提示词）
  system_prompt?: string
  user_prompt?: string
  model?: string
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
  film_style?: string  // 影视风格
  max_segment_duration?: number  // 最大分片时长（秒）
}

// 分镜引用的素材图（description 为分镜侧独立副本，默认带出库内描述）
export interface SegmentReferenceImage {
  image_id: string  // mat_* 分集素材 / lookbook_lb_* 定妆照
  image_path: string
  description: string
}

// 分镜（分镜大纲产出、分镜管理的基本单元）
export interface StoryboardSegment {
  index: number  // 分镜索引（从 0 开始）
  title: string
  outline: string  // 分镜大纲
  mode: 'first_frame' | 'last_frame' | 'all_reference' | 'first_last_frame'  // 分镜形式
  overlap: number  // 与上一分镜重叠秒数（0-3，仅全能参考模式使用）
  duration?: number  // 建议时长（秒，分镜大纲阶段 LLM 分析；第 2 步导图展示、第 3 步参考）
  prompt: string   // 已生成的分镜提示词
  reference_images?: SegmentReferenceImage[]  // 参考素材图（仅全能参考模式）
  configured?: boolean  // 用户手动确认当前分镜配置完成（修改配置后自动回退）
}

// 素材池条目（选择弹窗 / @ 引用候选）
export interface PoolMaterial {
  image_id: string
  image_path: string
  description: string
  title?: string  // 分集素材的素材名（定妆照无）
}

export interface MaterialPoolGroup {
  key: string  // lookbook / current / episode_{ep_id}
  label: string
  episode_id?: string
  materials: PoolMaterial[]
}

// 分镜提示词生成弹窗的上下文
export interface SegmentPromptContext {
  episode_title: string
  story_outline: string
  episode_context: string
  video_params: VideoParams
  segment: StoryboardSegment
  prev_segment: StoryboardSegment | null
  reference_images?: SegmentReferenceImage[]
  overlap: number
  effective_overlap: number
  overlap_rule: string
}

// ComfyUI 整段生成的最终视频信息
export interface FinalVideo {
  video_path: string
  prompt_id: string
  mock: boolean
  overlap_seconds: number  // 段间重叠合计秒数（逐段值见 timeline_data._overlap_seconds）
  segment_count: number
}

// 「导入到 ComfyUI」暂存摘要（两段式阶段一结果，session.step_results.comfyui_import）
export interface ComfyUIImport {
  segment_indexes: number[]
  segment_count: number
  image_count: number
  audio_count: number
  total_duration: number
  global_prompt: string
  mock: boolean
  imported_at: string
  // UI 工作流落盘结果（mock/落盘失败时无）：ComfyUI 网页「在 ComfyUI 中打开」直达链接用
  ui_workflow_name?: string
  comfyui_url?: string
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
  category?: string  // 分类：script=剧本创作 video=视频生成，空/未知归「其他」
  step?: number      // 组内展示顺序（升序），缺省排在最后
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
  script_title?: string  // 引用的剧本名（视频会话）
  episode_title?: string // 引用的分集名（视频会话）
  episode_number?: number // 集数（从 episode_id 解析，如 ep_01 → 1）
}

export interface SessionDetail extends Session {
  step_results: Record<string, any>
}

export interface StepResponse {
  success: boolean
  message: string
  data?: any
}

// ==================== 素材管理 ====================

/** 生成图素材的引用位置（实体 / 分镜） */
export interface MaterialReference {
  ref_type: 'entity' | 'segment'
  script_session_id: string
  script_title: string
  entity_id?: string
  entity_name?: string
  episode_id?: string
  segment_index?: number
  segment_title?: string
}

/** 视频素材的引用位置 */
export interface VideoReference {
  video_session_id: string
  script_title: string
}

/** 生成图素材条目（定妆照 / 分集素材图） */
export interface GeneratedMaterialItem {
  image_id: string
  image_path: string
  is_remote: boolean
  description: string
  script_session_id: string
  script_title: string
  created_at: string
  size: number
  reference_count: number
  references: MaterialReference[]
  entity_id?: string // 定妆照所属实体
  episode_id?: string // 分集素材图所属分集
  title?: string // 分集素材图标题
}

/** 文件型素材条目（上传参考图 / 视频） */
export interface FileMaterialItem {
  path: string
  name: string
  size: number
  mtime: number
  reference_count: number
  references?: VideoReference[]
  script_title?: string // 视频归属剧本（可查到时）
}

export interface MaterialListResponse {
  kind: string
  items: GeneratedMaterialItem[] | FileMaterialItem[]
  total: number
}

/** 孤儿文件条目（无 DB 记录且无引用的磁盘文件） */
export interface OrphanFileItem {
  path: string
  kind: 'image' | 'video' | 'upload'
  size: number
  mtime: number
}

export interface OrphanScanResponse {
  items: OrphanFileItem[]
  total: number
  total_size: number
}
