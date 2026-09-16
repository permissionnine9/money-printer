/**
 * 会话状态管理
 */
import { create } from 'zustand'
import type { Session, SessionDetail, StepName } from '@/types'
import { STEP_NAME_TO_INDEX } from '@/types'
import { sessionApi } from '@/api/client'

// 后端返回的原始会话数据
interface RawSessionData {
  session_id: string
  created_at: string
  updated_at: string
  current_step: string  // 后端返回的是步骤名称
  status: string
  completed_steps: string[]
  step_results?: Record<string, any>
}

// 将后端返回的步骤名称转换为步骤索引
const stepNameToIndex = (stepName: string | null | undefined, completedSteps?: string[]): number => {
  // 如果步骤名称有效，直接返回对应索引
  if (stepName && STEP_NAME_TO_INDEX[stepName as StepName] !== undefined) {
    return STEP_NAME_TO_INDEX[stepName as StepName]
  }

  // 如果 current_step 为空但已完成最后一步，显示最后一步
  const lastStepName = 'generate_videos'
  if (completedSteps?.includes(lastStepName)) {
    return STEP_NAME_TO_INDEX[lastStepName]
  }

  // 默认返回第一步
  return 0
}

// 转换原始会话数据为前端使用的格式
const transformSessionData = (raw: RawSessionData): SessionDetail => {
  return {
    session_id: raw.session_id,
    created_at: raw.created_at,
    updated_at: raw.updated_at,
    current_step: stepNameToIndex(raw.current_step, raw.completed_steps),
    status: raw.status,
    completed_steps: raw.completed_steps,
    step_results: raw.step_results || {},
  }
}

interface SessionStore {
  currentSession: SessionDetail | null
  sessions: Session[]
  loading: boolean
  error: string | null

  // Actions
  createSession: () => Promise<void>
  loadSession: (sessionId: string) => Promise<void>
  loadSessions: () => Promise<void>
  deleteSession: (sessionId: string) => Promise<void>
  refreshSession: () => Promise<void>
  setCurrentSession: (session: SessionDetail | null) => void
  clearError: () => void
}

export const useSessionStore = create<SessionStore>((set, get) => ({
  currentSession: null,
  sessions: [],
  loading: false,
  error: null,

  createSession: async () => {
    set({ loading: true, error: null })
    try {
      const session = await sessionApi.create()
      // 加载会话详情
      const detail = await sessionApi.get(session.session_id)
      set({ currentSession: transformSessionData(detail as unknown as RawSessionData), loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  loadSession: async (sessionId: string) => {
    set({ loading: true, error: null })
    try {
      const session = await sessionApi.get(sessionId)
      set({ currentSession: transformSessionData(session as unknown as RawSessionData), loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  loadSessions: async () => {
    set({ loading: true, error: null })
    try {
      const { sessions } = await sessionApi.list()
      // 转换会话列表中的 current_step
      const transformedSessions = sessions.map((s) => {
        const raw = s as unknown as RawSessionData
        return {
          ...s,
          current_step: stepNameToIndex(raw.current_step, raw.completed_steps),
        }
      })
      set({ sessions: transformedSessions, loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  deleteSession: async (sessionId: string) => {
    set({ loading: true, error: null })
    try {
      await sessionApi.delete(sessionId)
      // 重新加载会话列表
      const { sessions } = await sessionApi.list()
      const transformedSessions = sessions.map((s) => {
        const raw = s as unknown as RawSessionData
        return {
          ...s,
          current_step: stepNameToIndex(raw.current_step, raw.completed_steps),
        }
      })
      set({ sessions: transformedSessions, loading: false })
      // 如果删除的是当前会话，清空当前会话
      if (get().currentSession?.session_id === sessionId) {
        set({ currentSession: null })
      }
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  refreshSession: async () => {
    const sessionId = get().currentSession?.session_id
    if (!sessionId) return

    try {
      const session = await sessionApi.get(sessionId)
      set({ currentSession: transformSessionData(session as unknown as RawSessionData) })
    } catch (error) {
      set({ error: (error as Error).message })
    }
  },

  setCurrentSession: (session) => {
    set({ currentSession: session })
  },

  clearError: () => {
    set({ error: null })
  },
}))
