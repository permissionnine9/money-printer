/**
 * 主布局组件：顶部导航 + 左侧会话管理（视频 / 剧本两页各自渲染）+ 内容区
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Layout, Menu, Button, Dropdown, Tooltip } from 'antd'
import {
  VideoCameraOutlined,
  AppstoreOutlined,
  FileTextOutlined,
  FormOutlined,
  CloudServerOutlined,
  PictureOutlined,
  SettingOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import { SessionSider } from '@/components/common/SessionSider'
import { ComfyUIConnectionModal } from '@/components/settings/ComfyUIConnectionModal'
import { AgentRunDock } from './AgentRunDock'
import type { Session, ScriptSessionDetail } from '@/types'
import { sessionApi, scriptSessionApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import styles from './MainLayout.module.css'

const { Header, Sider, Content, Footer } = Layout

interface MainLayoutProps {
  children: React.ReactNode
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const isWorkflowPage = location.pathname === '/'
  const isScriptPage = location.pathname === '/script'

  // 视频会话
  const currentSession = useSessionStore((state) => state.currentSession)
  const loadVideoSession = useSessionStore((state) => state.loadSession)
  const setVideoCurrentSession = useSessionStore((state) => state.setCurrentSession)
  const [videoSessions, setVideoSessions] = useState<Session[]>([])
  const [loadingVideoSessions, setLoadingVideoSessions] = useState(false)
  const [creatingVideoSession, setCreatingVideoSession] = useState(false)

  // 剧本会话
  const currentScriptSession = useScriptSessionStore((state) => state.currentSession)
  const loadScriptSession = useScriptSessionStore((state) => state.loadSession)
  const setScriptCurrentSession = useScriptSessionStore((state) => state.setCurrentSession)
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
      await loadVideoSession(session.session_id)
    } catch {
      // ignore
    } finally {
      setCreatingVideoSession(false)
    }
  }

  // SPA 内切换会话：写 store 即可，页面会随 currentSession 重渲染并同步 URL
  const handleSelectSession = (sessionId: string, loadSession: (id: string) => Promise<unknown>, currentId?: string) => {
    if (sessionId === currentId) return
    loadSession(sessionId)
  }

  const handleDeleteVideoSession = async (sessionId: string) => {
    try {
      await sessionApi.delete(sessionId)
      if (currentSession?.session_id === sessionId) {
        // 清空当前会话并清掉 URL 中的 session_id（页面显示欢迎引导）
        setVideoCurrentSession(null)
        navigate(location.pathname, { replace: true })
        // 列表刷新由 currentSession 变化触发的 effect 完成
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
      await loadScriptSession(session.session_id)
    } catch {
      // ignore
    } finally {
      setCreatingScriptSession(false)
    }
  }

  const handleDeleteScriptSession = async (sessionId: string) => {
    try {
      await scriptSessionApi.delete(sessionId)
      if (currentScriptSession?.session_id === sessionId) {
        setScriptCurrentSession(null)
        navigate(location.pathname, { replace: true })
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
  ]

  // 右上角设置下拉：管理类页面入口 + Agent 并发配置
  const settingMenuItems = [
    { key: '/prompts', icon: <FileTextOutlined />, label: '提示词管理' },
    { key: '/models', icon: <AppstoreOutlined />, label: '模型管理' },
    { key: '/materials', icon: <PictureOutlined />, label: '素材管理' },
    { type: 'divider' as const },
    { key: '/settings/agent-concurrency', icon: <ThunderboltOutlined />, label: 'Agent 并发配置' },
  ]

  // ComfyUI 服务器连接设置（GPU 容器重启后 SSH 凭据变化时手动录入）
  const [connectionModalOpen, setConnectionModalOpen] = useState(false)

  // 侧边栏展示名：剧本页 = 剧本名平铺；视频页 = 按引用剧本二级分组（组头剧本名，二级「第N集·集名」按集数降序）
  const scriptSessionItems = scriptSessions.map((s) => ({
    ...s,
    title: s.title?.trim() || '未命名剧本',
  }))
  const videoSessionItems = videoSessions.map((s) => ({
    ...s,
    title: s.episode_number
      ? `第${s.episode_number}集·${s.episode_title?.trim() || ''}`
      : s.episode_title?.trim() || '',
    order: s.episode_number,
    group: s.script_session_id
      ? { key: s.script_session_id, title: s.script_title?.trim() || '未命名剧本' }
      : undefined,
  }))

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
          style={{ marginLeft: 48, background: 'transparent', borderBottom: 'none', minWidth: 320, flex: 1 }}
        />
        <Tooltip title="ComfyUI 服务器连接（容器重启后更新 SSH 信息）">
          <Button
            type="text"
            style={{ marginRight: 8 }}
            icon={<CloudServerOutlined style={{ color: '#fff', fontSize: 18 }} />}
            onClick={() => setConnectionModalOpen(true)}
          />
        </Tooltip>
        <Dropdown
          placement="bottomRight"
          menu={{
            items: settingMenuItems,
            onClick: ({ key }) => navigate(key),
          }}
        >
          <Button type="text" icon={<SettingOutlined style={{ color: '#fff', fontSize: 18 }} />} />
        </Dropdown>
        <ComfyUIConnectionModal open={connectionModalOpen} onClose={() => setConnectionModalOpen(false)} />
      </Header>
      <Layout>
        {isWorkflowPage && (
          <Sider width={280} theme="light" className={styles.sider}>
            <SessionSider
              sessions={videoSessionItems}
              grouped
              loading={loadingVideoSessions}
              currentSessionId={currentSession?.session_id}
              totalSteps={4}
              creating={creatingVideoSession}
              onCreate={handleCreateVideoSession}
              onSelect={(id) => handleSelectSession(id, loadVideoSession, currentSession?.session_id)}
              onDelete={handleDeleteVideoSession}
              onRefresh={loadVideoSessions}
            />
          </Sider>
        )}
        {isScriptPage && (
          <Sider width={280} theme="light" className={styles.sider}>
            <SessionSider
              sessions={scriptSessionItems}
              loading={loadingScriptSessions}
              currentSessionId={currentScriptSession?.session_id}
              totalSteps={4}
              creating={creatingScriptSession}
              onCreate={handleCreateScriptSession}
              onSelect={(id) => handleSelectSession(id, loadScriptSession, currentScriptSession?.session_id)}
              onDelete={handleDeleteScriptSession}
              onRefresh={loadScriptSessions}
            />
          </Sider>
        )}
        <Content className={styles.content}>{children}</Content>
      </Layout>
      <AgentRunDock />
      <Footer className={styles.footer}>
        AI视频创作智能体 ©2026 - 创作剧本（构思 → 大纲 → 分集 → 核心素材） + 视频工作流（选集 → 分镜大纲 → 分镜管理 → 视频）
      </Footer>
    </Layout>
  )
}
