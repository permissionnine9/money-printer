/**
 * 步骤 2（索引1）：分镜大纲
 * 以剧本分集设计为上下文生成本集分镜导图（markmap）+ 分镜列表；
 * 预览/编辑双模式与重新生成（重生成会级联清空分镜配置、提示词与视频数据）
 */
import React, { useState } from 'react'
import { Button, Card, Input, Modal, Segmented, Space, Spin, Tag, Typography, message } from 'antd'
import {
  CheckCircleOutlined,
  EditFilled,
  EditOutlined,
  ExclamationCircleOutlined,
  EyeOutlined,
  RedoOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { AgentEvent, SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { MindmapView } from '@/components/common'
import { AgentRunProgress } from '@/components/script/AgentRunProgress'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography
const { TextArea } = Input

interface StepStoryboardOutlineProps {
  session: SessionDetail
}

export const StepStoryboardOutline: React.FC<StepStoryboardOutlineProps> = ({ session }) => {
  const { refreshSession } = useSessionStore()
  const outlineData = session.step_results?.storyboard_outline?.result_data
  const mindmap: string = outlineData?.mindmap || ''
  const segmentCount: number = outlineData?.segment_count || 0
  const canExecute = session.completed_steps?.includes('select_episode')
  const isCompleted = session.completed_steps?.includes('storyboard_outline')
  const hasDownstream = session.completed_steps?.some(
    (s) => s === 'segment_management' || s === 'generate_videos'
  )

  const [extraPrompt, setExtraPrompt] = useState('')
  const [viewMode, setViewMode] = useState<'preview' | 'edit'>('preview')
  const [editingMarkdown, setEditingMarkdown] = useState('')
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [run, setRun] = useState<{ id: string; active: boolean } | null>(null)

  // 发起生成（POST storyboard-outline/generate → run_id → 观流）
  const executeGenerate = async () => {
    setStarting(true)
    try {
      const runId = await stepApi.generateStoryboardOutline(session.session_id, extraPrompt || undefined)
      setRun({ id: runId, active: true })
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  const handleRegenerate = () => {
    Modal.confirm({
      title: '确认重新生成分镜大纲？',
      icon: <ExclamationCircleOutlined />,
      content: '重新生成将清空分镜配置、已生成的分镜提示词与视频数据，此操作不可撤销。是否继续？',
      onOk: () => {
        setExtraPrompt('')
        void executeGenerate()
      },
    })
  }

  const handleRunDone = async (ev: AgentEvent) => {
    setRun((r) => (r ? { ...r, active: false } : r))
    if (ev.success) {
      message.success('分镜大纲生成完成')
      setViewMode('preview')
      await refreshSession()
    } else {
      message.error(ev.error || '分镜大纲生成失败')
    }
  }

  const saveEdit = async () => {
    if (!editingMarkdown.trim()) {
      message.warning('大纲内容不能为空')
      return
    }
    setSaving(true)
    try {
      await stepApi.updateStoryboardOutline(session.session_id, editingMarkdown)
      message.success('分镜大纲已保存')
      setViewMode('preview')
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!canExecute) {
    return (
      <Card title="分镜大纲" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 1 步：从剧本选集</Text>
      </Card>
    )
  }

  return (
    <Card
      title={
        <span>
          {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
          分镜大纲
          {outlineData?.edited && (
            <Tag color="blue" style={{ marginLeft: 12 }}>
              已人工修改
            </Tag>
          )}
          {segmentCount > 0 && (
            <Tag style={{ marginLeft: 8 }}>{segmentCount} 个分镜</Tag>
          )}
        </span>
      }
      style={{ marginTop: 16 }}
      extra={
        mindmap ? (
          <Space>
            <Segmented
              value={viewMode}
              onChange={(v) => {
                const mode = v as 'preview' | 'edit'
                if (mode === 'edit') setEditingMarkdown(mindmap)
                setViewMode(mode)
              }}
              options={[
                { value: 'preview', icon: <EyeOutlined />, label: '导图预览' },
                { value: 'edit', icon: <EditFilled />, label: '编辑' },
              ]}
            />
            <Button icon={<RedoOutlined />} disabled={run?.active} onClick={handleRegenerate}>
              重新生成
            </Button>
          </Space>
        ) : undefined
      }
    >
      {!mindmap && (
        <Text type="secondary">
          基于第 1 步选定的剧本分集生成本集分镜大纲（思维导图 + 分镜列表），生成后可人工编辑导图；
          下一步「分镜管理」将基于导图中产出的分镜列表进行配置。
        </Text>
      )}

      {run && (
        <div style={{ marginTop: 16 }}>
          <AgentRunProgress runId={run.id} onDone={handleRunDone} />
        </div>
      )}

      {!mindmap && !run && (
        <div style={{ marginTop: 16, maxWidth: 640 }}>
          <div style={{ marginBottom: 4 }}>
            <Text type="secondary">补充要求（可选）</Text>
          </div>
          <TextArea
            rows={3}
            value={extraPrompt}
            onChange={(e) => setExtraPrompt(e.target.value)}
            placeholder="例如：节奏更紧凑；开场用空镜；把高潮拆成 3 个分镜"
          />
          <div style={{ marginTop: 16 }}>
            <Spin spinning={starting}>
              <Button
                type="primary"
                size="large"
                icon={<ThunderboltOutlined />}
                loading={starting}
                onClick={() => executeGenerate()}
              >
                生成分镜大纲
              </Button>
            </Spin>
          </div>
        </div>
      )}

      {mindmap && viewMode === 'preview' && (
        <div style={{ marginTop: 16 }}>
          <MindmapView markdown={mindmap} height={520} />
        </div>
      )}

      {mindmap && viewMode === 'edit' && (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">
              直接编辑 markdown 层级文本（# 标题层级 / - 列表项）；保存仅更新导图，不改动分镜列表
            </Text>
            <Space>
              <Button onClick={() => setViewMode('preview')}>取消</Button>
              <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveEdit}>
                保存修改
              </Button>
            </Space>
          </div>
          <TextArea
            value={editingMarkdown}
            onChange={(e) => setEditingMarkdown(e.target.value)}
            rows={20}
            style={{ fontFamily: 'monospace' }}
          />
        </div>
      )}

      {mindmap && hasDownstream && (
        <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
          <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
          <span style={{ color: '#ad6800' }}>
            下游已有分镜配置 / 视频数据，重新生成大纲将清空这些数据；仅保存编辑不会清空
          </span>
        </div>
      )}

      {!mindmap && run?.active === false && (
        <div style={{ marginTop: 16 }}>
          <Button icon={<EditOutlined />} onClick={() => executeGenerate()}>
            重试生成
          </Button>
        </div>
      )}
    </Card>
  )
}

export default StepStoryboardOutline
