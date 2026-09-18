/**
 * 创作工作流页面（4 步向导）
 */
import { useEffect, useCallback, type CSSProperties } from 'react'
import { message } from 'antd'
import {
  StepNavigator,
  StepSelectEpisode,
  StepStoryboardOutline,
  StepSegmentManagement,
  Step6Videos,
} from '@/components/workflow'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkflowStore } from '@/stores/workflowStore'

// 隐藏而非卸载（keep-alive）：切步骤不断开 SSE 观流、不丢流式/生成进度
const HIDDEN: CSSProperties = { display: 'none' }

function WorkflowPage() {
  const {
    currentSession,
    loading,
    error,
    loadSession,
    clearError,
  } = useSessionStore()

  const { currentStep, setCurrentStep } = useWorkflowStore()

  // 更新 URL 中的 session_id
  const updateUrlSessionId = useCallback((sessionId: string | null) => {
    const url = new URL(window.location.href)
    if (sessionId) {
      url.searchParams.set('session_id', sessionId)
    } else {
      url.searchParams.delete('session_id')
    }
    window.history.replaceState({}, '', url.toString())
  }, [])

  // 从 URL 获取 session_id
  const getSessionIdFromUrl = useCallback((): string | null => {
    const url = new URL(window.location.href)
    return url.searchParams.get('session_id')
  }, [])

  // 错误提示
  useEffect(() => {
    if (error) {
      message.error(error)
      clearError()
    }
  }, [error, clearError])

  // 页面加载时从 URL 恢复会话
  useEffect(() => {
    const sessionId = getSessionIdFromUrl()
    if (sessionId) {
      loadSession(sessionId)
    }
    // 只在组件挂载时执行一次
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // 当前会话变化时更新 URL
  useEffect(() => {
    if (currentSession?.session_id) {
      updateUrlSessionId(currentSession.session_id)
    }
  }, [currentSession?.session_id, updateUrlSessionId])

  // 同步会话的当前步骤到 workflowStore（仅在会话切换时；与剧本侧一致，
  // 生成完成推进 current_step 不打断用户正在浏览的步骤）
  useEffect(() => {
    if (currentSession) {
      setCurrentStep(currentSession.current_step)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSession?.session_id])

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 步骤导航 */}
      {currentSession && (
        <>
          <StepNavigator
            session={currentSession}
            currentStep={currentStep}
            onStepChange={setCurrentStep}
          />

          {/* 步骤内容区域（4 步，keep-alive：仅隐藏非当前步骤，SSE 与生成进度保活） */}
          <div style={currentStep === 0 ? undefined : HIDDEN}>
            <StepSelectEpisode session={currentSession} />
          </div>
          <div style={currentStep === 1 ? undefined : HIDDEN}>
            <StepStoryboardOutline session={currentSession} />
          </div>
          <div style={currentStep === 2 ? undefined : HIDDEN}>
            <StepSegmentManagement session={currentSession} />
          </div>
          <div style={currentStep === 3 ? undefined : HIDDEN}>
            <Step6Videos session={currentSession} />
          </div>
        </>
      )}

      {/* 无会话时的引导 */}
      {!currentSession && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <h2>欢迎使用 AI 视频创作智能体</h2>
          <p style={{ color: '#888' }}>
            从左侧会话管理中新建一个视频会话即可开始创作（新会话将自动从剧本选集开始）
          </p>
        </div>
      )}
    </div>
  )
}

export default WorkflowPage
