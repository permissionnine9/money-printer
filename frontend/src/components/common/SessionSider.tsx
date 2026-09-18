/**
 * 会话 Sider 公共组件（视频 / 与 /script 各自渲染，数据源由 props 注入）
 * 平铺模式（剧本页）/ 分组模式（视频页，grouped=true 按引用剧本二级分组）
 */
import React, { useEffect, useMemo, useState } from 'react'
import { Button, Empty, Popconfirm, Spin, Tag, Tooltip, Typography } from 'antd'
import { CaretRightOutlined, DeleteOutlined, PlusOutlined, ReloadOutlined } from '@ant-design/icons'
import type { Session } from '@/types'
import styles from '@/components/layout/MainLayout.module.css'

const { Text } = Typography

// 无引用剧本的会话归入的哨兵组（「未选择剧本分集」）
const UNGROUPED_KEY = '__ungrouped__'

const statusColor = (status: string) => {
  if (status === 'completed') return 'success'
  if (status === 'error') return 'error'
  return 'processing'
}

export interface SessionGroupMeta {
  key: string  // 分组唯一 key（视频页 = 剧本会话ID）
  title: string // 组头标题（剧本名）
}

export interface SessionSiderProps {
  /** title 为展示名（剧本名 / 集名），缺省回退 session_id 前 8 位；grouped 时 group 声明归属组；
   *  order 为组内排序键（降序，如集数），缺省的排在有值之后（保持插入序） */
  sessions: Array<
    Pick<Session, 'session_id' | 'status' | 'completed_steps' | 'updated_at'> & {
      title?: string
      group?: SessionGroupMeta
      order?: number
    }
  >
  /** true = 二级分组渲染；缺省平铺 */
  grouped?: boolean
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
  grouped,
  loading,
  currentSessionId,
  totalSteps,
  onCreate,
  creating,
  onSelect,
  onDelete,
  onRefresh,
}) => {
  // 折叠状态：默认全收起，当前选中会话所在组自动展开
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())

  // 按 sessions 顺序（后端已按 updated_at DESC）派生分组，插入序即组序
  const groups = useMemo(() => {
    if (!grouped) return []
    const map = new Map<string, { key: string; title: string; scriptId?: string; items: typeof sessions }>()
    for (const s of sessions) {
      const g = s.group
      const key = g?.key || UNGROUPED_KEY
      if (!map.has(key)) {
        map.set(key, {
          key,
          title: key === UNGROUPED_KEY ? '未选择剧本分集' : g!.title,
          scriptId: key === UNGROUPED_KEY ? undefined : key,
          items: [],
        })
      }
      map.get(key)!.items.push(s)
    }
    // 组内按 order 降序（无 order 的排在最后，同值保持插入序）
    for (const g of map.values()) {
      g.items.sort((a, b) => (b.order ?? -Infinity) - (a.order ?? -Infinity))
    }
    return Array.from(map.values())
  }, [grouped, sessions])

  // 当前选中会话所在组的 key（无选中 / 不在列表 / 非分组模式为 null）
  const activeGroupKey = useMemo(() => {
    if (!grouped || !currentSessionId) return null
    const cur = sessions.find((s) => s.session_id === currentSessionId)
    if (!cur) return null
    return cur.group?.key || UNGROUPED_KEY
  }, [grouped, currentSessionId, sessions])

  // 自动展开：仅在 activeGroupKey 值翻转时触发一次（依赖字符串值而非 sessions 引用，
  // 用户手动收起当前组 / 刷新列表重拉数据都不会被弹开）
  useEffect(() => {
    if (!activeGroupKey) return
    setExpandedKeys((prev) => (prev.has(activeGroupKey) ? prev : new Set(prev).add(activeGroupKey)))
  }, [activeGroupKey])

  const toggleGroup = (key: string) => {
    setExpandedKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // 单个会话项（平铺与分组二级复用；indented 表达层级缩进）
  const renderItem = (s: SessionSiderProps['sessions'][number], indented = false) => {
    const isActive = currentSessionId === s.session_id
    return (
      <div
        key={s.session_id}
        className={`${styles.sessionItem} ${isActive ? styles.sessionItemActive : ''}`}
        onClick={() => onSelect(s.session_id)}
        style={{ cursor: 'pointer', padding: '10px 12px', paddingLeft: indented ? 24 : 12 }}
      >
        <div style={{ width: '100%', minWidth: 0 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text strong={isActive} ellipsis style={{ fontSize: 12 }} title={s.title || s.session_id}>
              {s.title || s.session_id.slice(0, 8)}
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
            <Text type="secondary" style={{ fontSize: 11 }} title={s.session_id}>
              {s.session_id.slice(0, 8)}
            </Text>
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
  }

  return (
    <>
      <div style={{ padding: '16px 12px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Text strong>会话管理</Text>
        <div style={{ display: 'flex', gap: 4 }}>
          <Tooltip title="刷新列表">
            <Button size="small" icon={<ReloadOutlined />} onClick={onRefresh} loading={loading} />
          </Tooltip>
          <Tooltip title="新建会话">
            <Button size="small" type="primary" icon={<PlusOutlined />} loading={creating} onClick={onCreate} />
          </Tooltip>
        </div>
      </div>
      <div className={styles.sessionList}>
        {sessions.length === 0 && !loading ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无会话" style={{ marginTop: 48 }} />
        ) : (
          <Spin spinning={loading}>
            {grouped
              ? groups.map((g) => {
                  const expanded = expandedKeys.has(g.key)
                  return (
                    <div key={g.key}>
                      <div className={styles.sessionGroupHeader} onClick={() => toggleGroup(g.key)}>
                        <CaretRightOutlined
                          style={{
                            fontSize: 10,
                            color: '#999',
                            flexShrink: 0,
                            transform: expanded ? 'rotate(90deg)' : 'none',
                            transition: 'transform 0.2s',
                          }}
                        />
                        <Text strong ellipsis style={{ fontSize: 12, flex: 1, minWidth: 0 }} title={g.title}>
                          {g.title}
                        </Text>
                        {g.scriptId && (
                          <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }} title={g.scriptId}>
                            {g.scriptId.slice(0, 8)}
                          </Text>
                        )}
                        <Text type="secondary" style={{ fontSize: 11, flexShrink: 0 }}>
                          ({g.items.length})
                        </Text>
                      </div>
                      {expanded && g.items.map((s) => renderItem(s, true))}
                    </div>
                  )
                })
              : sessions.map((s) => renderItem(s))}
          </Spin>
        )}
      </div>
    </>
  )
}
