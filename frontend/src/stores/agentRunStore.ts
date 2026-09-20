/**
 * 全局 Agent 后台任务管理：分镜提示词生成等异步 run，跨步骤/跨页面持续跟踪
 */
import { create } from 'zustand'

export interface AgentRunTask {
  runId: string
  sessionId: string
  segmentIndex: number
  segmentTitle?: string
  status: 'running' | 'success' | 'error'
  error?: string | null
  /** 是否展开进度弹窗（同一时间最多一个展开） */
  expanded: boolean
}

interface AgentRunStore {
  runs: AgentRunTask[]
  /** 发起新任务：追加并展开，其余全部收起 */
  addRun: (task: Pick<AgentRunTask, 'runId' | 'sessionId' | 'segmentIndex' | 'segmentTitle'>) => void
  /** 展开某个任务（其余收起） */
  expandRun: (runId: string) => void
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
      runs: [...s.runs.map((r) => ({ ...r, expanded: false })), { ...task, status: 'running', expanded: true }],
    })),
  expandRun: (runId) =>
    set((s) => ({ runs: s.runs.map((r) => ({ ...r, expanded: r.runId === runId })) })),
  collapseRun: (runId) =>
    set((s) => ({ runs: s.runs.map((r) => (r.runId === runId ? { ...r, expanded: false } : r)) })),
  markRunStatus: (runId, status, error) =>
    set((s) => ({
      runs: s.runs.map((r) => (r.runId === runId ? { ...r, status, error: error ?? null } : r)),
    })),
  removeRun: (runId) => set((s) => ({ runs: s.runs.filter((r) => r.runId !== runId) })),
}))

/** 组件外可调用的防重复守卫：同会话同分镜是否已有进行中的提示词生成 */
export const hasRunningSegmentPrompt = (sessionId: string, segmentIndex: number) =>
  useAgentRunStore
    .getState()
    .runs.some((r) => r.sessionId === sessionId && r.segmentIndex === segmentIndex && r.status === 'running')
