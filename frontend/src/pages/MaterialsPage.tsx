/**
 * 素材管理页面：全局素材（生成图 / 上传参考图 / 视频）列表、引用保护删除、孤儿文件清理。
 * 引用中的素材不可删除（需先在分镜/实体中解除引用）；孤儿清理按路径批量删除无引用文件。
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Badge,
  Button,
  Card,
  Empty,
  Image,
  Modal,
  Popconfirm,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import { ClearOutlined, DeleteOutlined, ReloadOutlined } from '@ant-design/icons'
import type { ColumnsType } from 'antd/es/table'
import type { FileMaterialItem, GeneratedMaterialItem, MaterialReference, OrphanFileItem } from '@/types'
import { materialApi } from '@/api/client'
import { imageSrc } from '@/utils/imageSrc'

const { Text, Paragraph } = Typography

type MaterialKind = 'lookbook' | 'episode' | 'upload' | 'video'

const KIND_TABS: { key: MaterialKind; label: string }[] = [
  { key: 'lookbook', label: '定妆照' },
  { key: 'episode', label: '分集素材图' },
  { key: 'upload', label: '上传参考图' },
  { key: 'video', label: '视频' },
]

const ORPHAN_KIND_LABEL: Record<OrphanFileItem['kind'], string> = {
  image: '图片',
  video: '视频',
  upload: '上传',
}

function formatBytes(size: number): string {
  if (!size) return '-'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  if (size < 1024 * 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`
  return `${(size / 1024 / 1024 / 1024).toFixed(2)} GB`
}

function formatTime(value: number | string): string {
  if (!value) return '-'
  const date = typeof value === 'number' ? new Date(value * 1000) : new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('zh-CN', { hour12: false })
}

function referenceLabel(ref: MaterialReference): string {
  if (ref.ref_type === 'entity') {
    return `${ref.script_title} · 实体「${ref.entity_name || ref.entity_id}」`
  }
  return `${ref.script_title} · 分镜「${ref.segment_title || (ref.segment_index ?? '')}」`
}

const MaterialsPage: React.FC = () => {
  const [activeKind, setActiveKind] = useState<MaterialKind>('lookbook')
  const [generatedItems, setGeneratedItems] = useState<GeneratedMaterialItem[]>([])
  const [fileItems, setFileItems] = useState<FileMaterialItem[]>([])
  const [loading, setLoading] = useState(false)
  const [scriptFilter, setScriptFilter] = useState<string>('all')

  // 孤儿清理
  const [orphanOpen, setOrphanOpen] = useState(false)
  const [orphans, setOrphans] = useState<OrphanFileItem[]>([])
  const [orphanLoading, setOrphanLoading] = useState(false)
  const [orphanSelected, setOrphanSelected] = useState<string[]>([])
  const [orphanDeleting, setOrphanDeleting] = useState(false)

  const loadMaterials = async (kind: MaterialKind) => {
    setLoading(true)
    try {
      const result = await materialApi.list(kind)
      if (kind === 'lookbook' || kind === 'episode') {
        setGeneratedItems((result.items as GeneratedMaterialItem[]) || [])
        setFileItems([])
      } else {
        setFileItems((result.items as FileMaterialItem[]) || [])
        setGeneratedItems([])
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    setScriptFilter('all')
    loadMaterials(activeKind)
  }, [activeKind])

  const scriptOptions = useMemo(() => {
    const titles = Array.from(new Set(generatedItems.map((i) => i.script_title)))
    return [
      { value: 'all', label: `全部剧本（${generatedItems.length}）` },
      ...titles.map((t) => ({ value: t, label: `${t}（${generatedItems.filter((i) => i.script_title === t).length}）` })),
    ]
  }, [generatedItems])

  const visibleGenerated = useMemo(
    () => (scriptFilter === 'all' ? generatedItems : generatedItems.filter((i) => i.script_title === scriptFilter)),
    [generatedItems, scriptFilter]
  )

  const handleDeleteImage = async (item: GeneratedMaterialItem) => {
    try {
      const result = await materialApi.deleteImage(item.image_id)
      message.success(result.file_deleted ? '素材与文件已删除' : '素材记录已删除（文件被其他素材共享）')
      loadMaterials(activeKind)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleDeleteFile = async (item: FileMaterialItem) => {
    try {
      const result = await materialApi.deleteFiles([item.path])
      if (result.deleted.length) {
        message.success('文件已删除')
      } else if (result.failed.length) {
        message.error(`删除失败：${result.failed[0].reason}`)
      }
      loadMaterials(activeKind)
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  // ==================== 孤儿清理 ====================

  const openOrphanModal = async () => {
    setOrphanOpen(true)
    setOrphanLoading(true)
    setOrphanSelected([])
    try {
      const result = await materialApi.scanOrphans()
      setOrphans(result.items)
    } catch (error) {
      message.error((error as Error).message)
      setOrphans([])
    } finally {
      setOrphanLoading(false)
    }
  }

  const orphanTotalSize = useMemo(() => orphans.reduce((sum, i) => sum + i.size, 0), [orphans])

  const handleOrphanDelete = async () => {
    if (!orphanSelected.length) return
    setOrphanDeleting(true)
    try {
      const result = await materialApi.deleteFiles(orphanSelected)
      if (result.failed.length) {
        message.warning(`${result.deleted.length} 个已删除，${result.failed.length} 个失败：${result.failed[0].reason}`)
      } else {
        message.success(`已删除 ${result.deleted.length} 个文件`)
      }
      // 重新扫描并刷新当前列表
      const rescan = await materialApi.scanOrphans().catch(() => null)
      setOrphans(rescan?.items || [])
      setOrphanSelected([])
      loadMaterials(activeKind)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setOrphanDeleting(false)
    }
  }

  // ==================== 渲染 ====================

  const referenceBadge = (count: number, labels: string[]) =>
    count > 0 ? (
      <Tooltip
        title={
          <div style={{ maxHeight: 240, overflowY: 'auto' }}>
            {labels.map((label, i) => (
              <div key={i}>{label}</div>
            ))}
          </div>
        }
      >
        <Badge status="processing" text={<Text type="secondary">引用中 {count}</Text>} />
      </Tooltip>
    ) : (
      <Badge status="default" text={<Text type="secondary">未引用</Text>} />
    )

  const renderImageGrid = () => (
    <Spin spinning={loading}>
      {visibleGenerated.length ? (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {visibleGenerated.map((item) => (
            <div
              key={item.image_id}
              style={{
                width: 200,
                border: '1px solid #f0f0f0',
                borderRadius: 8,
                padding: 8,
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
              }}
            >
              <Image
                src={imageSrc(item.image_path)}
                alt={item.description}
                height={120}
                style={{ objectFit: 'cover', borderRadius: 4, background: '#fafafa' }}
                fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNsbGhhAAB4AQC0AS2MHwAAAABJRU5ErkJggg=="
              />
              <Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0, fontSize: 12 }} title={item.description}>
                {item.description || item.title || item.image_id}
              </Paragraph>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Tooltip title={item.script_title}>
                  <Tag style={{ marginInlineEnd: 0, maxWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {item.script_title}
                  </Tag>
                </Tooltip>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {formatBytes(item.size)}
                </Text>
              </div>
              {referenceBadge(item.reference_count, item.references.map(referenceLabel))}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  {formatTime(item.created_at)}
                </Text>
                <Popconfirm
                  title={item.is_remote ? '删除素材记录？（远程图片无本地文件）' : '确定删除该素材及文件？'}
                  onConfirm={() => handleDeleteImage(item)}
                  okText="删除"
                  cancelText="取消"
                  disabled={item.reference_count > 0}
                >
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    disabled={item.reference_count > 0}
                    title={item.reference_count > 0 ? '素材正被引用，需先在分镜/实体中解除引用' : undefined}
                  />
                </Popconfirm>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <Empty description="暂无素材" style={{ padding: '32px 0' }} />
      )}
    </Spin>
  )

  const fileColumns: ColumnsType<FileMaterialItem> = [
    {
      title: '文件名',
      dataIndex: 'name',
      key: 'name',
      ellipsis: true,
      render: (name: string, record) => (
        <Tooltip title={record.path}>
          <span>{name}</span>
        </Tooltip>
      ),
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size: number) => formatBytes(size),
    },
    {
      title: '修改时间',
      dataIndex: 'mtime',
      key: 'mtime',
      width: 180,
      render: (mtime: number) => formatTime(mtime),
    },
    ...(activeKind === 'video'
      ? [
          {
            title: '归属剧本',
            dataIndex: 'script_title',
            key: 'script_title',
            width: 160,
            render: (title: string) => title || <Text type="secondary">-</Text>,
          },
        ]
      : []),
    {
      title: '引用',
      key: 'reference',
      width: 120,
      render: (_: unknown, record: FileMaterialItem) =>
        referenceBadge(
          record.reference_count,
          (record.references || []).map((r) =>
            r.script_title ? `剧本「${r.script_title}」` : `视频工作流 ${r.video_session_id.slice(0, 8)}`
          )
        ),
    },
    {
      title: '操作',
      key: 'actions',
      width: 90,
      render: (_: unknown, record: FileMaterialItem) => (
        <Popconfirm
          title="确定删除该文件？"
          onConfirm={() => handleDeleteFile(record)}
          okText="删除"
          cancelText="取消"
          disabled={record.reference_count > 0}
        >
          <Button
            size="small"
            danger
            icon={<DeleteOutlined />}
            disabled={record.reference_count > 0}
            title={record.reference_count > 0 ? '文件正被工作流引用' : undefined}
          />
        </Popconfirm>
      ),
    },
  ]

  const renderFileTable = () => (
    <Table
      rowKey="path"
      columns={fileColumns}
      dataSource={fileItems}
      loading={loading}
      pagination={false}
      locale={{ emptyText: '暂无文件' }}
    />
  )

  const orphanColumns: ColumnsType<OrphanFileItem> = [
    {
      title: '文件路径',
      dataIndex: 'path',
      key: 'path',
      ellipsis: true,
    },
    {
      title: '类型',
      dataIndex: 'kind',
      key: 'kind',
      width: 80,
      render: (kind: OrphanFileItem['kind']) => <Tag>{ORPHAN_KIND_LABEL[kind]}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'size',
      key: 'size',
      width: 100,
      render: (size: number) => formatBytes(size),
    },
    {
      title: '修改时间',
      dataIndex: 'mtime',
      key: 'mtime',
      width: 180,
      render: (mtime: number) => formatTime(mtime),
    },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Card
        title="素材管理"
        extra={
          <Space>
            {(activeKind === 'lookbook' || activeKind === 'episode') && (
              <Select
                style={{ minWidth: 200 }}
                value={scriptFilter}
                onChange={setScriptFilter}
                options={scriptOptions}
              />
            )}
            <Button icon={<ReloadOutlined />} onClick={() => loadMaterials(activeKind)} loading={loading}>
              刷新
            </Button>
            <Button icon={<ClearOutlined />} onClick={openOrphanModal}>
              孤儿清理
            </Button>
          </Space>
        }
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            查看服务器上的全部素材（生成图 / 上传参考图 / 视频）。引用中的素材不可删除；删除剧本不会清理已生成的文件，
            可用「孤儿清理」批量删除无引用的残留文件。
          </Text>
        </div>
        <Tabs
          activeKey={activeKind}
          onChange={(key) => setActiveKind(key as MaterialKind)}
          items={KIND_TABS.map((tab) => ({
            key: tab.key,
            label:
              tab.key === 'lookbook' || tab.key === 'episode'
                ? `${tab.label}（${generatedItems.length}）`
                : `${tab.label}（${fileItems.length}）`,
            children:
              tab.key === 'lookbook' || tab.key === 'episode' ? renderImageGrid() : renderFileTable(),
          }))}
        />
      </Card>

      <Modal
        title="孤儿文件清理"
        open={orphanOpen}
        onCancel={() => setOrphanOpen(false)}
        width={760}
        footer={[
          <Button key="cancel" onClick={() => setOrphanOpen(false)}>
            关闭
          </Button>,
          <Button
            key="all"
            disabled={!orphans.length}
            onClick={() => setOrphanSelected(orphanSelected.length === orphans.length ? [] : orphans.map((i) => i.path))}
          >
            {orphanSelected.length === orphans.length && orphans.length ? '取消全选' : '全选'}
          </Button>,
          <Button
            key="delete"
            type="primary"
            danger
            loading={orphanDeleting}
            disabled={!orphanSelected.length}
            onClick={handleOrphanDelete}
          >
            删除选中（{orphanSelected.length}）
          </Button>,
        ]}
      >
        <Text type="secondary" style={{ fontSize: 12 }}>
          以下文件无任何素材记录与引用（删除剧本/重新生成后残留的文件），合计 {formatBytes(orphanTotalSize)}。
          上传不足 1 小时的文件不在此列（生图任务可能正在使用）。
        </Text>
        <Table
          style={{ marginTop: 12 }}
          rowKey="path"
          size="small"
          columns={orphanColumns}
          dataSource={orphans}
          loading={orphanLoading}
          pagination={false}
          scroll={{ y: 360 }}
          rowSelection={{
            selectedRowKeys: orphanSelected,
            onChange: (keys) => setOrphanSelected(keys as string[]),
          }}
          locale={{ emptyText: orphanLoading ? '扫描中…' : '没有孤儿文件 🎉' }}
        />
      </Modal>
    </div>
  )
}

export default MaterialsPage
