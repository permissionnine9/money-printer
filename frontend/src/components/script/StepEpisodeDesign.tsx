/**
 * 第 3 步：分集设计（左侧集时间线 + 右侧单集详情编辑；人物/场景/线索伏笔实体库 Tabs）
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Button, Card, Empty, Input, Modal, Select, Space, Spin, Tabs, Tag, Typography, message } from 'antd'
import {
  CheckCircleOutlined,
  DeleteOutlined,
  DownloadOutlined,
  EditOutlined,
  ExclamationCircleOutlined,
  PlusOutlined,
  RedoOutlined,
  SaveOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import MarkdownIt from 'markdown-it'
import type {
  AgentEvent,
  EntityRef,
  EntityReferences,
  Episode,
  ScriptEntity,
  ScriptSessionDetail,
} from '@/types'
import { entityApi, scriptStepApi } from '@/api/client'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import { usePolling } from '@/hooks/usePolling'
import { ACTION_LABEL, buildScriptMarkdown, downloadTextFile, extractScriptTitle } from '@/utils/scriptMarkdown'
import { AgentRunProgress } from './AgentRunProgress'
import { imageSrc } from '@/utils/imageSrc'

const { Text } = Typography
const { TextArea } = Input

interface StepEpisodeDesignProps {
  session: ScriptSessionDetail
}

const ACTION_OPTIONS = (Object.keys(ACTION_LABEL) as EntityRef['action'][]).map((a) => ({
  value: a,
  label: ACTION_LABEL[a],
}))

// markdown 渲染（html:false —— 仅自家 agent 产出的 markdown，转义由 markdown-it 默认处理）
const md = new MarkdownIt({ html: false, breaks: true })

// 文档区排版样式（贴合 antd Typography 视觉）
const DOC_STYLE = `
.episode-doc { font-size: 14px; color: rgba(0,0,0,0.88); line-height: 1.7; }
.episode-doc h1 { font-size: 18px; font-weight: 600; margin: 0 0 4px; }
.episode-doc h2 { font-size: 15px; font-weight: 600; margin: 20px 0 8px; padding-bottom: 4px; border-bottom: 1px solid #f0f0f0; }
.episode-doc p { margin: 0 0 8px; }
.episode-doc ul, .episode-doc ol { margin: 0 0 8px; padding-left: 20px; }
.episode-doc li { margin-bottom: 2px; }
.episode-doc blockquote { margin: 8px 0; padding: 4px 12px; border-left: 3px solid #d9d9d9; color: rgba(0,0,0,0.45); background: #fafafa; }
.episode-doc strong { font-weight: 600; }
.episode-doc code { padding: 1px 4px; background: #f5f5f5; border-radius: 4px; font-size: 13px; }
`

// 图片路径 → 可访问 src（后端相对路径补 / 前缀）

type EpisodeDraft = Pick<
  Episode,
  | 'title'
  | 'logline'
  | 'story_progress'
  | 'conflict_chain'
  | 'causality_chain'
  | 'ending_summary'
  | 'character_ids'
  | 'scene_ids'
  | 'clue_refs'
  | 'foreshadow_refs'
>

const EMPTY_DRAFT: EpisodeDraft = {
  title: '',
  logline: '',
  story_progress: '',
  conflict_chain: '',
  causality_chain: '',
  ending_summary: '',
  character_ids: [],
  scene_ids: [],
  clue_refs: [],
  foreshadow_refs: [],
}

// 文档 section 定义：字段 key → 中文标题
type SectionKey = 'logline' | 'story_progress' | 'conflict_chain' | 'causality_chain' | 'ending_summary'

const SECTIONS: { key: SectionKey; title: string }[] = [
  { key: 'logline', title: '梗概 Logline' },
  { key: 'story_progress', title: '节点进展' },
  { key: 'conflict_chain', title: '矛盾链' },
  { key: 'causality_chain', title: '因果衔接' },
  { key: 'ending_summary', title: '集尾局面' },
]

export const StepEpisodeDesign: React.FC<StepEpisodeDesignProps> = ({ session }) => {
  const { refreshSession } = useScriptSessionStore()
  const canExecute = session.completed_steps?.includes('story_outline')
  const isCompleted = session.completed_steps?.includes('episode_design')

  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [entities, setEntities] = useState<ScriptEntity[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [tab, setTab] = useState('episodes')
  const [draft, setDraft] = useState<EpisodeDraft>(EMPTY_DRAFT)
  const [editing, setEditing] = useState(false)
  const [saving, setSaving] = useState(false)
  const [run, setRun] = useState<{ id: string; active: boolean } | null>(null)
  const [regenEpisodeId, setRegenEpisodeId] = useState('')
  const [genModal, setGenModal] = useState<{ open: boolean; episodeId: string; extra: string }>({
    open: false,
    episodeId: '',
    extra: '',
  })

  const [expandedId, setExpandedId] = useState('')
  const [detailId, setDetailId] = useState('')
  const [entityRefs, setEntityRefs] = useState<Record<string, EntityReferences>>({})
  const [refsLoading, setRefsLoading] = useState<Record<string, boolean>>({})

  const loadEpisodes = useCallback(async () => {
    try {
      const list = await scriptStepApi.listEpisodes(session.session_id)
      setEpisodes(list || [])
    } catch {
      // 静默失败（生成期间轮询）
    }
  }, [session.session_id])

  const loadEntities = useCallback(async () => {
    try {
      const list = await entityApi.list(session.session_id)
      setEntities(list || [])
    } catch {
      // 静默失败
    }
  }, [session.session_id])

  useEffect(() => {
    void loadEpisodes()
    void loadEntities()
  }, [loadEpisodes, loadEntities])

  // 实体引用集：点击实体卡/Tag 时加载（hook 必须位于 early return 之前，避免切换会话时 hooks 数量变化）
  const loadReferences = useCallback(
    async (entityId: string) => {
      setRefsLoading((s) => ({ ...s, [entityId]: true }))
      try {
        const refs = await entityApi.getReferences(session.session_id, entityId)
        setEntityRefs((s) => ({ ...s, [entityId]: refs }))
      } catch {
        // 静默失败（接口未就绪时不阻塞卡片）
      } finally {
        setRefsLoading((s) => ({ ...s, [entityId]: false }))
      }
    },
    [session.session_id]
  )

  // 生成期间 2s 轮询（agent 工具增量落库，时间线逐集点亮）
  usePolling(
    () => {
      void loadEpisodes()
      void loadEntities()
    },
    { interval: 2000, enabled: !!run?.active }
  )

  // 默认选中第一集
  useEffect(() => {
    if (episodes.length && !episodes.some((e) => e.episode_id === selectedId)) {
      setSelectedId(episodes[0].episode_id)
    }
  }, [episodes, selectedId])

  const selected = episodes.find((e) => e.episode_id === selectedId)

  // 选中集变化（或被单集重设计覆写）时还原编辑草稿并退出编辑态
  useEffect(() => {
    if (selected) {
      setDraft({
        title: selected.title || '',
        logline: selected.logline || '',
        story_progress: selected.story_progress || '',
        conflict_chain: selected.conflict_chain || '',
        causality_chain: selected.causality_chain || '',
        ending_summary: selected.ending_summary || '',
        character_ids: [...(selected.character_ids || [])],
        scene_ids: [...(selected.scene_ids || [])],
        clue_refs: (selected.clue_refs || []).map((r) => ({ ...r })),
        foreshadow_refs: (selected.foreshadow_refs || []).map((r) => ({ ...r })),
      })
    }
    setEditing(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, selected?.updated_at])

  const entityName = (id: string) => entities.find((e) => e.entity_id === id)?.name || ''

  // 点击实体 Tag：弹窗展示实体详情（不打断分集浏览）
  const openEntityDetail = (entityId: string) => {
    const ent = entities.find((e) => e.entity_id === entityId)
    if (!ent) {
      message.warning(`实体 ${entityId} 不在实体库中`)
      return
    }
    setDetailId(entityId)
    if (!entityRefs[entityId] && !refsLoading[entityId]) {
      void loadReferences(entityId)
    }
  }

  const openGenerate = (episodeId = '') => setGenModal({ open: true, episodeId, extra: '' })

  // 下载完整剧本（大纲 + 逐集正文，Markdown）
  const handleDownloadScript = () => {
    const outline: string = session.step_results?.story_outline?.result_data?.mindmap || ''
    const content = buildScriptMarkdown(episodes, entities, outline)
    downloadTextFile(`${extractScriptTitle(outline)} 完整剧本.md`, content)
  }

  const executeGenerate = async (episodeId: string, extra: string) => {
    setGenModal((m) => ({ ...m, open: false }))
    try {
      const runId = episodeId
        ? await scriptStepApi.regenerateEpisode(session.session_id, episodeId, extra)
        : await scriptStepApi.generateEpisodes(session.session_id, extra)
      setRegenEpisodeId(episodeId)
      setRun({ id: runId, active: true })
    } catch (e) {
      message.error((e as Error).message)
    }
  }

  const handleGenOk = () => {
    const { episodeId, extra } = genModal
    if (!episodeId && episodes.length > 0) {
      Modal.confirm({
        title: '确认重新生成分集设计？',
        icon: <ExclamationCircleOutlined />,
        content: '将清空现有全部分集、实体与定妆照数据，此操作不可撤销。是否继续？',
        onOk: () => executeGenerate('', extra),
      })
    } else {
      void executeGenerate(episodeId, extra)
    }
  }

  const handleRunDone = async (ev: AgentEvent) => {
    setRun((r) => (r ? { ...r, active: false } : r))
    if (ev.success) {
      message.success(regenEpisodeId ? `${regenEpisodeId} 重新设计完成` : '分集设计生成完成')
      await refreshSession()
    } else {
      message.error(ev.error || '分集设计运行失败')
    }
    await loadEpisodes()
    await loadEntities()
  }

  const saveDraft = async () => {
    if (!selected) return
    // 线索/伏笔 action 枚举校验
    for (const [label, refs] of [
      ['线索', draft.clue_refs],
      ['伏笔', draft.foreshadow_refs],
    ] as const) {
      const bad = refs.find(
        (r) => !r.entity_id || !['plant', 'develop', 'reveal', 'payoff'].includes(r.action)
      )
      if (bad) {
        message.warning(`${label} ${bad.entity_id || '（未选择实体）'} 的动作无效，请选择 埋设/发展/揭示/兑现`)
        return
      }
    }
    setSaving(true)
    try {
      await scriptStepApi.updateEpisode(session.session_id, selected.episode_id, draft)
      message.success(`${selected.episode_id} 已保存`)
      setEditing(false)
      await loadEpisodes()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!canExecute) {
    return (
      <Card title="分集设计" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 2 步：故事大纲</Text>
      </Card>
    )
  }

  // ==================== 实体库 ====================

  const characters = entities.filter((e) => e.entity_type === 'character')
  const scenes = entities.filter((e) => e.entity_type === 'scene')
  const refEntities = entities.filter(
    (e) => e.entity_type === 'clue' || e.entity_type === 'foreshadow'
  )

  const toggleExpand = (entityId: string) => {
    setExpandedId((cur) => {
      const next = cur === entityId ? '' : entityId
      if (next && !entityRefs[entityId] && !refsLoading[entityId]) {
        void loadReferences(entityId)
      }
      return next
    })
  }

  // 引用集渲染：线索/伏笔按集排序展示 plant→payoff 时间线，人物/场景展示分集列表
  const renderEntityRefs = (e: ScriptEntity) => {
    const refs = entityRefs[e.entity_id]
    const isRefEntity = e.entity_type === 'clue' || e.entity_type === 'foreshadow'
    if (refsLoading[e.entity_id]) {
      return (
        <Space>
          <Spin size="small" />
          <Text type="secondary" style={{ fontSize: 12 }}>
            加载中…
          </Text>
        </Space>
      )
    }
    if (refs && refs.episodes.length > 0) {
      return isRefEntity ? (
        <div>
          {[...refs.episodes]
            .sort((a, b) => a.episode_id.localeCompare(b.episode_id))
            .map((ep) => (
              <div key={ep.episode_id} style={{ display: 'flex', gap: 4, alignItems: 'center', marginBottom: 4 }}>
                <Text style={{ fontSize: 12, flexShrink: 0 }}>{ep.episode_id}</Text>
                <div style={{ width: 1, height: 12, background: '#d9d9d9' }} />
                {ep.actions.map((a) => (
                  <Tag
                    key={a}
                    style={{ marginRight: 0, fontSize: 11 }}
                    color={a === 'payoff' ? 'green' : a === 'plant' ? 'orange' : 'blue'}
                  >
                    {ACTION_LABEL[a as EntityRef['action']] || a}
                  </Tag>
                ))}
              </div>
            ))}
        </div>
      ) : (
        refs.episodes.map((ep) => (
          <div key={ep.episode_id} style={{ marginBottom: 4 }}>
            <Tag style={{ marginRight: 4, fontSize: 11 }}>{ep.episode_id}</Tag>
            <Text style={{ fontSize: 12 }}>{ep.title}</Text>
          </div>
        ))
      )
    }
    return (
      <Text type="secondary" style={{ fontSize: 12 }}>
        暂无分集引用
      </Text>
    )
  }

  const renderEntityCard = (e: ScriptEntity) => {
    const expanded = expandedId === e.entity_id
    const metaEntries = Object.entries(e.meta || {}).filter(
      ([, v]) => v != null && v !== '' && typeof v !== 'object'
    )
    return (
      <div key={e.entity_id} style={{ width: 220 }}>
        <Card
          size="small"
          style={{ border: '1px solid #f0f0f0', cursor: 'pointer' }}
          styles={{ body: { padding: 8 } }}
          onClick={() => toggleExpand(e.entity_id)}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4, marginBottom: 6 }}>
            <Text strong ellipsis style={{ maxWidth: 130 }}>
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
          <div style={{ fontSize: 12, color: '#888', marginTop: 6, maxHeight: expanded ? undefined : 48, overflow: 'hidden' }}>
            {e.description}
          </div>

          {expanded && (
            <div style={{ marginTop: 8, borderTop: '1px solid #f0f0f0', paddingTop: 8 }} onClick={(ev) => ev.stopPropagation()}>
              {metaEntries.length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  {metaEntries.map(([k, v]) => (
                    <div key={k} style={{ fontSize: 12, lineHeight: 1.6 }}>
                      <Text type="secondary">{k}：</Text>
                      <Text style={{ fontSize: 12 }}>{String(v)}</Text>
                    </div>
                  ))}
                </div>
              )}
              <Text type="secondary" style={{ fontSize: 12 }}>
                引用集
              </Text>
              <div style={{ marginTop: 4 }}>{renderEntityRefs(e)}</div>
            </div>
          )}
        </Card>
      </div>
    )
  }

  const entityPanel = (list: ScriptEntity[]) =>
    list.length ? (
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginTop: 8 }}>
        {list.map(renderEntityCard)}
      </div>
    ) : (
      <Empty description="暂无实体" style={{ marginTop: 48 }} />
    )

  // ==================== 单集详情 ====================

  const entityTag = (id: string, suffix?: string) => (
    <Tag key={`${id}-${suffix || ''}`} color="blue" style={{ cursor: 'pointer' }} onClick={() => openEntityDetail(id)}>
      {id} {entityName(id)}
      {suffix ? ` · ${suffix}` : ''}
    </Tag>
  )

  // 文档视图 section（空字段不渲染）
  const docSection = (title: string, content: string) =>
    content.trim() ? (
      <div key={title}>
        <h2>{title}</h2>
        <div dangerouslySetInnerHTML={{ __html: md.render(content) }} />
      </div>
    ) : null

  const refSection = (label: string, children: React.ReactNode) =>
    Array.isArray(children) && children.length > 0 ? (
      <div key={label}>
        <h2>{label}</h2>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>{children}</div>
      </div>
    ) : null

  const docView = (
    <div className="episode-doc">
      <style>{DOC_STYLE}</style>
      <h1>
        {selected?.episode_id} {selected?.title}
      </h1>
      {SECTIONS.map((s) => docSection(s.title, selected?.[s.key] || ''))}
      {refSection('出场人物', selected?.character_ids.map((id) => entityTag(id)))}
      {refSection('出场场景', selected?.scene_ids.map((id) => entityTag(id)))}
      {refSection('线索', selected?.clue_refs.map((r) => entityTag(r.entity_id, ACTION_LABEL[r.action])))}
      {refSection('伏笔', selected?.foreshadow_refs.map((r) => entityTag(r.entity_id, ACTION_LABEL[r.action])))}
    </div>
  )

  // ==================== 编辑表单（文档感分节） ====================

  const entityOptions = (type: 'character' | 'scene') =>
    entities
      .filter((e) => e.entity_type === type)
      .map((e) => ({ value: e.entity_id, label: `${e.entity_id} ${e.name}` }))

  const refEntityOptions = entities
    .filter((e) => e.entity_type === 'clue' || e.entity_type === 'foreshadow')
    .map((e) => ({ value: e.entity_id, label: `${e.entity_id} ${e.name}` }))

  const editSection = (
    title: string,
    key: SectionKey,
    rows: number
  ) => (
    <div key={key} style={{ marginTop: 16 }}>
      <Text strong>{title}</Text>
      <TextArea
        rows={rows}
        value={draft[key]}
        onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
        style={{ marginTop: 4 }}
      />
    </div>
  )

  // 线索/伏笔 refs 编辑行：实体 Select + 动作 Select + 删除
  const refRows = (
    label: string,
    key: 'clue_refs' | 'foreshadow_refs',
    options: { value: string; label: string }[]
  ) => (
    <div key={key} style={{ marginTop: 16 }}>
      <Text strong>{label}</Text>
      {draft[key].map((r, i) => (
        <div key={i} style={{ display: 'flex', gap: 4, marginTop: 4 }}>
          <Select
            showSearch
            optionFilterProp="label"
            placeholder="选择实体"
            value={r.entity_id || undefined}
            options={options}
            onChange={(v) =>
              setDraft((d) => {
                const list = [...d[key]]
                list[i] = { ...list[i], entity_id: v }
                return { ...d, [key]: list }
              })
            }
            style={{ flex: 1, minWidth: 0 }}
          />
          <Select
            placeholder="动作"
            value={r.action || undefined}
            options={ACTION_OPTIONS}
            onChange={(v: EntityRef['action']) =>
              setDraft((d) => {
                const list = [...d[key]]
                list[i] = { ...list[i], action: v }
                return { ...d, [key]: list }
              })
            }
            style={{ width: 100 }}
          />
          <Button
            icon={<DeleteOutlined />}
            onClick={() =>
              setDraft((d) => ({ ...d, [key]: d[key].filter((_, j) => j !== i) }))
            }
          />
        </div>
      ))}
      <Button
        size="small"
        type="dashed"
        icon={<PlusOutlined />}
        style={{ marginTop: 4 }}
        onClick={() => setDraft((d) => ({ ...d, [key]: [...d[key], { entity_id: '', action: 'plant' }] }))}
      >
        添加
      </Button>
    </div>
  )

  const editView = (
    <div className="episode-doc">
      <style>{DOC_STYLE}</style>
      <h1>{selected?.episode_id}</h1>
      <div style={{ marginTop: 8 }}>
        <Text strong>标题</Text>
        <Input
          value={draft.title}
          onChange={(e) => setDraft((d) => ({ ...d, title: e.target.value }))}
          style={{ marginTop: 4 }}
        />
      </div>
      {editSection('梗概 Logline', 'logline', 2)}
      {editSection('节点进展', 'story_progress', 3)}
      {editSection('矛盾链', 'conflict_chain', 3)}
      {editSection('因果衔接', 'causality_chain', 3)}
      {editSection('集尾局面', 'ending_summary', 2)}
      <div style={{ marginTop: 16 }}>
        <Text strong>出场人物</Text>
        <Select
          mode="multiple"
          showSearch
          optionFilterProp="label"
          placeholder="选择出场人物"
          value={draft.character_ids}
          options={entityOptions('character')}
          onChange={(v) => setDraft((d) => ({ ...d, character_ids: v }))}
          style={{ width: '100%', marginTop: 4 }}
        />
      </div>
      <div style={{ marginTop: 16 }}>
        <Text strong>出场场景</Text>
        <Select
          mode="multiple"
          showSearch
          optionFilterProp="label"
          placeholder="选择出场场景"
          value={draft.scene_ids}
          options={entityOptions('scene')}
          onChange={(v) => setDraft((d) => ({ ...d, scene_ids: v }))}
          style={{ width: '100%', marginTop: 4 }}
        />
      </div>
      {refRows('线索', 'clue_refs', refEntityOptions)}
      {refRows('伏笔', 'foreshadow_refs', refEntityOptions)}
    </div>
  )

  const detailPanel = selected ? (
    <Card
      size="small"
      title={<Text strong>{selected.episode_id}</Text>}
      extra={
        <Space>
          {editing ? (
            <>
              <Button size="small" onClick={() => setEditing(false)}>
                取消
              </Button>
              <Button size="small" type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveDraft}>
                保存
              </Button>
            </>
          ) : (
            <Button size="small" icon={<EditOutlined />} onClick={() => setEditing(true)}>
              编辑
            </Button>
          )}
          {isCompleted && !editing && (
            <Button
              size="small"
              icon={<RedoOutlined />}
              disabled={run?.active}
              onClick={() => openGenerate(selected.episode_id)}
            >
              重新设计
            </Button>
          )}
        </Space>
      }
    >
      {editing ? editView : docView}
    </Card>
  ) : (
    <Empty description="暂无分集" style={{ marginTop: 48 }} />
  )

  // ==================== 分集设计 Tab ====================

  const episodesPanel = (
    <div>
      <Space style={{ marginBottom: 16 }}>
        <Button
          type="primary"
          icon={<ThunderboltOutlined />}
          disabled={run?.active}
          onClick={() => openGenerate('')}
        >
          {episodes.length ? '重新生成分集设计' : '生成分集设计'}
        </Button>
        <Button icon={<DownloadOutlined />} disabled={episodes.length === 0} onClick={handleDownloadScript}>
          下载完整剧本
        </Button>
        {episodes.length > 0 && <Text type="secondary">共 {episodes.length} 集</Text>}
        {isCompleted && <Tag color="success">已完成</Tag>}
      </Space>

      {run && (
        <div style={{ marginBottom: 16 }}>
          <AgentRunProgress runId={run.id} onDone={handleRunDone} />
        </div>
      )}

      {episodes.length === 0 && !run ? (
        <Empty description="尚未生成分集，点击上方按钮开始" style={{ marginTop: 48 }} />
      ) : (
        <div style={{ display: 'flex', gap: 16 }}>
          {/* 左侧集时间线 */}
          <div
            style={{
              width: 180,
              flexShrink: 0,
              borderRight: '1px solid #f0f0f0',
              paddingRight: 8,
              maxHeight: 640,
              overflow: 'auto',
            }}
          >
            {episodes.map((ep) => {
              const active = ep.episode_id === selectedId
              const regenerating = regenEpisodeId === ep.episode_id && run?.active
              return (
                <div
                  key={ep.episode_id}
                  onClick={() => setSelectedId(ep.episode_id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 10px',
                    borderRadius: 6,
                    cursor: 'pointer',
                    marginBottom: 4,
                    background: active ? '#e6f4ff' : 'transparent',
                  }}
                >
                  {regenerating ? (
                    <Spin size="small" />
                  ) : (
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: '50%',
                        background: '#52c41a',
                        display: 'inline-block',
                        flexShrink: 0,
                      }}
                    />
                  )}
                  <Text strong={active} style={{ fontSize: 13 }}>
                    {ep.episode_id}
                  </Text>
                  <Text type="secondary" ellipsis style={{ fontSize: 12, flex: 1 }}>
                    {ep.title}
                  </Text>
                </div>
              )
            })}
            {run?.active && !regenEpisodeId && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px' }}>
                <Spin size="small" />
                <Text type="secondary" style={{ fontSize: 12 }}>
                  生成中（已产出 {episodes.length} 集）…
                </Text>
              </div>
            )}
          </div>
          {/* 右侧详情 */}
          <div style={{ flex: 1, minWidth: 0 }}>{detailPanel}</div>
        </div>
      )}
    </div>
  )

  const detailEntity = entities.find((e) => e.entity_id === detailId)

  // 实体详情弹窗（分集文档中点击实体 Tag 触发）
  const entityModalNode = (
    <Modal
      open={!!detailEntity}
      onCancel={() => setDetailId('')}
      footer={null}
      width={560}
      title={
        detailEntity && (
          <Space>
            <Text strong>{detailEntity.name}</Text>
            <Tag style={{ fontSize: 11 }}>{detailEntity.entity_id}</Tag>
          </Space>
        )
      }
    >
      {detailEntity && (
        <div style={{ display: 'flex', gap: 16, maxHeight: '65vh', overflow: 'auto' }}>
          {detailEntity.lookbook_image_path ? (
            <img
              src={imageSrc(detailEntity.lookbook_image_path)}
              alt={detailEntity.name}
              style={{ width: 180, height: 240, objectFit: 'cover', borderRadius: 6, flexShrink: 0 }}
            />
          ) : (
            <div
              style={{
                width: 180,
                height: 240,
                background: '#fafafa',
                border: '1px dashed #e8e8e8',
                borderRadius: 6,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            >
              <Text type="secondary" style={{ fontSize: 12 }}>
                暂无定妆照
              </Text>
            </div>
          )}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, lineHeight: 1.7 }}>{detailEntity.description}</div>
            {Object.entries(detailEntity.meta || {})
              .filter(([, v]) => v != null && v !== '' && typeof v !== 'object')
              .map(([k, v]) => (
                <div key={k} style={{ fontSize: 12, lineHeight: 1.6, marginTop: 4 }}>
                  <Text type="secondary">{k}：</Text>
                  <Text style={{ fontSize: 12 }}>{String(v)}</Text>
                </div>
              ))}
            <div style={{ marginTop: 12, borderTop: '1px solid #f0f0f0', paddingTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                引用集
              </Text>
              <div style={{ marginTop: 4 }}>{renderEntityRefs(detailEntity)}</div>
            </div>
          </div>
        </div>
      )}
    </Modal>
  )

  const genModalNode = (
    <Modal
      title={genModal.episodeId ? `重新设计 ${genModal.episodeId}` : '生成分集设计'}
      open={genModal.open}
      onOk={handleGenOk}
      onCancel={() => setGenModal((m) => ({ ...m, open: false }))}
      okText={genModal.episodeId ? '开始重新设计' : '开始生成'}
      cancelText="取消"
      width={600}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          {genModal.episodeId
            ? '仅重新设计该集（episode_id 不变，不破坏下游引用）；可输入补充要求（可选）。'
            : 'Agent 将基于大纲注册实体并从 ep_01 起逐集保存设计；可输入补充要求（可选）。'}
        </Text>
      </div>
      <TextArea
        rows={4}
        value={genModal.extra}
        onChange={(e) => setGenModal((m) => ({ ...m, extra: e.target.value }))}
        placeholder="例如：第 2 集结尾加强悬念；女主前三集不暴露身份"
      />
    </Modal>
  )

  return (
    <Card
      title={
        <span>
          {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
          分集设计
        </span>
      }
      style={{ marginTop: 16 }}
    >
      <Tabs
        activeKey={tab}
        onChange={setTab}
        items={[
          { key: 'episodes', label: '分集设计', children: episodesPanel },
          { key: 'characters', label: `人物库 (${characters.length})`, children: entityPanel(characters) },
          { key: 'scenes', label: `场景库 (${scenes.length})`, children: entityPanel(scenes) },
          { key: 'ref', label: `线索伏笔 (${refEntities.length})`, children: entityPanel(refEntities) },
        ]}
      />
      {genModalNode}
      {entityModalNode}
    </Card>
  )
}

export default StepEpisodeDesign
