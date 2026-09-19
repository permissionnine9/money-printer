/**
 * AI 生成素材图弹窗：自定义提示词（支持 @ 引用素材池图片）+ 上传自定义参考图
 * → 调用 Agent 需求理解（自动注入剧本大纲/本集脚本/当前分镜）→ 直接生图
 * → 归档本集图库并自动加入当前分镜（SSE 观流，AgentRunProgress）。
 */
import React, { useEffect, useState } from 'react'
import { Alert, Button, Card, Image, Modal, Select, Space, Tag, Typography, Upload, message } from 'antd'
import {
  DeleteOutlined,
  PictureOutlined,
  PictureFilled,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import type { AgentEvent, ImageModelConfig, PoolMaterial } from '@/types'
import { modelApi, stepApi, uploadApi } from '@/api/client'
import { AgentRunProgress } from '@/components/script/AgentRunProgress'
import { MentionImageInput } from './MentionImageInput'
import { MaterialPickerModal } from './MaterialPickerModal'
import { imageSrc } from '@/utils/imageSrc'

const { Text, Paragraph } = Typography

export interface MaterialGenerateModalProps {
  sessionId: string
  segmentIndex: number
  segmentTitle?: string
  segmentOutline?: string
  episodeTitle?: string
  /** 本分镜素材图（选择弹窗第 3 个 tab） */
  segmentMaterials?: PoolMaterial[]
  open: boolean
  onClose: () => void
  /** 生成成功后回调（父组件刷新会话） */
  onGenerated: () => void
}

export const MaterialGenerateModal: React.FC<MaterialGenerateModalProps> = ({
  sessionId,
  segmentIndex,
  segmentTitle,
  segmentOutline,
  episodeTitle,
  segmentMaterials,
  open,
  onClose,
  onGenerated,
}) => {
  const [pool, setPool] = useState<PoolMaterial[]>([])
  const [userPrompt, setUserPrompt] = useState('')
  const [mentions, setMentions] = useState<PoolMaterial[]>([])
  const [uploadPaths, setUploadPaths] = useState<string[]>([])
  const [pickedMaterials, setPickedMaterials] = useState<PoolMaterial[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [models, setModels] = useState<ImageModelConfig[]>([])
  const [modelConfigId, setModelConfigId] = useState<string | undefined>(undefined)
  const [submitting, setSubmitting] = useState(false)
  const [run, setRun] = useState<{ id: string; active: boolean } | null>(null)

  useEffect(() => {
    if (!open) return
    setUserPrompt('')
    setMentions([])
    setUploadPaths([])
    setPickedMaterials([])
    setPickerOpen(false)
    setModelConfigId(undefined)
    setRun(null)
    stepApi
      .getMaterialPool(sessionId)
      .then((groups) => setPool(groups.flatMap((g) => g.materials)))
      .catch(() => setPool([]))
    modelApi
      .list('image')
      .then((r) => setModels(r.data?.models || []))
      .catch(() => setModels([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, open])

  const handleUpload = async (file: File) => {
    setUploading(true)
    try {
      const result = await uploadApi.uploadImage(file)
      setUploadPaths((prev) => [...prev, result.file_path])
      message.success('参考图上传成功')
    } catch (e) {
      message.error('上传失败：' + (e as Error).message)
    } finally {
      setUploading(false)
    }
    return false
  }

  const refCount = uploadPaths.length + mentions.length + pickedMaterials.length

  const handleSubmit = async () => {
    if (!userPrompt.trim() && refCount === 0) {
      message.warning('请填写提示词，或提供参考图（@ 素材图 / 选择素材图 / 上传参考图）')
      return
    }
    setSubmitting(true)
    try {
      const runId = await stepApi.generateSegmentMaterial(sessionId, segmentIndex, {
        user_prompt: userPrompt.trim(),
        mentioned_image_ids: [...mentions, ...pickedMaterials].map((m) => m.image_id),
        reference_paths: uploadPaths,
        ...(modelConfigId ? { model_config_id: modelConfigId } : {}),
      })
      setRun({ id: runId, active: true })
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  const handleRunDone = async (ev: AgentEvent) => {
    setRun((r) => (r ? { ...r, active: false } : r))
    if (ev.success) {
      message.success('素材图已生成并加入本分镜')
      onGenerated()
      onClose()
    } else {
      message.error(ev.error || '素材图生成失败')
    }
  }

  return (
    <Modal
      title={`AI 生成素材图 - 分镜 ${segmentIndex + 1}${segmentTitle ? `《${segmentTitle}》` : ''}`}
      open={open}
      onCancel={() => {
        if (run?.active) return // 生成中不允许关闭
        onClose()
      }}
      footer={
        run
          ? null
          : [
              <Button key="cancel" onClick={onClose}>
                取消
              </Button>,
              <Button
                key="ok"
                type="primary"
                icon={<ThunderboltOutlined />}
                loading={submitting}
                onClick={handleSubmit}
              >
                生成（AI 需求理解 → 生图）
              </Button>,
            ]
      }
      width={680}
      destroyOnHidden
    >
      {/* 上下文摘要（自动注入） */}
      <Card size="small" style={{ marginBottom: 12 }}>
        <Space size={6} wrap style={{ marginBottom: 6 }}>
          <Tag color="blue">自动注入上下文</Tag>
          <Tag>剧本大纲</Tag>
          <Tag>本集脚本{episodeTitle ? `（${episodeTitle}）` : ''}</Tag>
          <Tag>当前分镜内容</Tag>
        </Space>
        <Paragraph
          style={{ marginBottom: 0, fontSize: 13, color: 'rgba(0,0,0,0.65)' }}
          ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
        >
          {segmentTitle && <Text strong>{`【${segmentTitle}】`}</Text>}
          {segmentOutline || '（无大纲）'}
        </Paragraph>
      </Card>

      {/* 自定义参考图：上传 / 从素材库选择 */}
      <div style={{ marginBottom: 4 }}>
        <Text style={{ fontSize: 13 }}>自定义参考图（可选，最多 4 张，与 @ 素材合并使用）</Text>
      </div>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        {uploadPaths.map((p) => (
          <div key={p} style={{ position: 'relative', width: 60, height: 60 }}>
            <Image
              src={imageSrc(p)}
              alt="参考图"
              style={{ width: 60, height: 60, objectFit: 'cover', borderRadius: 6 }}
              preview={false}
            />
            <Button
              size="small"
              type="primary"
              danger
              shape="circle"
              icon={<DeleteOutlined />}
              style={{ position: 'absolute', top: -6, right: -6, width: 20, height: 20, minWidth: 20 }}
              onClick={() => setUploadPaths((prev) => prev.filter((x) => x !== p))}
            />
          </div>
        ))}
        {pickedMaterials.map((m) => (
          <div key={m.image_id} style={{ position: 'relative', width: 60, height: 60 }}>
            <Image
              src={imageSrc(m.image_path)}
              alt={m.title || m.description || '素材图'}
              style={{ width: 60, height: 60, objectFit: 'cover', borderRadius: 6 }}
              preview={false}
            />
            <Button
              size="small"
              type="primary"
              danger
              shape="circle"
              icon={<DeleteOutlined />}
              style={{ position: 'absolute', top: -6, right: -6, width: 20, height: 20, minWidth: 20 }}
              onClick={() => setPickedMaterials((prev) => prev.filter((x) => x.image_id !== m.image_id))}
            />
          </div>
        ))}
        <Button
          icon={<PictureFilled />}
          disabled={refCount >= 4}
          onClick={() => setPickerOpen(true)}
        >
          选择素材图
        </Button>
        <Upload
          accept="image/*"
          showUploadList={false}
          beforeUpload={handleUpload}
          disabled={uploading || refCount >= 4}
        >
          <Button icon={<UploadOutlined />} loading={uploading} disabled={refCount >= 4}>
            上传参考图
          </Button>
        </Upload>
      </div>

      {/* 提示词（@ 引用素材）+ 生图模型同行 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <Text style={{ fontSize: 13, flex: 1, minWidth: 0 }}>
          自定义提示词（输入 <Text code>@</Text> 可引用素材池图片作为生图参考）
        </Text>
        <Text style={{ fontSize: 13, flexShrink: 0 }}>模型</Text>
        <Select
          value={modelConfigId}
          onChange={setModelConfigId}
          placeholder="默认生图模型"
          allowClear
          style={{ width: 100 }}
          options={models.map((m) => ({ value: m.id, label: m.name || m.model_id }))}
        />
      </div>
      <MentionImageInput
        value={userPrompt}
        onChange={setUserPrompt}
        mentions={mentions}
        onMentionsChange={setMentions}
        pool={pool}
        rows={4}
      />

      {run && (
        <div style={{ marginTop: 12 }}>
          {run.active && (
            <Alert
              type="info"
              showIcon
              icon={<PictureOutlined />}
              style={{ marginBottom: 8 }}
              message="生成中：AI 需求理解 → 生图 → 归档本集图库（static/images/{剧本}/{本集}/）→ 自动加入本分镜"
            />
          )}
          <AgentRunProgress runId={run.id} onDone={handleRunDone} />
        </div>
      )}

      <MaterialPickerModal
        sessionId={sessionId}
        open={pickerOpen}
        multi
        excludeImageIds={[...mentions, ...pickedMaterials].map((m) => m.image_id)}
        segmentMaterials={segmentMaterials}
        onClose={() => setPickerOpen(false)}
        onConfirm={(items) =>
          setPickedMaterials((prev) => {
            const seen = new Set(prev.map((x) => x.image_id))
            return [...prev, ...items.filter((m) => !seen.has(m.image_id))].slice(0, 4 - uploadPaths.length - mentions.length)
          })
        }
      />
    </Modal>
  )
}

export default MaterialGenerateModal
