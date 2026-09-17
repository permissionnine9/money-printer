/**
 * 创作工作流页面（7 步向导）
 */
import { useEffect, useCallback } from 'react'
import { message } from 'antd'
import {
  StepNavigator,
  Step1Script,
  Step2Optimize,
  Step3Mindmap,
  Step3Materials,
  Step4Segments,
  Step5Frames,
  Step6Videos,
} from '@/components/workflow'
import { useSessionStore } from '@/stores/sessionStore'
import { useWorkflowStore } from '@/stores/workflowStore'

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
      console.log('从 URL 恢复会话:', sessionId)
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

  // 同步会话的当前步骤到 workflowStore
  useEffect(() => {
    if (currentSession) {
      setCurrentStep(currentSession.current_step)
    }
  }, [currentSession?.session_id, currentSession?.current_step, setCurrentStep])

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

          {/* 步骤内容区域（7 步：+思维导图，素材图/分片/首尾帧/视频顺延） */}
          {currentStep === 0 && <Step1Script session={currentSession} />}
          {currentStep === 1 && <Step2Optimize session={currentSession} />}
          {currentStep === 2 && <Step3Mindmap session={currentSession} />}
          {currentStep === 3 && <Step3Materials session={currentSession} />}
          {currentStep === 4 && <Step4Segments session={currentSession} />}
          {currentStep === 5 && <Step5Frames session={currentSession} />}
          {currentStep === 6 && <Step6Videos session={currentSession} />}
        </>
      )}

      {/* 无会话时的引导 */}
      {!currentSession && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <h2>欢迎使用 AI 视频创作智能体</h2>
          <p style={{ color: '#888' }}>从左侧会话管理中新建或选择一个会话开始创作</p>
        </div>
      )}
    </div>
  )
}

export default WorkflowPage
