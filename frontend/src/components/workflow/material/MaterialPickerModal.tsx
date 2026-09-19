/**
 * 素材图选择组件（可复用）：3 个 tab 分组展示素材池。
 * Tab1 剧本定妆照 / Tab2 本集素材（含其他集素材）/ Tab3 本分镜素材（传入 segmentMaterials 时展示）。
 * multi=true 勾选多张确认；否则单选（点击即确认，用于「更换」场景）。
 */
import React, { useEffect, useState } from 'react'
import { Button, Card, Empty, Image, Modal, Popconfirm, Spin, Tabs, Tooltip, Typography, message } from 'antd'
import { CheckSquareFilled, DeleteOutlined, PictureOutlined } from '@ant-design/icons'
import type { MaterialPoolGroup, PoolMaterial } from '@/types'
import { stepApi } from '@/api/client'
import { imageSrc } from '@/utils/imageSrc'

const { Text } = Typography

export interface MaterialPickerModalProps {
  sessionId: string
  open: boolean
  /** 多选（确认按钮）或单选（点击即确认） */
  multi?: boolean
  /** 隐藏这些 ID（已被当前分镜引用的素材） */
  excludeImageIds?: string[]
  /** 本分镜素材图（传入时展示第 3 个 tab） */
  segmentMaterials?: PoolMaterial[]
  onClose: () => void
  onConfirm: (items: PoolMaterial[]) => void
}

const MaterialGrid: React.FC<{
  groups: { key: string; label: string; materials: PoolMaterial[] }[]
  selected: PoolMaterial[]
  onItemClick: (m: PoolMaterial) => void
  /** 删除素材图（仅 AI 生成的 mat_* 素材；删除后分镜中已引用处将失效） */
  onDelete?: (m: PoolMaterial) => void
}> = ({ groups, selected, onItemClick, onDelete }) => (
  <div style={{ maxHeight: 420, overflowY: 'auto' }}>
    {groups.map((g) => (
      <Card
        key={g.key}
        size="small"
        title={<Text style={{ fontSize: 13 }}>{g.label}</Text>}
        style={{ marginBottom: 12 }}
      >
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {g.materials.map((m) => {
            const checked = selected.some((x) => x.image_id === m.image_id)
            return (
              <Tooltip
                key={m.image_id}
                title={m.description || m.title || m.image_id}
                placement="top"
              >
                <div
                  onClick={() => onItemClick(m)}
                  style={{
                    position: 'relative',
                    width: 108,
                    cursor: 'pointer',
                    border: checked ? '2px solid #1677ff' : '1px solid #f0f0f0',
                    borderRadius: 8,
                    padding: 4,
                  }}
                >
                  {checked && (
                    <CheckSquareFilled
                      style={{
                        position: 'absolute',
                        top: 8,
                        right: 8,
                        fontSize: 18,
                        color: '#1677ff',
                        zIndex: 1,
                      }}
                    />
                  )}
                  {onDelete && m.image_id.startsWith('mat_') && (
                    <Popconfirm
                      title="删除该素材图？"
                      description="分镜中已引用该图的地方将失效"
                      okText="删除"
                      cancelText="取消"
                      onConfirm={(e) => {
                        e?.stopPropagation()
                        onDelete(m)
                      }}
                      onCancel={(e) => e?.stopPropagation()}
                    >
                      <Button
                        size="small"
                        type="primary"
                        danger
                        shape="circle"
                        icon={<DeleteOutlined />}
                        style={{ position: 'absolute', top: 4, left: 4, width: 20, height: 20, minWidth: 20, zIndex: 2 }}
                        onClick={(e) => e.stopPropagation()}
                      />
                    </Popconfirm>
                  )}
                  <Image
                    src={imageSrc(m.image_path)}
                    alt={m.title || m.description}
                    style={{ objectFit: 'cover', width: '100%', height: 78, borderRadius: 6 }}
                    preview={false}
                    fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                  />
                  <div
                    style={{
                      marginTop: 4,
                      fontSize: 12,
                      color: 'rgba(0,0,0,0.65)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 4,
                    }}
                  >
                    <PictureOutlined />
                    {m.title || m.description || m.image_id}
                  </div>
                </div>
              </Tooltip>
            )
          })}
        </div>
      </Card>
    ))}
  </div>
)

