/**
 * 工作流状态管理
 *
 * 视频工作流 4 步（与 types/index.ts 的 STEP_NAMES 对应）：
 *   0 select_episode      从剧本选集（选择剧本分集与视频参数）
 *   1 storyboard_outline  分镜大纲（导图 + 分镜列表）
 *   2 segment_management  分镜管理（分镜形式配置 + 提示词生成）
 *   3 generate_videos     生成视频
 *
 * 各步骤的执行由对应步骤组件直接调用 stepApi 完成并刷新会话，
 * 此处仅维护用户当前浏览的步骤。
 */
import { create } from 'zustand'

interface WorkflowStore {
  currentStep: number

  // Actions
  setCurrentStep: (step: number) => void
}

export const useWorkflowStore = create<WorkflowStore>((set) => ({
  currentStep: 0,

  setCurrentStep: (step: number) => {
    set({ currentStep: step })
  },
}))
