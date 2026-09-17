/**
 * 主布局组件：顶部导航 + 左侧会话管理（仅工作流页）+ 内容区
 */
import React, { useEffect, useState } from 'react'
import { Layout, Menu, Button, Tag, Popconfirm, Tooltip, Typography, Empty, Spin } from 'antd'
import {
  PlusOutlined,
  ReloadOutlined,
  DeleteOutlined,
  VideoCameraOutlined,
  AppstoreOutlined,
  FileTextOutlined,
} from '@ant-design/icons'
import { useLocation, useNavigate } from 'react-router-dom'
import type { Session } from '@/types'
import { sessionApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import styles from './MainLayout.module.css'

const { Header, Sider, Content, Footer } = Layout
const { Text } = Typography

interface MainLayoutProps {
  children: React.ReactNode
}

// 会话状态标签颜色映射
const statusColor = (status: string) => {
  if (status === 'completed') return 'success'
  if (status === 'error') return 'error'
  return 'processing'
}

export const MainLayout: React.FC<MainLayoutProps> = ({ children }) => {
  const location = useLocation()
  const navigate = useNavigate()
  const isWorkflowPage = location.pathname === '/'
  const [sessions, setSessions] = useState<Session[]>([])
  const [loadingSessions, setLoadingSessions] = useState(false)
  const currentSession = useSessionStore((state) => state.currentSession)

  // 加载会话列表
  const loadSessions = async () => {
    setLoadingSessions(true)
    try {
      const result = await sessionApi.list()
      setSessions(result.sessions || [])
    } catch {
      // 静默失败，侧边栏显示空态
    } finally {
      setLoadingSessions(false)
    }
  }

  useEffect(() => {
    if (isWorkflowPage) {
      loadSessions()
    }
  }, [isWorkflowPage, currentSession?.session_id])

  // 点击会话：地址栏带上 session_id 并刷新网页
  const handleSelectSession = (sessionId: string) => {
    const url = new URL(window.location.href)
    url.searchParams.set('session_id', sessionId)
    window.location.href = url.toString()
  }

  // 新建会话：创建后地址栏带 session_id 并整页刷新
  const handleCreateSession = async () => {
    const session = await sessionApi.create()
    const url = new URL(window.location.href)
    url.searchParams.set('session_id', session.session_id)
    window.location.href = url.toString()
  }

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await sessionApi.delete(sessionId)
      if (currentSession?.session_id === sessionId) {
        const url = new URL(window.location.href)
        url.searchParams.delete('session_id')
        window.location.href = url.toString()
        return
      }
      await loadSessions()
    } catch {
      // ignore
    }
  }

  const navItems = [
    { key: '/', icon: <VideoCameraOutlined />, label: '创作工作流' },
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
          style={{ marginLeft: 48, background: 'transparent', borderBottom: 'none', minWidth: 360 }}
        />
      </Header>
      <Layout>
        {isWorkflowPage && (
          <Sider width={280} theme="light" className={styles.sider}>
            <div style={{ padding: '16px 12px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text strong>会话管理</Text>
              <Tooltip title="新建会话">
                <Button size="small" type="primary" icon={<PlusOutlined />} onClick={handleCreateSession} />
              </Tooltip>
            </div>
            <div style={{ padding: '0 12px 8px' }}>
              <Button
                size="small"
                block
                icon={<ReloadOutlined />}
                onClick={loadSessions}
                loading={loadingSessions}
              >
                刷新列表
              </Button>
            </div>
            <div className={styles.sessionList}>
              {sessions.length === 0 && !loadingSessions ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" style={{ marginTop: 48 }} />
              ) : (
                <Spin spinning={loadingSessions}>
                  {sessions.map((s) => {
                    const isActive = currentSession?.session_id === s.session_id
                    return (
                      <div
                        key={s.session_id}
                        className={`${styles.sessionItem} ${isActive ? styles.sessionItemActive : ''}`}
                        onClick={() => handleSelectSession(s.session_id)}
                        style={{ cursor: 'pointer', padding: '10px 12px' }}
                      >
                        <div style={{ width: '100%', minWidth: 0 }}>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                            <Text strong={isActive} ellipsis style={{ fontSize: 12 }}>
                              {s.session_id.slice(0, 8)}
                            </Text>
                            <Popconfirm
                              title="确定删除此会话？"
                              onConfirm={(e) => {
                                e?.stopPropagation()
                                handleDeleteSession(s.session_id)
                              }}
                              onCancel={(e) => e?.stopPropagation()}
                              okText="删除"
                              cancelText="取消"
                            >
                              <Button
                                type="text"
                                danger
                                size="small"
                                icon={<DeleteOutlined />}
                                onClick={(e) => e.stopPropagation()}
                              />
                            </Popconfirm>
                          </div>
                          <div style={{ display: 'flex', gap: 4, marginTop: 4, alignItems: 'center' }}>
                            <Tag color={statusColor(s.status)} style={{ marginRight: 0, fontSize: 11 }}>
                              {s.status === 'completed' ? '已完成' : s.status === 'error' ? '异常' : '进行中'}
                            </Tag>
                            <Text type="secondary" style={{ fontSize: 11 }}>
                              {(s.completed_steps?.length || 0)}/7 步
                            </Text>
                            <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }}>
                              {new Date(s.updated_at).toLocaleDateString()}
                            </Text>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </Spin>
              )}
            </div>
          </Sider>
        )}
        <Content className={styles.content}>{children}</Content>
      </Layout>
      <Footer className={styles.footer}>
        AI视频创作智能体 ©2026 - 7步工作流：脚本 → 优化 → 思维导图 → 素材图 → 分片 → 首尾帧 → ComfyUI 视频
      </Footer>
    </Layout>
  )
}