export const MaterialPickerModal: React.FC<MaterialPickerModalProps> = ({
  sessionId,
  open,
  multi = true,
  excludeImageIds = [],
  segmentMaterials,
  onClose,
  onConfirm,
}) => {
  const [groups, setGroups] = useState<MaterialPoolGroup[]>([])
  const [loading, setLoading] = useState(false)
  const [selected, setSelected] = useState<PoolMaterial[]>([])
  const [error, setError] = useState('')

  const loadPool = () => {
    setLoading(true)
    setError('')
    stepApi
      .getMaterialPool(sessionId)
      .then(setGroups)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!open) return
    setSelected([])
    loadPool()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, open])

  const filterGroups = (predicate: (g: MaterialPoolGroup) => boolean) =>
    groups
      .filter(predicate)
      .map((g) => ({ ...g, materials: g.materials.filter((m) => !excludeImageIds.includes(m.image_id)) }))
      .filter((g) => g.materials.length > 0)

  const lookbookGroups = filterGroups((g) => g.key === 'lookbook')
  const episodeGroups = filterGroups((g) => g.key !== 'lookbook')
  const segmentGroups = (segmentMaterials || []).filter((m) => !excludeImageIds.includes(m.image_id))
  const total =
    lookbookGroups.reduce((n, g) => n + g.materials.length, 0) +
    episodeGroups.reduce((n, g) => n + g.materials.length, 0)

  const toggle = (m: PoolMaterial) => {
    setSelected((prev) =>
      prev.some((x) => x.image_id === m.image_id)
        ? prev.filter((x) => x.image_id !== m.image_id)
        : [...prev, m]
    )
  }

  const handleItemClick = (m: PoolMaterial) => {
    if (multi) {
      toggle(m)
    } else {
      onConfirm([m])
      onClose()
    }
  }

  // 删除 AI 生成的素材图（mat_*）后刷新素材池
  const handleDeleteMaterial = async (m: PoolMaterial) => {
    try {
      await stepApi.deleteMaterial(sessionId, m.image_id)
      message.success('素材图已删除')
      setSelected((prev) => prev.filter((x) => x.image_id !== m.image_id))
      loadPool()
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const handleConfirm = () => {
    if (selected.length === 0) {
      message.warning('请先选择素材图')
      return
    }
    onConfirm(selected)
    onClose()
  }

  const emptyHint = (
    <Empty
      description="素材池为空：可先在第 4 步剧本工作流生成定妆照，或用「AI 生成素材图」创建"
      style={{ padding: '24px 0' }}
    />
  )

  const tabItems = [
    { key: 'lookbook', label: '定妆照', children: lookbookGroups.length ? <MaterialGrid groups={lookbookGroups} selected={selected} onItemClick={handleItemClick} /> : emptyHint },
    { key: 'episode', label: '本集素材', children: episodeGroups.length ? <MaterialGrid groups={episodeGroups} selected={selected} onItemClick={handleItemClick} onDelete={handleDeleteMaterial} /> : emptyHint },
    ...(segmentMaterials !== undefined
      ? [{
          key: 'segment',
          label: '本分镜素材',
          children: segmentGroups.length ? (
            <MaterialGrid
              groups={[{ key: 'segment', label: '当前分镜素材图', materials: segmentGroups }]}
              selected={selected}
              onItemClick={handleItemClick}
            />
          ) : (
            <Empty description="本分镜尚未关联素材图" style={{ padding: '24px 0' }} />
          ),
        }]
      : []),
  ]

  return (
    <Modal
      title={multi ? '选择素材图（可多选）' : '选择素材图'}
      open={open}
      onCancel={onClose}
      width={760}
      destroyOnHidden
      footer={
        multi
          ? [
              <Button key="cancel" onClick={onClose}>
                取消
              </Button>,
              <Button key="ok" type="primary" disabled={selected.length === 0} onClick={handleConfirm}>
                确定{selected.length > 0 ? `（${selected.length} 张）` : ''}
              </Button>,
            ]
          : null
      }
    >
      <Spin spinning={loading}>
        {error ? (
          <Text type="danger">{error}</Text>
        ) : total === 0 && segmentGroups.length === 0 && !loading ? (
          emptyHint
        ) : (
          <Tabs defaultActiveKey="lookbook" items={tabItems} />
        )}
      </Spin>
      {multi && selected.length > 0 && (
        <div style={{ marginTop: 4 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            已选 {selected.length} 张
          </Text>
        </div>
      )}
    </Modal>
  )
}

export default MaterialPickerModal
