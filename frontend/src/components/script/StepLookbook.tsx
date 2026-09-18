/**
 * 第 4 步：剧本定妆照（勾选实体 → agent 出 prompt + 生图 → 网格管理与单张重生成）
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Button, Card, Checkbox, Empty, Image, Input, Popconfirm, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, DeleteOutlined, RedoOutlined, ThunderboltOutlined } from '@ant-design/icons'
import type { AgentEvent, ImageModelConfig, LookbookImage, ScriptEntity, ScriptSessionDetail } from '@/types'
import { entityApi, modelApi, scriptStepApi } from '@/api/client'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import { usePolling } from '@/hooks/usePolling'
import { AgentRunProgress } from './AgentRunProgress'

const { Text } = Typography
const { TextArea } = Input

interface StepLookbookProps {
  session: ScriptSessionDetail
}

// 图片路径 → 可访问 src（后端相对路径补 / 前缀）
const imageSrc = (path?: string): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  return `/${path}`
}

export const StepLookbook: React.FC<StepLookbookProps> = ({ session }) => {
  const { refreshSession } = useScriptSessionStore()
  const canExecute = session.completed_steps?.includes('episode_design')
  const isCompleted = session.completed_steps?.includes('lookbook_images')

  const [entities, setEntities] = useState<ScriptEntity[]>([])
  const [images, setImages] = useState<LookbookImage[]>([])
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [stylePrompt, setStylePrompt] = useState('')
  const [models, setModels] = useState<ImageModelConfig[]>([])
  const [modelConfigId, setModelConfigId] = useState<string | undefined>(undefined)
  const [run, setRun] = useState<{ id: string; active: boolean } | null>(null)
  const [starting, setStarting] = useState(false)
  const [completing, setCompleting] = useState(false)
  const [actionLoading, setActionLoading] = useState('')

  const loadEntities = useCallback(async () => {
    try {
      const list = await entityApi.list(session.session_id)
      setEntities(list || [])
    } catch {
      // 静默失败
    }
  }, [session.session_id])

  const loadImages = useCallback(async () => {
    try {
      const list = await scriptStepApi.listLookbook(session.session_id)
      setImages(list || [])
    } catch {
      // 静默失败
    }
  }, [session.session_id])

  useEffect(() => {
    void loadEntities()
    void loadImages()
    modelApi
      .list('image')
      .then((r) => setModels(r.models || []))
      .catch(() => setModels([]))
  }, [loadEntities, loadImages])

  // 生成中（run 活跃或有 pending/processing 图片）2s 轮询状态机
  const hasActiveImages = images.some(
    (i) => i.task_status === 'pending' || i.task_status === 'processing'
  )
  usePolling(
    () => {
      void loadImages()
      void loadEntities()
    },
    { interval: 2000, enabled: !!run?.active || hasActiveImages }
  )

  const toggleEntity = (id: string, checked: boolean) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (checked) next.add(id)
      else next.delete(id)
      return next
    })
  }

  const handleGenerate = async () => {
    const ids = Array.from(selectedIds)
    if (!ids.length) {
      message.warning('请至少勾选一个实体')
      return
    }
    setStarting(true)
    try {
      const runId = await scriptStepApi.generateLookbook(
        session.session_id,
        ids,
        stylePrompt,
        modelConfigId
      )
      setRun({ id: runId, active: true })
      message.success('定妆照生成任务已启动')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setStarting(false)
    }
  }

  const handleRunDone = async (ev: AgentEvent) => {
    setRun((r) => (r ? { ...r, active: false } : r))
    if (ev.success) {
      message.success('定妆照生成完成')
      await refreshSession()
    } else {
      message.error(ev.error || '定妆照生成失败')
    }
    await loadImages()
    await loadEntities()
  }

  const handleRegenerateImage = async (image: LookbookImage) => {
    setActionLoading(image.image_id)
    try {
      const runId = await scriptStepApi.regenerateLookbookImage(session.session_id, image.image_id)
      setRun({ id: runId, active: true })
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setActionLoading('')
    }
  }

  const handleDeleteImage = async (image: LookbookImage) => {
    setActionLoading(image.image_id)
    try {
      await scriptStepApi.deleteLookbookImage(session.session_id, image.image_id)
      message.success('定妆照已删除')
      await loadImages()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setActionLoading('')
    }
  }

  const handleComplete = async () => {
    setCompleting(true)
    try {
      await scriptStepApi.completeLookbook(session.session_id)
      message.success('第 4 步已完成')
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setCompleting(false)
    }
  }

  if (!canExecute) {
    return (
      <Card title="剧本定妆照" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 3 步：分集设计</Text>
      </Card>
    )
  }

  // ==================== 实体勾选卡片 ====================

  const characters = entities.filter((e) => e.entity_type === 'character')
  const scenes = entities.filter((e) => e.entity_type === 'scene')

  const entityCard = (e: ScriptEntity) => {
    const checked = selectedIds.has(e.entity_id)
    return (
      <div
        key={e.entity_id}
        onClick={() => toggleEntity(e.entity_id, !checked)}
        style={{
          width: 200,
          border: checked ? '2px solid #1677ff' : '1px solid #f0f0f0',
          borderRadius: 8,
          padding: 8,
          cursor: 'pointer',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, marginBottom: 6 }}>
          <Checkbox
            checked={checked}
            onClick={(ev) => ev.stopPropagation()}
            onChange={(ev) => toggleEntity(e.entity_id, ev.target.checked)}
          />
          <Text strong ellipsis style={{ maxWidth: 100 }}>
            {e.name}
          </Text>
          <Tag style={{ marginRight: 0, fontSize: 11 }}>{e.entity_id}</Tag>
        </div>
        {e.lookbook_image_path ? (
          <img
            src={imageSrc(e.lookbook_image_path)}
            alt={e.name}
            style={{ width: '100%', height: 120, objectFit: 'cover', borderRadius: 6 }}
          />
        ) : (
          <div
            style={{
              width: '100%',
              height: 120,
              background: '#fafafa',
              border: '1px dashed #e8e8e8',
              borderRadius: 6,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
          >
            <Text type="secondary" style={{ fontSize: 12 }}>
              暂无定妆照
            </Text>
          </div>
        )}
        <div style={{ fontSize: 12, color: '#888', marginTop: 6, maxHeight: 36, overflow: 'hidden' }}>
          {e.description}
        </div>
      </div>
    )
  }

  const entityGroup = (title: string, list: ScriptEntity[]) =>
    list.length ? (
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>{title}（{list.length}）</Text>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>{list.map(entityCard)}</div>
      </div>
    ) : null

  // ==================== 结果网格 ====================

  const imageCard = (img: LookbookImage) => {
    const entity = entities.find((e) => e.entity_id === img.entity_id)
    const status = img.task_status
    const busy = actionLoading === img.image_id || status === 'pending' || status === 'processing'
    return (
      <div key={img.image_id} style={{ width: 200, border: '1px solid #f0f0f0', borderRadius: 8, padding: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, marginBottom: 6 }}>
          <Text strong ellipsis style={{ maxWidth: 110 }}>
            {entity?.name || img.entity_id}
          </Text>
          {status === 'completed' ? (
            <Tag color="success" style={{ marginRight: 0 }}>已完成</Tag>
          ) : status === 'failed' ? (
            <Tag color="error" style={{ marginRight: 0 }}>失败</Tag>
          ) : (
            <Tag color="processing" style={{ marginRight: 0 }}>生成中</Tag>
          )}
        </div>
        <div
          style={{
            width: '100%',
            height: 160,
            borderRadius: 6,
            overflow: 'hidden',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#fafafa',
          }}
        >
          {status === 'completed' && img.image_path ? (
            <Image
              src={imageSrc(img.image_path)}
              alt={entity?.name || img.entity_id}
              style={{ width: '100%', height: 160, objectFit: 'cover' }}
            />
          ) : status === 'failed' ? (
            <Text type="danger" style={{ fontSize: 12 }}>
              生成失败
            </Text>
          ) : (
            <Space direction="vertical" align="center" size={4}>
              <Spin />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {status === 'pending' ? '排队中' : '生成中'}
              </Text>
            </Space>
          )}
        </div>
        <div title={img.prompt} style={{ fontSize: 12, color: '#888', marginTop: 6, maxHeight: 36, overflow: 'hidden' }}>
          {img.prompt}
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6 }}>
          <Button
            size="small"
            icon={<RedoOutlined />}
            disabled={busy || run?.active}
            onClick={() => handleRegenerateImage(img)}
          >
            重生成
          </Button>
          <Popconfirm
            title="确定删除此定妆照？"
            onConfirm={() => handleDeleteImage(img)}
            okText="删除"
            cancelText="取消"
          >
            <Button size="small" danger icon={<DeleteOutlined />} disabled={actionLoading === img.image_id} />
          </Popconfirm>
        </div>
      </div>
    )
  }

  return (
    <Card
      title={
        <span>
          {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
          剧本定妆照
        </span>
      }
      style={{ marginTop: 16 }}
    >
      <Text type="secondary">
        为分集设计中的人物 / 场景生成定妆照：Agent 基于实体设定与风格要求产出英文 prompt 并批量生图，完成后可单张重生成。
      </Text>

      {/* 实体勾选 */}
      <div style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>选择实体（已选 {selectedIds.size}）</Text>
        </div>
        {characters.length === 0 && scenes.length === 0 ? (
          <Empty description="暂无实体，请先完成分集设计" style={{ marginTop: 24 }} />
        ) : (
          <>
            {entityGroup('人物', characters)}
            {entityGroup('场景', scenes)}
          </>
        )}
      </div>

      {/* 风格与模型 */}
      <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 8 }}>
        <div style={{ flex: 1, minWidth: 320 }}>
          <Text type="secondary">风格要求（可选）</Text>
          <TextArea
            rows={1}
            value={stylePrompt}
            onChange={(e) => setStylePrompt(e.target.value)}
            placeholder="例如：电影质感、写实风格、暖色调"
            style={{ marginTop: 4 }}
          />
        </div>
        <div style={{ width: 340 }}>
          <Text type="secondary">生图模型</Text>
          <Select
            value={modelConfigId}
            onChange={(v) => setModelConfigId(v)}
            placeholder="默认使用「模型管理」中的默认生图模型"
            allowClear
            style={{ width: '100%', marginTop: 4 }}
            options={models.map((m) => ({
              value: m.id,
              label: `${m.name}${m.is_default ? '（默认）' : ''} · ${m.model_id || '未指定模型ID'}`,
            }))}
          />
        </div>
      </div>

      <div style={{ marginTop: 16 }}>
        <Button
          type="primary"
          size="large"
          icon={<ThunderboltOutlined />}
          loading={starting}
          disabled={run?.active}
          onClick={handleGenerate}
        >
          生成定妆照
        </Button>
      </div>

      {run && (
        <div style={{ marginTop: 16 }}>
          <AgentRunProgress runId={run.id} onDone={handleRunDone} />
        </div>
      )}

      {images.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <div style={{ marginBottom: 8 }}>
            <Text strong>定妆照（{images.length}）</Text>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>{images.map(imageCard)}</div>
        </div>
      )}

      <div style={{ marginTop: 24, borderTop: '1px solid #f0f0f0', paddingTop: 16, textAlign: 'center' }}>
        <Button
          type="primary"
          icon={<CheckCircleOutlined />}
          loading={completing}
          disabled={isCompleted || images.length === 0}
          onClick={handleComplete}
        >
          {isCompleted ? '本步骤已完成' : '完成本步骤'}
        </Button>
        {!isCompleted && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              确认定妆照满足要求后手动完成第 4 步
            </Text>
          </div>
        )}
      </div>
    </Card>
  )
}

export default StepLookbook
