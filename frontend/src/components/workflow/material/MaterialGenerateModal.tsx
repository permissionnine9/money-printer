/**
 * AI 生成素材图弹窗：自定义提示词（支持 @ 引用素材池图片）+ 上传自定义参考图
 * → 调用 Agent 需求理解（自动注入剧本大纲/本集脚本/当前分镜）→ 直接生图
 * → 归档本集图库并自动加入当前分镜（提交后任务进后台队列，进度见右上角「后台任务」浮窗）。
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Image, Modal, Select, Space, Tag, Typography, Upload, message } from 'antd'
import {
  DeleteOutlined,
  PictureFilled,
  ThunderboltOutlined,
  UploadOutlined,
} from '@ant-design/icons'
import type { ImageModelConfig, PoolMaterial } from '@/types'
import { modelApi, stepApi, uploadApi } from '@/api/client'
import { useStartRun } from '@/hooks/useRunTask'
import { hasRunningSegmentMaterial } from '@/stores/agentRunStore'
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
  const { starting, launch } = useStartRun(sessionId)

  // 打开时刷新素材池/模型列表（保留提示词与参考图，便于微调后重新生成）
  useEffect(() => {
    if (!open) return
    setPickerOpen(false)
    stepApi
      .getMaterialPool(sessionId)
      .then((groups) => setPool(groups.flatMap((g) => g.materials)))
      .catch(() => setPool([]))
    modelApi
      .list('image')
      .then((r) => setModels((r.data?.models || []).filter((m) => m.enabled !== false)))
      .catch(() => setModels([]))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, open])

  // 切换会话/分镜时才清空输入（提示词与参考图针对具体分镜）
  useEffect(() => {
    setUserPrompt('')
    setMentions([])
    setUploadPaths([])
    setPickedMaterials([])
    setModelConfigId(undefined)
  }, [sessionId, segmentIndex])

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
    // 提交后任务进全局后台队列（AgentRunDock 跟踪进度，成功后自动刷新会话）
    await launch({
      kind: 'segment_material',
      label: `分镜 ${segmentIndex + 1} 素材图`,
      // 分镜粒度守卫（同分镜防重复；不同分镜可并行），替换默认的 kind 级守卫
      guard: () => {
        if (hasRunningSegmentMaterial(sessionId, segmentIndex)) {
          message.warning(`分镜 ${segmentIndex + 1} 的素材图正在生成中（见右上角后台任务），请等待完成后再试`)
          return true
        }
        return false
      },
      close: onClose,
      extra: { segmentIndex, segmentTitle },
      invoke: () =>
        stepApi.generateSegmentMaterial(sessionId, segmentIndex, {
          user_prompt: userPrompt.trim(),
          mentioned_image_ids: [...mentions, ...pickedMaterials].map((m) => m.image_id),
          reference_paths: uploadPaths,
          ...(modelConfigId ? { model_config_id: modelConfigId } : {}),
        }),
      infoText: '素材图生成已发起，进度见右上角后台任务',
    })
  }

  return (
    <Modal
      title={`AI 生成素材图 - 分镜 ${segmentIndex + 1}${segmentTitle ? `《${segmentTitle}》` : ''}`}
      open={open}
      onCancel={onClose}
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          icon={<ThunderboltOutlined />}
          loading={starting}
          onClick={handleSubmit}
        >
          生成（AI 需求理解 → 生图）
        </Button>,
      ]}
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
