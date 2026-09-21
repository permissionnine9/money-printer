/**
 * 全局 Agent 后台任务管理：分镜提示词 / 故事大纲 / 分集设计 / 分镜大纲等异步 run，
 * 跨步骤/跨页面持续跟踪
 */
import { create } from 'zustand'

/** 任务类型（判别字段：决定 Dock 的文案与终态刷新哪个会话 store） */
export type AgentRunKind = 'segment_prompt' | 'outline' | 'episodes' | 'storyboard_outline'

export const RUN_KIND_LABEL: Record<AgentRunKind, string> = {
  segment_prompt: '分镜提示词',
  outline: '故事大纲',
  episodes: '分集设计',
  storyboard_outline: '分镜大纲',
}

export interface AgentRunTask {
  runId: string
  sessionId: string
  kind: AgentRunKind
  segmentIndex?: number
  segmentTitle?: string
  /** 仅 episodes 单集重设计时记录目标集 */
  episodeId?: string
  /** queued=后端队列排队中（并发上限 5），started 事件后转 running */
  status: 'queued' | 'running' | 'success' | 'error'
  error?: string | null
  /** 是否展开进度弹窗（同一时间最多一个展开） */
  expanded: boolean
}

/** 任务卡片/弹窗显示名（单一来源，勿在组件里重复拼接） */
export const runDisplayName = (
  run: Pick<AgentRunTask, 'kind' | 'segmentIndex' | 'segmentTitle' | 'episodeId'>,
): string => {
  switch (run.kind) {
    case 'segment_prompt':
      return `分镜 ${(run.segmentIndex ?? 0) + 1}${run.segmentTitle ? `《${run.segmentTitle}》` : ''}`
    case 'outline':
      return '故事大纲'
    case 'episodes':
      return run.episodeId ? `分集重设计 ${run.episodeId}` : '分集设计'
    case 'storyboard_outline':
      return '分镜大纲'
  }
}

interface AgentRunStore {
  runs: AgentRunTask[]
  /** 发起新任务：追加并收起（不自动弹窗，进度从右上角任务按钮查看），其余弹窗全部收起 */
  addRun: (
    task: Pick<AgentRunTask, 'runId' | 'sessionId' | 'kind'> &
      Partial<Pick<AgentRunTask, 'segmentIndex' | 'segmentTitle' | 'episodeId'>>,
  ) => void
  /** 展开某个任务（其余收起） */
  expandRun: (runId: string) => void
  /** 排队任务被 worker 领取开始执行（started 事件驱动） */
  markRunRunning: (runId: string) => void
  /** 收起到右上角 */
  collapseRun: (runId: string) => void
  /** 更新终态（成功时任务即移除，实际仅用于 error） */
  markRunStatus: (runId: string, status: 'success' | 'error', error?: string | null) => void
  removeRun: (runId: string) => void
}

export const useAgentRunStore = create<AgentRunStore>((set) => ({
  runs: [],
  addRun: (task) =>
    set((s) => ({
      runs: [...s.runs.map((r) => ({ ...r, expanded: false })), { ...task, status: 'queued', expanded: false }],
    })),
  expandRun: (runId) => set((s) => ({ runs: s.runs.map((r) => ({ ...r, expanded: r.runId === runId })) })),
  markRunRunning: (runId) =>
    set((s) => ({ runs: s.runs.map((r) => (r.runId === runId && r.status === 'queued' ? { ...r, status: 'running' } : r)) })),
  collapseRun: (runId) => set((s) => ({ runs: s.runs.map((r) => (r.runId === runId ? { ...r, expanded: false } : r)) })),
  markRunStatus: (runId, status, error) =>
    set((s) => ({
      runs: s.runs.map((r) => (r.runId === runId ? { ...r, status, error: error ?? null } : r)),
    })),
  removeRun: (runId) => set((s) => ({ runs: s.runs.filter((r) => r.runId !== runId) })),
}))

/** 组件外可调用的防重复守卫：同会话同类型是否已有进行中/排队中的任务（失败任务不阻塞重试） */
export const hasRunningRun = (sessionId: string, kind: AgentRunKind) =>
  useAgentRunStore
    .getState()
    .runs.some((r) => r.sessionId === sessionId && r.kind === kind && (r.status === 'running' || r.status === 'queued'))

/** 组件外可调用的防重复守卫：同会话同分镜是否已有进行中/排队中的提示词生成 */
export const hasRunningSegmentPrompt = (sessionId: string, segmentIndex: number) =>
  useAgentRunStore.getState().runs.some(
    (r) => r.sessionId === sessionId && r.kind === 'segment_prompt' && r.segmentIndex === segmentIndex && (r.status === 'running' || r.status === 'queued'),
  )
