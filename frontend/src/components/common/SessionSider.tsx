/**
 * 会话 Sider 公共组件（视频 / 与 /script 各自渲染，数据源由 props 注入）
 */
import React from 'react'
import { Button, Empty, Popconfirm, Spin, Tag, Tooltip, Typography } from 'antd'
import { DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Session } from '@/types'
import styles from '@/components/layout/MainLayout.module.css'

const { Text } = Typography

const statusColor = (status: string) => {
  if (status === 'completed') return 'success'
  if (status === 'error') return 'error'
  return 'processing'
}

export interface SessionSiderProps {
  sessions: Array<Pick<Session, 'session_id' | 'status' | 'completed_steps' | 'updated_at'>>
  loading: boolean
  currentSessionId?: string
  totalSteps: number
  /** 新建会话（返回 session_id，由调用方决定跳转方式） */
  onCreate: () => void
  creating?: boolean
  /** 点击会话项 */
  onSelect: (sessionId: string) => void
  /** 删除会话 */
  onDelete: (sessionId: string) => void
  onRefresh: () => void
}

export const SessionSider: React.FC<SessionSiderProps> = ({
  sessions,
  loading,
  currentSessionId,
  totalSteps,
  onCreate,
  creating,
  onSelect,
  onDelete,
  onRefresh,
}) => {
  return (
    <>
      <div style={{ padding: '16px 12px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text strong>会话管理</Text>
        <Tooltip title="新建会话">
          <Button size="small" type="primary" icon={<PlusOutlined />} loading={creating} onClick={onCreate} />
        </Tooltip>
      </div>
      <div style={{ padding: '0 12px 8px' }}>
        <Button size="small" block icon={<ReloadOutlined />} onClick={onRefresh} loading={loading}>
          刷新列表
        </Button>
      </div>
      <div className={styles.sessionList}>
        {sessions.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" style={{ marginTop: 48 }} />
        ) : (
          <Spin spinning={loading}>
            {sessions.map((s) => {
              const isActive = currentSessionId === s.session_id
              return (
                <div
                  key={s.session_id}
                  className={`${styles.sessionItem} ${isActive ? styles.sessionItemActive : ''}`}
                  onClick={() => onSelect(s.session_id)}
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
                          onDelete(s.session_id)
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
                        {(s.completed_steps?.length || 0)}/{totalSteps} 步
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
    </>
  )
}
