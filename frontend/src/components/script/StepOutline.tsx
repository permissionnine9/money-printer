/**
 * 第 2 步：故事大纲（参数化生成思维导图 → run 观流；预览/编辑双模式与重新生成）
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Input, InputNumber, Modal, Segmented, Space, Spin, Tag, Typography, message } from 'antd'
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
import type { AgentEvent, ScriptSessionDetail } from '@/types'
import client, { scriptStepApi } from '@/api/client'
import { MindmapView } from '@/components/common'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import { AgentRunProgress } from './AgentRunProgress'

const { Text } = Typography
const { TextArea } = Input

interface StepOutlineProps {
  session: ScriptSessionDetail
}

export const StepOutline: React.FC<StepOutlineProps> = ({ session }) => {
  const { refreshSession } = useScriptSessionStore()
  const outlineData = session.step_results?.story_outline?.result_data
  const mindmap: string = outlineData?.mindmap || ''
  const canExecute = session.completed_steps?.includes('story_ideation')
  const isCompleted = session.completed_steps?.includes('story_outline')
  const hasDownstream = session.completed_steps?.some(
    (s) => s === 'episode_design' || s === 'lookbook_images'
  )

  const [episodeCount, setEpisodeCount] = useState<number>(outlineData?.requirements?.episode_count || 0)
  const [totalWordCount, setTotalWordCount] = useState<number>(outlineData?.requirements?.total_word_count || 0)
  const [sceneCount, setSceneCount] = useState<number>(outlineData?.requirements?.scene_count || 0)
  const [extraPrompt, setExtraPrompt] = useState('')
  const [viewMode, setViewMode] = useState<'preview' | 'edit'>('preview')
  const [editingMarkdown, setEditingMarkdown] = useState('')
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [run, setRun] = useState<{ id: string; active: boolean } | null>(null)
  const [promptModal, setPromptModal] = useState<{ open: boolean; extraPrompt: string }>({
    open: false,
    extraPrompt: '',
  })

  // 会话切换时还原生成参数
  useEffect(() => {
    const req = session.step_results?.story_outline?.result_data?.requirements || {}
    setEpisodeCount(req.episode_count || 0)
    setTotalWordCount(req.total_word_count || 0)
    setSceneCount(req.scene_count || 0)
    setViewMode('preview')
    setRun(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.session_id])

  // 发起生成（POST outline/generate → run_id → 观流）
  const executeGenerate = async (regenExtraPrompt: string) => {
    setStarting(true)
    setPromptModal({ open: false, extraPrompt: '' })
    try {
      const { data } = await client.post(`/script-sessions/${session.session_id}/outline/generate`, {
        episode_count: episodeCount || 0,
        total_word_count: totalWordCount || 0,
        scene_count: sceneCount || 0,
        extra_prompt: regenExtraPrompt || extraPrompt || '',
      })
      const runId = data?.data?.run_id
      if (!runId) throw new Error('未获取到 run_id')
      setRun({ id: runId, active: true })
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  const handleModalOk = () => {
    Modal.confirm({
      title: '确认重新生成大纲？',
      icon: <ExclamationCircleOutlined />,
      content: '重新生成将清空下游已生成的分集设计、实体库与核心素材，此操作不可撤销。是否继续？',
      onOk: () => executeGenerate(promptModal.extraPrompt),
    })
  }

  const handleRunDone = async (ev: AgentEvent) => {
    setRun((r) => (r ? { ...r, active: false } : r))
    if (ev.success) {
      message.success('大纲生成完成')
      setViewMode('preview')
      await refreshSession()
    } else {
      message.error(ev.error || '大纲生成失败')
    }
  }

  const saveEdit = async () => {
    if (!editingMarkdown.trim()) {
      message.warning('大纲内容不能为空')
      return
    }
    setSaving(true)
    try {
      await scriptStepApi.updateOutline(session.session_id, editingMarkdown)
      message.success('大纲已保存')
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
      <Card title="故事大纲" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 1 步：故事构思</Text>
      </Card>
    )
  }

  const promptModalNode = (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          重新生成大纲 - 补充要求
        </span>
      }
      open={promptModal.open}
      onOk={handleModalOk}
      onCancel={() => setPromptModal({ open: false, extraPrompt: '' })}
      okText="开始重新生成"
      cancelText="取消"
      width={600}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">重新生成将级联清空下游分集 / 实体 / 核心素材；可输入补充要求（可选，留空使用当前参数）。</Text>
      </div>
      <TextArea
        rows={4}
        value={promptModal.extraPrompt}
        onChange={(e) => setPromptModal((m) => ({ ...m, extraPrompt: e.target.value }))}
        placeholder="例如：节奏更紧凑、每集结尾留悬念"
      />
    </Modal>
  )

  return (
    <>
      <Card
        title={
          <span>
            {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
            故事大纲
            {outlineData?.edited && (
              <Tag color="blue" style={{ marginLeft: 12 }}>
                已人工修改
              </Tag>
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
              <Button
                icon={<RedoOutlined />}
                disabled={run?.active}
                onClick={() => setPromptModal({ open: true, extraPrompt: '' })}
              >
                重新生成
              </Button>
            </Space>
          ) : undefined
        }
      >
        {!mindmap && (
          <Text type="secondary">
            基于第 1 步的故事逻辑生成 markdown 层级大纲（思维导图），生成后可人工编辑；后续分集设计将基于该大纲。
          </Text>
        )}

        {run && (
          <div style={{ marginTop: 16 }}>
            <AgentRunProgress runId={run.id} onDone={handleRunDone} />
          </div>
        )}

        {!mindmap && !run && (
          <div style={{ marginTop: 16 }}>
            <Space wrap size={24}>
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary">集数（0=自动）</Text>
                </div>
                <InputNumber
                  min={0}
                  precision={0}
                  value={episodeCount}
                  onChange={(v) => setEpisodeCount(v ?? 0)}
                  style={{ width: 140 }}
                />
              </div>
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary">总字数目标（0=不限）</Text>
                </div>
                <InputNumber
                  min={0}
                  precision={0}
                  value={totalWordCount}
                  onChange={(v) => setTotalWordCount(v ?? 0)}
                  style={{ width: 140 }}
                  formatter={(v) => (v ? `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : `${v}`)}
                />
              </div>
              <div>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary">主要场景数（0=自动）</Text>
                </div>
                <InputNumber
                  min={0}
                  precision={0}
                  value={sceneCount}
                  onChange={(v) => setSceneCount(v ?? 0)}
                  style={{ width: 140 }}
                />
              </div>
            </Space>
            <div style={{ marginTop: 16, maxWidth: 640 }}>
              <div style={{ marginBottom: 4 }}>
                <Text type="secondary">补充要求（可选）</Text>
              </div>
              <TextArea
                rows={3}
                value={extraPrompt}
                onChange={(e) => setExtraPrompt(e.target.value)}
                placeholder="例如：三幕式结构；主线一条副线一条；每集结尾留钩子"
              />
            </div>
            <div style={{ marginTop: 16 }}>
              <Spin spinning={starting}>
                <Button
                  type="primary"
                  size="large"
                  icon={<ThunderboltOutlined />}
                  loading={starting}
                  onClick={() => executeGenerate('')}
                >
                  生成大纲
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
                直接编辑 markdown 层级文本（# 标题层级 / - 列表项），保存后分集设计将使用新大纲
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
              下游已生成分集 / 核心素材数据，重新生成大纲将清空这些数据；仅保存编辑不会清空
            </span>
          </div>
        )}
      </Card>
      {promptModalNode}
    </>
  )
}

export default StepOutline
