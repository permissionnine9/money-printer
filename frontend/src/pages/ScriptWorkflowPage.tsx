/**
 * 创作剧本工作流页面（4 步向导：故事构思 → 故事大纲 → 分集设计 → 全剧核心素材生成）
 */
import { useEffect, useState, type CSSProperties } from 'react'
import { message, Steps } from 'antd'
import {
  StepIdeationChat,
  StepOutline,
  StepEpisodeDesign,
  StepLookbook,
} from '@/components/script'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'

const STEPS = [
  { title: '故事构思', description: '与 AI 多轮讨论并收敛故事逻辑' },
  { title: '故事大纲', description: '生成可编辑的思维导图大纲' },
  { title: '分集设计', description: '逐集设计矛盾与因果链，维护实体库' },
  { title: '全剧核心素材生成', description: '人物三视图设定图 + 场景全景素材图' },
]

// 隐藏而非卸载（keep-alive）：切步骤不断开 SSE 观流、不丢流式/生成进度
const HIDDEN: CSSProperties = { display: 'none' }

function ScriptWorkflowPage() {
  const {
    currentSession,
    loading,
    error,
    loadSession,
    clearError,
  } = useScriptSessionStore()

  // 浏览步骤（纯前端切换，不回写后端）
  const [viewStep, setViewStep] = useState(0)

  // 更新 URL 中的 session_id
  const updateUrlSessionId = (sessionId: string | null) => {
    const url = new URL(window.location.href)
    if (sessionId) {
      url.searchParams.set('session_id', sessionId)
    } else {
      url.searchParams.delete('session_id')
    }
    window.history.replaceState({}, '', url.toString())
  }

  // 从 URL 获取 session_id
  const getSessionIdFromUrl = (): string | null => {
    const url = new URL(window.location.href)
    return url.searchParams.get('session_id')
  }

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
  }, [currentSession?.session_id])

  // 会话切换时同步浏览步骤到会话进度（步骤内完成后不自动跳转，由用户点击切换）
  useEffect(() => {
    if (currentSession) {
      setViewStep(Number(currentSession.current_step))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSession?.session_id])

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 步骤导航 */}
      {currentSession && (
        <>
          <Steps
            current={viewStep}
            onChange={setViewStep}
            items={STEPS}
            style={{ marginTop: 8, marginBottom: 8 }}
          />

          {/* 步骤内容区域（4 步，keep-alive：仅隐藏非当前步骤，SSE 与生成进度保活） */}
          <div style={viewStep === 0 ? undefined : HIDDEN}>
            <StepIdeationChat session={currentSession} />
          </div>
          <div style={viewStep === 1 ? undefined : HIDDEN}>
            <StepOutline session={currentSession} />
          </div>
          <div style={viewStep === 2 ? undefined : HIDDEN}>
            <StepEpisodeDesign session={currentSession} />
          </div>
          <div style={viewStep === 3 ? undefined : HIDDEN}>
            <StepLookbook session={currentSession} />
          </div>
        </>
      )}

      {/* 无会话时的引导 */}
      {!currentSession && !loading && (
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <h2>欢迎使用 AI 剧本创作智能体</h2>
          <p style={{ color: '#888' }}>从左侧会话管理中新建或选择一个剧本会话开始创作</p>
        </div>
      )}
    </div>
  )
}

export default ScriptWorkflowPage
