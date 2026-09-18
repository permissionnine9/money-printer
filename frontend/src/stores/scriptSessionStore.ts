/**
 * 剧本会话 store（镜像 sessionStore 结构，与视频 store 独立）
 */
import { create } from 'zustand'
import {
  SCRIPT_STEP_NAMES,
  SCRIPT_STEP_NAME_TO_INDEX,
  type ScriptStepName,
  type ScriptSessionDetail,
} from '@/types'
import { scriptSessionApi } from '@/api/client'

/** 后端步骤名 → 前端步骤索引；全完成 → 最后一步 */
function scriptStepNameToIndex(session: ScriptSessionDetail): number {
  const raw = (session as any).current_step_name || (session as any).current_step
  if (typeof raw === 'string' && raw in SCRIPT_STEP_NAME_TO_INDEX) {
    return SCRIPT_STEP_NAME_TO_INDEX[raw as ScriptStepName]
  }
  // 全部完成 → 最后一步
  if (session.completed_steps?.includes(SCRIPT_STEP_NAMES[SCRIPT_STEP_NAMES.length - 1])) {
    return SCRIPT_STEP_NAMES.length - 1
  }
  // 第一个未完成步骤
  const firstIncomplete = SCRIPT_STEP_NAMES.find((name) => !session.completed_steps?.includes(name))
  return firstIncomplete !== undefined ? SCRIPT_STEP_NAME_TO_INDEX[firstIncomplete] : 0
}

/** 后端数据 → 前端 SessionDetail（current_step 转索引） */
function transformScriptSession(data: any): ScriptSessionDetail {
  return {
    ...data,
    current_step: scriptStepNameToIndex(data),
  } as ScriptSessionDetail
}

interface ScriptSessionState {
  currentSession: ScriptSessionDetail | null
  sessions: ScriptSessionDetail[]
  loading: boolean
  error: string | null

  createSession: () => Promise<ScriptSessionDetail>
  loadSessions: () => Promise<void>
  loadSession: (sessionId: string) => Promise<ScriptSessionDetail>
  refreshSession: () => Promise<void>
  deleteSession: (sessionId: string) => Promise<void>
  setCurrentSession: (session: ScriptSessionDetail | null) => void
  clearError: () => void
}

export const useScriptSessionStore = create<ScriptSessionState>((set, get) => ({
  currentSession: null,
  sessions: [],
  loading: false,
  error: null,

  createSession: async () => {
    set({ loading: true, error: null })
    try {
      const session = await scriptSessionApi.create()
      const transformed = transformScriptSession(session)
      set({ currentSession: transformed, loading: false })
      return transformed
    } catch (err: any) {
      set({ loading: false, error: err.message || '创建剧本会话失败' })
      throw err
    }
  },

  loadSessions: async () => {
    set({ loading: true, error: null })
    try {
      const result = await scriptSessionApi.list()
      set({
        sessions: (result.sessions || []).map(transformScriptSession),
        loading: false,
      })
    } catch (err: any) {
      set({ loading: false, error: err.message || '获取剧本会话列表失败' })
    }
  },

  loadSession: async (sessionId: string) => {
    set({ loading: true, error: null })
    try {
      const session = await scriptSessionApi.get(sessionId)
      const transformed = transformScriptSession(session)
      set({ currentSession: transformed, loading: false })
      return transformed
    } catch (err: any) {
      set({ loading: false, error: err.message || '获取剧本会话失败' })
      throw err
    }
  },

  refreshSession: async () => {
    const sessionId = get().currentSession?.session_id
    if (!sessionId) return
    try {
      const session = await scriptSessionApi.get(sessionId)
      set({ currentSession: transformScriptSession(session) })
    } catch {
      // 静默失败（轮询场景）
    }
  },

  deleteSession: async (sessionId: string) => {
    await scriptSessionApi.delete(sessionId)
    const { currentSession, sessions } = get()
    set({
      sessions: sessions.filter((s) => s.session_id !== sessionId),
      currentSession: currentSession?.session_id === sessionId ? null : currentSession,
    })
  },

  setCurrentSession: (session) => set({ currentSession: session }),
  clearError: () => set({ error: null }),
}))
