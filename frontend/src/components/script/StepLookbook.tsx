/**
 * 第 4 步：全剧核心素材生成（实体卡片上直接生成 / 重新生成 / 删除，弹窗输入提示词，单卡片独立进度）
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Button, Card, Empty, Image, Input, Modal, Popconfirm, Select, Space, Spin, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, DeleteOutlined, PictureOutlined, RedoOutlined } from '@ant-design/icons'
import type { AgentEvent, ImageModelConfig, LookbookImage, ScriptEntity, ScriptSessionDetail } from '@/types'
import { entityApi, modelApi, scriptStepApi } from '@/api/client'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import { usePolling } from '@/hooks/usePolling'
import { AgentRunProgress } from './AgentRunProgress'
import { imageSrc } from '@/utils/imageSrc'

const { Text } = Typography
const { TextArea } = Input

// 图片风格选项：zh 为中文风格要求（并入 style_prompt 给 agent，生成路径）；en 为英文风格关键词（附加到生图 prompt，重新生成路径）
const IMAGE_STYLE_OPTIONS = [
  { value: 'auto', label: '自动（AI 根据剧本气质判断）', zh: '', en: '' },
  { value: 'realistic', label: '现实主义', zh: '写实摄影质感，真实自然光影与材质细节，像真实存在的照片', en: 'realistic photography style, shot on 35mm film, natural lighting, lifelike textures' },
  { value: '2d', label: '2D 插画', zh: '2D 手绘插画，干净线稿与扁平上色，明快配色', en: '2D illustration style, clean linework, flat colors' },
  { value: '3d', label: '3D 卡通渲染', zh: '皮克斯式 3D 卡通渲染，柔和全局光照，圆润造型，高细节材质', en: 'stylized 3D render, soft global illumination, subsurface scattering' },
  { value: 'anime', label: '日式动漫', zh: '日式动漫赛璐璐风格，clean line art，精致角色设计与背景美术', en: 'Japanese anime style, cel shading, clean line art' },
  { value: 'guofeng', label: '国风动漫', zh: '国风动漫美术，东方古典元素与配色，飘逸写意的中国风', en: 'Chinese guofeng anime style, oriental classical aesthetics, elegant flowing design' },
  { value: 'comic', label: '美漫风', zh: '美式漫画风格，粗犷勾线与网点排线阴影，强对比动态构图', en: 'American comic book style, bold ink outlines, halftone shading' },
  { value: 'ink', label: '水墨画', zh: '中国传统水墨画，毛笔笔触与留白意境，淡雅设色', en: 'traditional Chinese ink painting, brush strokes, negative space, muted colors' },
  { value: 'watercolor', label: '水彩手绘', zh: '水彩手绘质感，柔和晕染边缘与纸纹，清新通透', en: 'watercolor painting, soft bleeding edges, paper texture' },
  { value: 'cyberpunk', label: '赛博朋克', zh: '赛博朋克科幻风，霓虹灯光效与未来都市氛围，高对比冷暖色', en: 'cyberpunk style, neon lighting, futuristic sci-fi atmosphere' },
]

interface StepLookbookProps {
  session: ScriptSessionDetail
}

export const StepLookbook: React.FC<StepLookbookProps> = ({ session }) => {
  const { refreshSession } = useScriptSessionStore()
  const canExecute = session.completed_steps?.includes('episode_design')
  const isCompleted = session.completed_steps?.includes('lookbook_images')

  const [entities, setEntities] = useState<ScriptEntity[]>([])
  const [images, setImages] = useState<LookbookImage[]>([])
  const [models, setModels] = useState<ImageModelConfig[]>([])
  const [runs, setRuns] = useState<Map<string, string>>(new Map()) // entity_id -> run_id
  const [deleting, setDeleting] = useState('')
  const [modal, setModal] = useState<{ entity: ScriptEntity; image?: LookbookImage } | null>(null)
  const [promptText, setPromptText] = useState('')
  const [styleType, setStyleType] = useState('auto')
  const [modelConfigId, setModelConfigId] = useState<string | undefined>(undefined)
  const [confirming, setConfirming] = useState(false)
  const [completing, setCompleting] = useState(false)

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
      .then((r) => setModels(r.data?.models || []))
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
    { interval: 2000, enabled: runs.size > 0 || hasActiveImages }
  )

  // 实体的当前定妆照行：优先实体指向的行，否则取最新一条
  const imageByEntity = useMemo(() => {
    const m = new Map<string, LookbookImage>()
    for (const e of entities) {
      const rows = images.filter((i) => i.entity_id === e.entity_id)
      if (!rows.length) continue
      m.set(e.entity_id, rows.find((i) => i.image_id === e.lookbook_image_id) || rows[rows.length - 1])
    }
    return m
  }, [entities, images])

  const openModal = (entity: ScriptEntity, image?: LookbookImage) => {
    setPromptText(image?.prompt || '')
    setStyleType('auto')
    setModal({ entity, image })
  }

  const handleConfirm = async () => {
    if (!modal) return
    const { entity, image } = modal
    const style = IMAGE_STYLE_OPTIONS.find((s) => s.value === styleType && s.value !== 'auto')
    setConfirming(true)
    try {
      let runId: string
      if (image) {
        // 重新生成不走 agent：英文风格关键词附加到生图 prompt（提示词为空则沿用原 prompt 再附加）
        let prompt = promptText || undefined
        if (style) {
          const base = promptText || image.prompt || ''
          prompt = base ? `${base}, ${style.en}` : style.en
        }
        runId = await scriptStepApi.regenerateLookbookImage(
          session.session_id,
          image.image_id,
          prompt,
          modelConfigId
        )
      } else {
        // 生成走 agent：中文风格要求并入 style_prompt（优先级高于 agent 自行判断）
        const stylePrompt = [style ? `图片风格：${style.label}——${style.zh}` : '', promptText]
          .filter(Boolean)
          .join('\n')
        runId = await scriptStepApi.generateLookbook(
          session.session_id,
          [entity.entity_id],
          stylePrompt,
          modelConfigId
        )
      }
      setRuns((prev) => new Map(prev).set(entity.entity_id, runId))
      message.success('核心素材生成任务已启动')
      setModal(null)
      void loadImages()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConfirming(false)
    }
  }

  const handleRunDone = (entityId: string) => async (ev: AgentEvent) => {
    setRuns((prev) => {
      if (!prev.has(entityId)) return prev
      const next = new Map(prev)
      next.delete(entityId)
      return next
    })
    if (!ev.success) message.error(ev.error || '核心素材生成失败')
    await loadImages()
    await loadEntities()
  }

  const handleDeleteImage = async (image: LookbookImage) => {
    setDeleting(image.image_id)
    try {
      await scriptStepApi.deleteLookbookImage(session.session_id, image.image_id)
      message.success('核心素材已删除')
      await loadImages()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setDeleting('')
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
      <Card title="全剧核心素材生成" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 3 步：分集设计</Text>
      </Card>
    )
  }

  // ==================== 实体卡片 ====================

  const characters = entities.filter((e) => e.entity_type === 'character')
  const scenes = entities.filter((e) => e.entity_type === 'scene')

  const entityCard = (e: ScriptEntity) => {
    const img = imageByEntity.get(e.entity_id)
    const status = img?.task_status
    const runId = runs.get(e.entity_id)
    const busy = !!runId || status === 'pending' || status === 'processing'
    return (
      <div key={e.entity_id} style={{ width: 320, border: '1px solid #f0f0f0', borderRadius: 8, padding: 8 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, marginBottom: 6 }}>
          <Text strong ellipsis style={{ maxWidth: 120 }}>
            {e.name}
          </Text>
          <Tag style={{ marginRight: 0, fontSize: 11 }}>{e.entity_id}</Tag>
        </div>
        <div
          style={{
            width: '100%',
            height: 180,
            borderRadius: 6,
            overflow: 'hidden',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#fafafa',
          }}
        >
          {status === 'completed' && img?.image_path ? (
            <Image
              src={imageSrc(img.image_path)}
              alt={e.name}
              style={{ width: '100%', height: 180, objectFit: 'cover' }}
            />
          ) : busy ? (
            <Space direction="vertical" align="center" size={4}>
              <Spin />
              <Text type="secondary" style={{ fontSize: 12 }}>
                {status === 'pending' ? '排队中' : '生成中'}
              </Text>
            </Space>
          ) : status === 'failed' ? (
            <Text type="danger" style={{ fontSize: 12 }}>
              生成失败
            </Text>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>
              暂无核心素材
            </Text>
          )}
        </div>
        <div title={e.description} style={{ fontSize: 12, color: '#888', marginTop: 6, maxHeight: 36, overflow: 'hidden' }}>
          {e.description}
        </div>
        <div style={{ display: 'flex', justifyContent: img ? 'space-between' : 'center', marginTop: 6 }}>
          {img ? (
            <>
              <Button size="small" icon={<RedoOutlined />} disabled={busy} onClick={() => openModal(e, img)}>
                重新生成
              </Button>
              <Popconfirm
                title="确定删除此核心素材？"
                onConfirm={() => handleDeleteImage(img)}
                okText="删除"
                cancelText="取消"
              >
                <Button
                  size="small"
                  danger
                  icon={<DeleteOutlined />}
                  disabled={busy}
                  loading={deleting === img.image_id}
                />
              </Popconfirm>
            </>
          ) : (
            <Button
              size="small"
              type="primary"
              icon={<PictureOutlined />}
              disabled={busy}
              onClick={() => openModal(e)}
            >
              生成核心素材
            </Button>
          )}
        </div>
        {runId && (
          <div style={{ marginTop: 8 }}>
            <AgentRunProgress runId={runId} onDone={handleRunDone(e.entity_id)} />
          </div>
        )}
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

  return (
    <Card
      title={
        <span>
          {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
          全剧核心素材生成
        </span>
      }
      style={{ marginTop: 16 }}
    >
      <Text type="secondary">
        为分集设计中的人物 / 场景生成核心素材：人物为三视图设定图（含身高标注与比例尺），场景为全景素材图；点击卡片上的按钮，输入提示词后生成；已有素材可重新生成或删除，各卡片互不影响。
      </Text>

      {/* 实体卡片 */}
      <div style={{ marginTop: 16 }}>
        {characters.length === 0 && scenes.length === 0 ? (
          <Empty description="暂无实体，请先完成分集设计" style={{ marginTop: 24 }} />
        ) : (
          <>
            {entityGroup('人物', characters)}
            {entityGroup('场景', scenes)}
          </>
        )}
      </div>

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
              确认核心素材满足要求后手动完成第 4 步
            </Text>
          </div>
        )}
      </div>

      {/* 生成 / 重新生成弹窗 */}
      <Modal
        open={!!modal}
        title={`${modal?.image ? '重新生成' : '生成'}核心素材${modal ? ` - ${modal.entity.name}` : ''}`}
        okText="开始生成"
        cancelText="取消"
        confirmLoading={confirming}
        onOk={handleConfirm}
        onCancel={() => setModal(null)}
      >
        <div>
          <Text type="secondary">
            {modal?.image
              ? '提示词（可修改后重新生成，清空则沿用原提示词）'
              : '提示词（可选，风格要求；留空由 Agent 基于实体设定生成）'}
          </Text>
          <TextArea
            rows={3}
            value={promptText}
            onChange={(ev) => setPromptText(ev.target.value)}
            placeholder="例如：纪实摄影质感，自然光，真实生活感，35mm 胶片"
            style={{ marginTop: 4 }}
          />
        </div>
        <div style={{ marginTop: 12 }}>
          <Text type="secondary">图片风格</Text>
          <Select
            value={styleType}
            onChange={(v) => setStyleType(v)}
            style={{ width: '100%', marginTop: 4 }}
            options={IMAGE_STYLE_OPTIONS.map((s) => ({
              value: s.value,
              label: s.value === 'auto' ? s.label : `${s.label} · ${s.zh}`,
            }))}
          />
        </div>
        <div style={{ marginTop: 12 }}>
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
      </Modal>
    </Card>
  )
}

export default StepLookbook
