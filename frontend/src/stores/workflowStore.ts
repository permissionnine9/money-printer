/**
 * 工作流状态管理
 */
import { create } from 'zustand'
import { stepApi } from '@/api/client'
import { useSessionStore } from './sessionStore'

interface WorkflowStore {
  loading: boolean
  error: string | null
  currentStep: number

  // Actions
  executeStep: (step: number, ...args: any[]) => Promise<void>
  setCurrentStep: (step: number) => void
  clearError: () => void
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  loading: false,
  error: null,
  currentStep: 0,

  executeStep: async (step: number, ...args: any[]) => {
    const sessionId = useSessionStore.getState().currentSession?.session_id
    if (!sessionId) {
      set({ error: '请先创建或选择会话' })
      return
    }

    set({ loading: true, error: null })

    try {
      let response
      switch (step) {
        case 1:
          response = await stepApi.submitScript(sessionId, args[0], args[1])
          break
        case 2:
          response = await stepApi.optimizeScript(sessionId)
          break
        case 3:
          response = await stepApi.generateMaterials(sessionId)
          break
        case 4:
          response = await stepApi.generateSegments(sessionId)
          break
        case 5:
          response = await stepApi.generateFrames(sessionId)
          break
        case 6:
          response = await stepApi.generateVideos(sessionId)
          break
        default:
          throw new Error(`未知步骤: ${step}`)
      }

      if (!response.success) {
        set({ error: response.message, loading: false })
        return
      }

      // 刷新会话数据
      await useSessionStore.getState().refreshSession()
      set({ loading: false })
    } catch (error) {
      set({ error: (error as Error).message, loading: false })
    }
  },

  setCurrentStep: (step: number) => {
    set({ currentStep: step })
  },

  clearError: () => {
    set({ error: null })
  },
}))
