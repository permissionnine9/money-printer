/**
 * 主应用组件
 */
import { useEffect, useCallback } from 'react'
import { Button, Card, Space, message } from 'antd'
import { PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import { MainLayout } from './components/layout/MainLayout'
import {
  StepNavigator,
  Step1Script,
  Step2Optimize,
  Step3Materials,
  Step4Segments,
  Step5Frames,
  Step6Videos,
} from './components/workflow'
import { useSessionStore } from './stores/sessionStore'
import { useWorkflowStore } from './stores/workflowStore'

import './App.css'

function App() {
  const {
    currentSession,
    loading,
    error,
    createSession,
    loadSession,
    refreshSession,
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

  // 处理创建新会话
  const handleCreateSession = async () => {
    await createSession()
    // URL 会通过上面的 useEffect 自动更新
  }

  return (
    <MainLayout>
      <div style={{ maxWidth: 1400, margin: '0 auto' }}>
        {/* 会话控制 */}
        <Card
          title="会话管理"
          extra={
            <Space>
              <Button
                type="primary"
                icon={<PlusOutlined />}
                onClick={handleCreateSession}
                loading={loading}
              >
                新建会话
              </Button>
              {currentSession && (
                <Button
                  icon={<ReloadOutlined />}
                  onClick={refreshSession}
                  loading={loading}
                >
                  刷新
                </Button>
              )}
            </Space>
          }
          style={{ marginBottom: 24 }}
        >
          {currentSession ? (
            <div>
              <p>
                <strong>会话ID:</strong> {currentSession.session_id}
              </p>
              <p>
                <strong>已完成步骤:</strong> {currentSession.current_step} / 6
              </p>
              <p>
                <strong>状态:</strong> {currentSession.status}
              </p>
            </div>
          ) : (
            <p>请创建新会话或选择已有会话</p>
          )}
        </Card>

        {/* 步骤导航 */}
        {currentSession && (
          <>
            <StepNavigator
              session={currentSession}
              currentStep={currentStep}
              onStepChange={setCurrentStep}
            />

            {/* 步骤内容区域 */}
            {currentStep === 0 && <Step1Script session={currentSession} />}
            {currentStep === 1 && <Step2Optimize session={currentSession} />}
            {currentStep === 2 && <Step3Materials session={currentSession} />}
            {currentStep === 3 && <Step4Segments session={currentSession} />}
            {currentStep === 4 && <Step5Frames session={currentSession} />}
            {currentStep === 5 && <Step6Videos session={currentSession} />}
          </>
        )}
      </div>
    </MainLayout>
  )
}

export default App
