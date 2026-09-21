/**
 * 定妆照素材库选择弹窗（第 4 步复用）：跨剧本会话 + 本剧本历史素材，单选绑定到实体。
 * 选中后复制素材到当前剧本（引用同一图片 URL）并锚定，源剧本删除不受影响。
 */
import React, { useEffect, useState } from 'react'
import { Button, Empty, Modal, Spin, Typography, message } from 'antd'
import type { LookbookImage, LookbookLibraryGroup, PoolMaterial, ScriptEntity } from '@/types'
import { scriptStepApi } from '@/api/client'
import { MaterialGrid } from '@/components/workflow/material/MaterialPickerModal'

const { Text } = Typography

export interface LookbookLibraryModalProps {
  sessionId: string
  /** 绑定目标实体（用于标题与过滤已锚定图） */
  entity: ScriptEntity | null
  open: boolean
  onClose: () => void
  onImported: (image: LookbookImage) => void
}

export const LookbookLibraryModal: React.FC<LookbookLibraryModalProps> = ({
  sessionId,
  entity,
  open,
  onClose,
  onImported,
}) => {
  const [groups, setGroups] = useState<LookbookLibraryGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<PoolMaterial | null>(null)
  const [importing, setImporting] = useState(false)

  useEffect(() => {
    if (!open) return
    setSelected(null)
    setError('')
    setLoading(true)
    scriptStepApi
      .getLookbookLibrary(sessionId)
      .then(setGroups)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
  }, [sessionId, open])

  // 排除目标实体当前已锚定的那张；映射为 MaterialGrid 展示形态（源实体已重建/删除时标注）
  const displayGroups = entity
    ? groups
        .map((g) => ({
          key: g.key,
          label: g.label,
          materials: g.materials
            .filter((m) => m.image_id !== entity.lookbook_image_id)
            .map((m) => ({
              image_id: m.image_id,
              image_path: m.image_path,
              description: m.description,
              title: m.entity_exists ? m.entity_name || m.entity_id : `${m.entity_id}（实体已失效）`,
            })),
        }))
        .filter((g) => g.materials.length > 0)
    : []

  const handleItemClick = (m: PoolMaterial) => {
    setSelected((prev) => (prev?.image_id === m.image_id ? null : m))
  }

  const handleImport = async () => {
    if (!entity || !selected) return
    setImporting(true)
    try {
      const image = await scriptStepApi.importLookbookImage(sessionId, entity.entity_id, selected.image_id)
      message.success('核心素材已绑定')
      onImported(image)
      onClose()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setImporting(false)
    }
  }

  return (
    <Modal
      title={`从素材库选择${entity ? ` - ${entity.name}` : ''}`}
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnHidden
      footer={[
        <Button key="cancel" onClick={onClose}>
          取消
        </Button>,
        <Button
          key="ok"
          type="primary"
          disabled={!selected}
          loading={importing}
          onClick={handleImport}
        >
          {entity ? `绑定到「${entity.name}」` : '绑定'}
        </Button>,
      ]}
    >
      <Text type="secondary" style={{ fontSize: 12 }}>
        跨剧本与本剧本历史的已完成素材；选中后复制到当前剧本并锚定到该实体
      </Text>
      <Spin spinning={loading} style={{ marginTop: 8 }}>
        {error ? (
          <Text type="danger">{error}</Text>
        ) : displayGroups.length ? (
          <MaterialGrid groups={displayGroups} selected={selected ? [selected] : []} onItemClick={handleItemClick} />
        ) : (
          <Empty
            description="素材库为空：可先生成核心素材，之后修改大纲/分集设计时已完成的素材会自动保留"
            style={{ padding: '24px 0' }}
          />
        )}
      </Spin>
    </Modal>
  )
}

export default LookbookLibraryModal
