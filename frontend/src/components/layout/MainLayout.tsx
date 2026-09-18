/**
 * 主布局组件：顶部导航 + 左侧会话管理（视频 / 剧本两页各自渲染）+ 内容区
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Layout, Menu } from 'antd'
import {
  VideoCameraOutlined,
  AppstoreOutlined,
  FileTextOutlined,
  FormOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { SessionSider } from '@/components/common/SessionSider'
import type { Session, ScriptSessionDetail } from '@/types'
import { sessionApi, scriptSessionApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import styles from './MainLayout.module.css'

const { Header, Sider, Content, Footer } = Layout

interface MainLayoutProps {
  children: React.ReactNode
}

// 会话跳转：地址栏带 session_id 并整页刷新（与现有模式一致）
function navigateWithSession(sessionId: string) {
  const url = new URL(window.location.href)
  url.searchParams.set('session_id', sessionId)
  window.location.href = url.toString()
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const isWorkflowPage = location.pathname === '/'
  const isScriptPage = location.pathname === '/script'

  // 视频会话
  const currentSession = useSessionStore((state) => state.currentSession)
  const [videoSessions, setVideoSessions] = useState<Session[]>([])
  const [loadingVideoSessions, setLoadingVideoSessions] = useState(false)
  const [creatingVideoSession, setCreatingVideoSession] = useState(false)

  // 剧本会话
  const currentScriptSession = useScriptSessionStore((state) => state.currentSession)
  const [scriptSessions, setScriptSessions] = useState<ScriptSessionDetail[]>([])
  const [loadingScriptSessions, setLoadingScriptSessions] = useState(false)
  const [creatingScriptSession, setCreatingScriptSession] = useState(false)

  const loadVideoSessions = useCallback(async () => {
    setLoadingVideoSessions(true)
    try {
      const result = await sessionApi.list()
      // 旧版 7 步会话不兼容新工作流，隐藏
      setVideoSessions((result.sessions || []).filter((s) => !s.legacy))
    } catch {
      // 静默失败，侧边栏显示空态
    } finally {
      setLoadingVideoSessions(false)
    }
  }, [])

  const loadScriptSessions = useCallback(async () => {
    setLoadingScriptSessions(true)
    try {
      const result = await scriptSessionApi.list()
      setScriptSessions(result.sessions || [])
    } catch {
      // 静默失败
    } finally {
      setLoadingScriptSessions(false)
    }
  }, [])

  useEffect(() => {
    if (isWorkflowPage) loadVideoSessions()
  }, [isWorkflowPage, currentSession?.session_id, loadVideoSessions])

  useEffect(() => {
    if (isScriptPage) loadScriptSessions()
  }, [isScriptPage, currentScriptSession?.session_id, loadScriptSessions])

  // ==================== 视频会话操作 ====================
  const handleCreateVideoSession = async () => {
    setCreatingVideoSession(true)
    try {
      const session = await sessionApi.create()
      navigateWithSession(session.session_id)
    } catch {
      setCreatingVideoSession(false)
    }
  }

  const handleDeleteVideoSession = async (sessionId: string) => {
    try {
      await sessionApi.delete(sessionId)
      if (currentSession?.session_id === sessionId) {
        const url = new URL(window.location.href)
        url.searchParams.delete('session_id')
        window.location.href = url.toString()
        return
      }
      await loadVideoSessions()
    } catch {
      // ignore
    }
  }

  // ==================== 剧本会话操作 ====================
  const handleCreateScriptSession = async () => {
    setCreatingScriptSession(true)
    try {
      const session = await scriptSessionApi.create()
      navigateWithSession(session.session_id)
    } catch {
      setCreatingScriptSession(false)
    }
  }

  const handleDeleteScriptSession = async (sessionId: string) => {
    try {
      await scriptSessionApi.delete(sessionId)
      if (currentScriptSession?.session_id === sessionId) {
        const url = new URL(window.location.href)
        url.searchParams.delete('session_id')
        window.location.href = url.toString()
        return
      }
      await loadScriptSessions()
    } catch {
      // ignore
    }
  }

  const navItems = [
    { key: '/script', icon: <FormOutlined />, label: '创作剧本' },
    { key: '/', icon: <VideoCameraOutlined />, label: '视频生成工作流' },
    { key: '/models', icon: <AppstoreOutlined />, label: '模型管理' },
    { key: '/prompts', icon: <FileTextOutlined />, label: '提示词管理' },
  ]

  return (
    <Layout className={styles.layout}>
      <Header className={styles.header}>
        <h1 className={styles.title}>AI视频创作智能体</h1>
        <Menu
          theme="dark"
          mode="horizontal"
          selectedKeys={[location.pathname]}
          items={navItems}
          onClick={({ key }) => navigate(key)}
          style={{ marginLeft: 48, background: 'transparent', borderBottom: 'none', minWidth: 480 }}
        />
      </Header>
      <Layout>
        {isWorkflowPage && (
          <Sider width={280} theme="light" className={styles.sider}>
            <SessionSider
              sessions={videoSessions}
              loading={loadingVideoSessions}
              currentSessionId={currentSession?.session_id}
              totalSteps={4}
              creating={creatingVideoSession}
              onCreate={handleCreateVideoSession}
              onSelect={navigateWithSession}
              onDelete={handleDeleteVideoSession}
              onRefresh={loadVideoSessions}
            />
          </Sider>
        )}
        {isScriptPage && (
          <Sider width={280} theme="light" className={styles.sider}>
            <SessionSider
              sessions={scriptSessions}
              loading={loadingScriptSessions}
              currentSessionId={currentScriptSession?.session_id}
              totalSteps={4}
              creating={creatingScriptSession}
              onCreate={handleCreateScriptSession}
              onSelect={navigateWithSession}
              onDelete={handleDeleteScriptSession}
              onRefresh={loadScriptSessions}
            />
          </Sider>
        )}
        <Content className={styles.content}>{children}</Content>
      </Layout>
      <Footer className={styles.footer}>
        AI视频创作智能体 ©2026 - 创作剧本（构思 → 大纲 → 分集 → 定妆照） + 视频工作流（选集 → 分镜大纲 → 分镜管理 → 视频）
      </Footer>
    </Layout>
  )
}
