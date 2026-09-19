/**
 * 步骤 3（索引2）：分镜管理
 * 左侧分镜列表 + 右侧选中分镜详情（布局参照剧本工作流「分集设计」）。
 * 详情含：分镜大纲展示、分镜配置（分镜形式下拉框；全能参考模式时出现 overlap 滑块、
 * 参考素材图编辑区，且「分镜提示词生成」可用）、已生成提示词展示；
 * 每个分镜独立「完成当前分镜配置」按钮（≥1 个完成即可进入第 4 步勾选生成视频）。
 */
import React, { useMemo, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Empty,
  Image,
  Input,
  Modal,
  Popconfirm,
  Select,
  Slider,
  Space,
  Spin,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd'
import {
  CheckCircleOutlined,
  CopyOutlined,
  DeleteOutlined,
  FileTextOutlined,
  PictureOutlined,
  PlusOutlined,
  SwapOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import type { AgentEvent, SessionDetail, SegmentReferenceImage, StoryboardSegment } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { AgentRunProgress } from '@/components/script/AgentRunProgress'
import { MaterialPickerModal } from './material/MaterialPickerModal'
import { MaterialGenerateModal } from './material/MaterialGenerateModal'
import { imageSrc } from '@/utils/imageSrc'

const { Text, Paragraph } = Typography
const { TextArea } = Input

// 分镜形式（仅全能参考模式实现 overlap 与提示词生成逻辑）
const MODE_OPTIONS = [
  { value: 'first_frame', label: '首帧模式（暂未实现关联逻辑）' },
  { value: 'last_frame', label: '尾帧模式（暂未实现关联逻辑）' },
  { value: 'all_reference', label: '全能参考模式' },
  { value: 'first_last_frame', label: '首尾帧模式（暂未实现关联逻辑）' },
]

const MODE_TAG: Record<string, { color: string; text: string }> = {
  first_frame: { color: 'geekblue', text: '首帧' },
  last_frame: { color: 'purple', text: '尾帧' },
  all_reference: { color: 'gold', text: '全能参考' },
  first_last_frame: { color: 'cyan', text: '首尾帧' },
}

interface StepSegmentManagementProps {
  session: SessionDetail
}

// 提示词生成弹窗的上下文预览类型（后端 build_prompt_context 产出）
interface PromptContextView {
  story_outline: string
  episode_context: string
  segment: StoryboardSegment
  prev_segment: StoryboardSegment | null
  reference_images?: SegmentReferenceImage[]
  overlap: number
  effective_overlap: number
  overlap_rule: string
}

export const StepSegmentManagement: React.FC<StepSegmentManagementProps> = ({ session }) => {
  const { refreshSession } = useSessionStore()
  const outlineData = session.step_results?.storyboard_outline?.result_data
  const segments: StoryboardSegment[] = useMemo(() => outlineData?.segments || [], [outlineData])
  const canExecute = session.completed_steps?.includes('storyboard_outline')
  const configuredCount = segments.filter((s) => s.configured).length

  const [selectedIndex, setSelectedIndex] = useState(0)
  const [configLoading, setConfigLoading] = useState(false)
  const [completing, setCompleting] = useState(false)
  // 参考素材图编辑
  const [refsSaving, setRefsSaving] = useState(false)
  const [descDrafts, setDescDrafts] = useState<Record<string, string>>({}) // image_id → 描述草稿（onBlur 保存）
  const [picker, setPicker] = useState<{ open: boolean; replaceIndex: number | null }>({ open: false, replaceIndex: null })
  const [genOpen, setGenOpen] = useState(false)
  // 提示词生成弹窗
  const [promptModal, setPromptModal] = useState<{
    open: boolean
    context: PromptContextView | null
    loading: boolean
    run: { id: string; active: boolean } | null
  }>({ open: false, context: null, loading: false, run: null })

  const selected = useMemo(
    () => segments.find((s) => s.index === selectedIndex) || segments[0],
    [segments, selectedIndex]
  )

  if (!canExecute) {
    return (
      <Card title="分镜管理" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 2 步：生成分镜大纲</Text>
      </Card>
    )
  }

  if (!segments.length) {
    return (
      <Card title="分镜管理" style={{ marginTop: 16 }}>
        <Empty description="分镜列表为空，请回到第 2 步重新生成分镜大纲" />
      </Card>
    )
  }

  const updateConfig = async (index: number, config: { mode?: string; overlap?: number }) => {
    setConfigLoading(true)
    try {
      await stepApi.updateSegmentConfig(session.session_id, index, config)
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setConfigLoading(false)
    }
  }

  const saveReferenceImages = async (items: SegmentReferenceImage[]) => {
    if (!selected) return
    setRefsSaving(true)
    try {
      await stepApi.updateSegmentReferenceImages(
        session.session_id,
        selected.index,
        items.map((r) => ({ image_id: r.image_id, description: r.description }))
      )
      setDescDrafts({})
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setRefsSaving(false)
    }
  }

  const handlePickerConfirm = (picked: { image_id: string; image_path: string; description: string }[]) => {
    if (!selected) return
    const current = selected.reference_images || []
    if (picker.replaceIndex !== null) {
      // 更换单张：描述重置为新素材的库内默认
      const next = [...current]
      next[picker.replaceIndex] = {
        image_id: picked[0].image_id,
        image_path: picked[0].image_path,
        description: picked[0].description,
      }
      saveReferenceImages(next)
    } else {
      // 追加（去重），描述带出库内默认
      const existing = new Set(current.map((r) => r.image_id))
      const additions = picked
        .filter((p) => !existing.has(p.image_id))
        .map((p) => ({ image_id: p.image_id, image_path: p.image_path, description: p.description }))
      saveReferenceImages([...current, ...additions])
    }
  }

  const removeReferenceImage = (imageId: string) => {
    if (!selected) return
    saveReferenceImages((selected.reference_images || []).filter((r) => r.image_id !== imageId))
  }

  const commitDescDraft = (imageId: string) => {
    if (!selected) return
    const draft = descDrafts[imageId]
    if (draft === undefined) return
    const item = (selected.reference_images || []).find((r) => r.image_id === imageId)
    if (!item || draft === item.description) return
    saveReferenceImages(
      (selected.reference_images || []).map((r) => (r.image_id === imageId ? { ...r, description: draft } : r))
    )
  }

  const openPromptModal = async () => {
    if (!selected) return
    setPromptModal({ open: true, context: null, loading: true, run: null })
    try {
      const ctx = await stepApi.getSegmentPromptContext(session.session_id, selected.index)
      setPromptModal({ open: true, context: ctx as PromptContextView, loading: false, run: null })
    } catch (e) {
      message.error((e as Error).message)
      setPromptModal({ open: false, context: null, loading: false, run: null })
    }
  }

  const confirmGeneratePrompt = async () => {
    if (!selected) return
    try {
      const runId = await stepApi.generateSegmentPrompt(session.session_id, selected.index)
      setPromptModal((m) => ({ ...m, run: { id: runId, active: true } }))
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const handlePromptRunDone = async (ev: AgentEvent) => {
    setPromptModal((m) => (m.run ? { ...m, run: { ...m.run, active: false } } : m))
    if (ev.success) {
      message.success('分镜提示词已生成')
      setPromptModal({ open: false, context: null, loading: false, run: null })
      await refreshSession()
    } else {
      message.error(ev.error || '分镜提示词生成失败')
    }
  }

  const completeSegment = async (index: number, completed: boolean) => {
    setCompleting(true)
    try {
      await stepApi.completeSegment(session.session_id, index, completed)
      message.success(completed ? `分镜 ${index + 1} 配置已完成，可进入第 4 步勾选生成视频` : '分镜配置已取消完成')
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setCompleting(false)
    }
  }

  const copyPrompt = async () => {
    if (!selected?.prompt) return
    try {
      await navigator.clipboard.writeText(selected.prompt)
      message.success('提示词已复制')
    } catch {
      message.error('复制失败，请手动选择复制')
    }
  }

  const modeTag = selected ? MODE_TAG[selected.mode] : undefined

  const promptModalNode = (
    <Modal
      title={`生成分镜提示词 - 分镜 ${(selected?.index ?? 0) + 1}${selected?.title ? `《${selected.title}》` : ''}`}
      open={promptModal.open}
      onCancel={() => {
        if (promptModal.run?.active) return // 生成中不允许关闭
        setPromptModal({ open: false, context: null, loading: false, run: null })
      }}
      footer={
        promptModal.run
          ? null
          : [
              <Button key="cancel" onClick={() => setPromptModal({ open: false, context: null, loading: false, run: null })}>
                取消
              </Button>,
              <Button key="ok" type="primary" icon={<ThunderboltOutlined />} onClick={confirmGeneratePrompt}>
                确定（调用 video-prompt skill 生成）
              </Button>,
            ]
      }
      width={720}
      destroyOnHidden
    >
      <Spin spinning={promptModal.loading}>
        {promptModal.context && (
          <div style={{ maxHeight: 480, overflowY: 'auto' }}>
            <ContextBlock title="剧本大纲（全剧 story_outline）" content={promptModal.context.story_outline || '（无）'} />
            <ContextBlock title="本集脚本（分集设计）" content={promptModal.context.episode_context} />
            <ContextBlock
              title="当前分镜内容"
              content={`【${promptModal.context.segment.title || `分镜 ${promptModal.context.segment.index + 1}`}】${promptModal.context.segment.outline}`}
            />
            {(promptModal.context.reference_images?.length ?? 0) > 0 && (
              <ContextBlock
                title={`本分镜参考素材图（${promptModal.context.reference_images!.length} 张）`}
                content={promptModal
                  .context!.reference_images!.map((r) => `· ${r.image_id}《${r.description || '（无描述）'}》`)
                  .join('\n')}
              />
            )}
            <Card size="small" style={{ marginBottom: 12, background: '#f6ffed', borderColor: '#b7eb8f' }}>
              <Text strong style={{ fontSize: 13 }}>overlap 衔接信息</Text>
              <Paragraph style={{ marginBottom: 0, marginTop: 4, fontSize: 13 }}>
                当前 overlap = {promptModal.context.overlap} 秒；{promptModal.context.overlap_rule}
              </Paragraph>
            </Card>
          </div>
        )}
      </Spin>
      {promptModal.run && (
        <div style={{ marginTop: 8 }}>
          <AgentRunProgress runId={promptModal.run.id} onDone={handlePromptRunDone} />
        </div>
      )}
    </Modal>
  )

  return (
    <>
      <Card
        title={
          <span>
            分镜管理
            <Text type="secondary" style={{ marginLeft: 12, fontSize: 13, fontWeight: 'normal' }}>
              共 {segments.length} 个分镜 · 已完成配置 {configuredCount} 个 · 已生成提示词{' '}
              {segments.filter((s) => s.prompt).length} 个
            </Text>
          </span>
        }
        style={{ marginTop: 16 }}
        extra={
          configuredCount > 0 ? (
            <Tag icon={<CheckCircleOutlined />} color="success">
              {configuredCount}/{segments.length} 已配置
            </Tag>
          ) : undefined
        }
      >
        <div style={{ display: 'flex', gap: 16, alignItems: 'stretch' }}>
          {/* 左侧：分镜列表 */}
          <div style={{ width: 260, flexShrink: 0, borderRight: '1px solid #f0f0f0', paddingRight: 8 }}>
            {segments.map((seg) => {
              const tag = MODE_TAG[seg.mode]
              const active = selected?.index === seg.index
              return (
                <Card
                  key={seg.index}
                  size="small"
                  hoverable
                  onClick={() => {
                    setSelectedIndex(seg.index)
                    setDescDrafts({})
                  }}
                  style={{
                    marginBottom: 8,
                    ...(active
                      ? { borderColor: '#1677ff', background: '#e6f4ff' }
                      : {}),
                  }}
                >
                  <Space size={6} wrap>
                    <Tag color="blue">分镜 {seg.index + 1}</Tag>
                    {tag && <Tag color={tag.color}>{tag.text}</Tag>}
                    {seg.configured && <Tag color="success">已配置</Tag>}
                    {seg.prompt && <Tag color="green">已生成提示词</Tag>}
                  </Space>
                  <div
                    style={{
                      marginTop: 4,
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                      fontSize: 13,
                      fontWeight: active ? 600 : 'normal',
                    }}
                  >
                    {seg.title || seg.outline?.substring(0, 30) || `分镜 ${seg.index + 1}`}
                    {seg.duration ? (
                      <span style={{ color: 'rgba(0,0,0,0.45)', fontWeight: 'normal' }}> · {seg.duration}s</span>
                    ) : null}
                  </div>
                </Card>
              )
            })}
          </div>

          {/* 右侧：选中分镜详情 */}
          <div style={{ flex: 1, minWidth: 0 }}>
            {selected && (
              <>
                {/* 分镜大纲 */}
                <Card
                  size="small"
                  title={
                    <Space size={8}>
                      <FileTextOutlined />
                      <span>分镜大纲</span>
                      {modeTag && <Tag color={modeTag.color}>{modeTag.text}模式</Tag>}
                    </Space>
                  }
                >
                  <Paragraph
                    style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }}
                    ellipsis={{ rows: 6, expandable: true, symbol: '展开' }}
                  >
                    <Text strong>{selected.title && `【${selected.title}】`}</Text>
                    {selected.outline || '（无大纲）'}
                  </Paragraph>
                </Card>

                {/* 分镜配置 */}
                <Card
                  size="small"
                  title="分镜配置"
                  style={{ marginTop: 12 }}
                  extra={
                    selected.configured ? (
                      <Popconfirm
                        title="取消完成该分镜的配置？"
                        onConfirm={() => completeSegment(selected.index, false)}
                      >
                        <Button size="small" icon={<CheckCircleOutlined />} loading={completing}>
                          已完成配置（点击取消）
                        </Button>
                      </Popconfirm>
                    ) : (
                      <Button
                        size="small"
                        type="primary"
                        icon={<CheckCircleOutlined />}
                        loading={completing}
                        onClick={() => completeSegment(selected.index, true)}
                      >
                        完成当前分镜配置
                      </Button>
                    )
                  }
                >
                  <Spin spinning={configLoading}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
                      <Text style={{ flexShrink: 0 }}>分镜形式</Text>
                      <Select
                        value={selected.mode}
                        options={MODE_OPTIONS}
                        onChange={(mode) => updateConfig(selected.index, { mode })}
                        style={{ width: 280 }}
                      />
                    </div>

                    {selected.mode === 'all_reference' && (
                      <div style={{ marginTop: 16, padding: '4px 0' }}>
                        <div style={{ marginBottom: 4 }}>
                          <Text type="secondary">
                            与上一分镜的 overlap（重叠秒数，将转化为提示词衔接规则：0 = 不承接；1~3 = 承接上一分镜）
                          </Text>
                        </div>
                        <Slider
                          min={0}
                          max={3}
                          step={1}
                          value={selected.overlap ?? 1}
                          marks={{ 0: '0s', 1: '1s', 2: '2s', 3: '3s' }}
                          disabled={selected.index === 0}
                          onChange={(v) => updateConfig(selected.index, { overlap: v })}
                        />
                        {selected.index === 0 && (
                          <Text type="secondary" style={{ fontSize: 12 }}>
                            首个分镜无上一分镜，不承接
                          </Text>
                        )}
                      </div>
                    )}
                  </Spin>
                </Card>

                {/* 参考素材图（仅全能参考模式） */}
                {selected.mode === 'all_reference' && (
                  <Card
                    size="small"
                    title={
                      <Space size={8}>
                        <PictureOutlined />
                        <span>参考素材图</span>
                        <Text type="secondary" style={{ fontSize: 12, fontWeight: 'normal' }}>
                          生成视频与提示词时的全能参考（{selected.reference_images?.length || 0} 张）
                        </Text>
                      </Space>
                    }
                    style={{ marginTop: 12 }}
                    extra={
                      <Space size={8}>
                        <Button
                          size="small"
                          icon={<PlusOutlined />}
                          loading={refsSaving}
                          onClick={() => setPicker({ open: true, replaceIndex: null })}
                        >
                          从素材库选择
                        </Button>
                        <Button size="small" type="primary" icon={<ThunderboltOutlined />} onClick={() => setGenOpen(true)}>
                          AI 生成素材图
                        </Button>
                      </Space>
                    }
                  >
                    <Spin spinning={refsSaving}>
                      {selected.reference_images?.length ? (
                        selected.reference_images.map((r, i) => (
                          <div
                            key={r.image_id}
                            style={{
                              display: 'flex',
                              gap: 12,
                              alignItems: 'flex-start',
                              padding: '8px 0',
                              borderBottom: i < (selected.reference_images?.length || 0) - 1 ? '1px solid #f0f0f0' : 'none',
                            }}
                          >
                            <Image
                              src={imageSrc(r.image_path)}
                              alt={r.description}
                              width={64}
                              height={64}
                              style={{ objectFit: 'cover', borderRadius: 6, flexShrink: 0 }}
                              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                            />
                            <TextArea
                              value={descDrafts[r.image_id] ?? r.description}
                              autoSize={{ minRows: 1, maxRows: 3 }}
                              placeholder="对图片描述（生成提示词与视频时作为参考依据）"
                              style={{ flex: 1 }}
                              onChange={(e) => setDescDrafts((d) => ({ ...d, [r.image_id]: e.target.value }))}
                              onBlur={() => commitDescDraft(r.image_id)}
                            />
                            <Space direction="vertical" size={4}>
                              <Tooltip title="更换此张素材图">
                                <Button
                                  size="small"
                                  icon={<SwapOutlined />}
                                  onClick={() => setPicker({ open: true, replaceIndex: i })}
                                />
                              </Tooltip>
                              <Popconfirm
                                title="移除该素材图？"
                                description="仅解除本分镜的关联，不会删除素材图文件与素材库记录"
                                onConfirm={() => removeReferenceImage(r.image_id)}
                              >
                                <Button size="small" danger icon={<DeleteOutlined />} />
                              </Popconfirm>
                            </Space>
                          </div>
                        ))
                      ) : (
                        <Text type="secondary">
                          尚未关联素材图。可从素材库选择（定妆照/本集素材/其他集素材），或用 AI 生成专属素材图。
                        </Text>
                      )}
                    </Spin>
                  </Card>
                )}

                {/* 已生成的提示词 */}
                <Card
                  size="small"
                  title="分镜提示词"
                  style={{ marginTop: 12 }}
                  extra={
                    <Space size={12}>
                      <Tooltip title="分镜大纲阶段 AI 分析的建议时长，仅作参考">
                        <Text type="secondary" style={{ fontSize: 13 }}>
                          建议时长：{selected.duration ? `${selected.duration} 秒` : '—'}
                        </Text>
                      </Tooltip>
                      <Tooltip
                        title={
                          selected.mode === 'all_reference'
                            ? '基于剧本大纲、本集脚本、当前分镜大纲与 overlap 信息，调用 video-prompt skill 生成当前分镜的提示词'
                            : '仅「全能参考模式」支持分镜提示词生成'
                        }
                      >
                        <Button
                          size="small"
                          type="primary"
                          icon={<ThunderboltOutlined />}
                          disabled={selected.mode !== 'all_reference'}
                          onClick={openPromptModal}
                        >
                          分镜提示词生成
                        </Button>
                      </Tooltip>
                      {selected.prompt && (
                        <Button size="small" icon={<CopyOutlined />} onClick={copyPrompt}>
                          复制
                        </Button>
                      )}
                    </Space>
                  }
                >
                  {selected.prompt ? (
                    <Paragraph style={{ whiteSpace: 'pre-wrap', marginBottom: 0 }} copyable={false}>
                      {selected.prompt}
                    </Paragraph>
                  ) : (
                    <Text type="secondary">
                      尚未生成。将分镜形式切换为「全能参考模式」后点击「分镜提示词生成」。
                    </Text>
                  )}
                </Card>
              </>
            )}
          </div>
        </div>

        {configuredCount === 0 && (
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 16 }}
            title="每个分镜配置完成后点击「完成当前分镜配置」；至少完成 1 个分镜即可进入第 4 步勾选生成视频。修改已完成的分镜配置会清空其提示词并回退完成状态。"
          />
        )}
      </Card>
      {promptModalNode}
      <MaterialPickerModal
        sessionId={session.session_id}
        open={picker.open}
        multi={picker.replaceIndex === null}
        segmentMaterials={selected?.reference_images || []}
        excludeImageIds={
          picker.replaceIndex === null
            ? (selected?.reference_images || []).map((r) => r.image_id)
            : (selected?.reference_images || []).filter((_, i) => i !== picker.replaceIndex).map((r) => r.image_id)
        }
        onClose={() => setPicker({ open: false, replaceIndex: null })}
        onConfirm={handlePickerConfirm}
      />
      {selected && (
        <MaterialGenerateModal
          sessionId={session.session_id}
          segmentIndex={selected.index}
          segmentTitle={selected.title}
          segmentOutline={selected.outline}
          episodeTitle={session.episode_title}
          segmentMaterials={selected.reference_images || []}
          open={genOpen}
          onClose={() => setGenOpen(false)}
          onGenerated={refreshSession}
        />
      )}
    </>
  )
}

// 弹窗内的上下文展示块（标题 + 滚动内容）
const ContextBlock: React.FC<{ title: string; content: string }> = ({ title, content }) => (
  <Card size="small" title={title} style={{ marginBottom: 12 }}>
    <div
      style={{
        maxHeight: 140,
        overflowY: 'auto',
        whiteSpace: 'pre-wrap',
        fontSize: 13,
        color: 'rgba(0,0,0,0.65)',
      }}
    >
      {content}
    </div>
  </Card>
)

export default StepSegmentManagement
