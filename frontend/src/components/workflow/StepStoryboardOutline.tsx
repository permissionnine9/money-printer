/**
 * 步骤 2（索引1）：分镜大纲
 * 以剧本分集设计为上下文生成本集分镜导图（markmap）+ 分镜列表；
 * 预览/编辑双模式与重新生成（重生成会级联清空分镜配置、提示词与视频数据）
 */
import React, { useMemo, useState } from 'react'
import { Button, Card, Input, Modal, Segmented, Select, Space, Tag, Typography, message } from 'antd'
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
import type { SessionDetail, StoryboardSegment } from '@/types'
import { stepApi } from '@/api/client'
import { MindmapView, RunTaskBanner } from '@/components/common'
import { useRunActive, useRunError, useStartRun } from '@/hooks/useRunTask'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography
const { TextArea } = Input

// 常用提示词快捷选项（分镜大纲）
const PRESET_PROMPTS = [
  '节奏更紧凑',
  '减少冗余分镜，突出冲突',
  '开场用空镜交代环境',
  '把高潮拆成 3 个分镜',
  '多用人物特写表现情绪',
  '控制每个分镜时长在 5 秒内',
  '增强画面电影感与光影氛围',
  '先抑后扬，情绪层层递进',
  '结尾留悬念钩子',
].map((t) => ({ label: t, value: t }))

// 常用提示词下拉：选中后通过 onPick 追加到输入框，自身回到占位态以便连续叠加
const PresetPromptSelect: React.FC<{ onPick: (text: string) => void }> = ({ onPick }) => {
  const [sel, setSel] = useState<string | undefined>(undefined)
  return (
    <Select
      value={sel}
      options={PRESET_PROMPTS}
      onChange={(v) => {
        if (v) onPick(v)
        setSel(undefined)
      }}
      placeholder="选择常用提示词（追加到输入框）"
      style={{ width: '200px', float: 'right', marginBottom: 8 }}
    />
  )
}

interface StepStoryboardOutlineProps {
  session: SessionDetail
}

export const StepStoryboardOutline: React.FC<StepStoryboardOutlineProps> = ({ session }) => {
  const { refreshSession } = useSessionStore()
  const outlineData = session.step_results?.storyboard_outline?.result_data
  const mindmap: string = outlineData?.mindmap || ''
  const segmentCount: number = outlineData?.segment_count || 0
  const segments: StoryboardSegment[] = useMemo(() => outlineData?.segments || [], [outlineData])

  // 拼接导图：分镜内容（outline）拼为 ### 分镜标题下的 `- ` 列表子节点；
  // withDuration 控制是否把建议时长/overlap 拼到标题行上（仅预览拼接）。
  // 预览与编辑共用，编辑保存这份文本、由后端解析同步回 mindmap 与 segments。
  // segments 与导图 ### 行按序对应
  const buildMindmap = (withDuration: boolean): string => {
    if (!mindmap || !segments.length) return mindmap
    let i = 0
    return mindmap
      .split("\n")
      .flatMap((line) => {
        if (/^###\s/.test(line) && i < segments.length) {
          const seg = segments[i++]
          let titled = line
          if (withDuration) {
            const parts = [seg.duration ? `${seg.duration}s` : ""]
            if (seg.index > 0 && seg.overlap > 0) parts.push(`overlap ${seg.overlap}s`)
            const suffix = parts.filter(Boolean).join(" · ")
            if (suffix) titled = `${line} · ${suffix}`
          }
          const outline = (seg.outline || "").replace(/\s*\n\s*/g, " ").trim()
          return outline ? [titled, `- ${outline}`] : [titled]
        }
        return [line]
      })
      .join("\n")
  }
  const previewMindmap = useMemo(() => buildMindmap(true), [mindmap, segments])
  const editableMindmap = useMemo(() => buildMindmap(false), [mindmap, segments])
  const canExecute = session.completed_steps?.includes('select_episode')
  const isCompleted = session.completed_steps?.includes('storyboard_outline')
  const hasDownstream = session.completed_steps?.some(
    (s) => s === 'segment_management' || s === 'generate_videos'
  )

  const [extraPrompt, setExtraPrompt] = useState('')
  const [viewMode, setViewMode] = useState<'preview' | 'edit'>('preview')
  const [editingMarkdown, setEditingMarkdown] = useState('')
  const [saving, setSaving] = useState(false)
  const [promptModal, setPromptModal] = useState<{ open: boolean; extraPrompt: string }>({
    open: false,
    extraPrompt: '',
  })

  // 分镜大纲生成任务在全局 store 中跟踪（跨菜单切换不丢失，按钮据此防重复触发）
  const outlineRunning = useRunActive(session.session_id, 'storyboard_outline')
  const outlineError = useRunError(session.session_id, 'storyboard_outline')
  const { starting, launch } = useStartRun(session.session_id)

  // 大纲内容变化（生成完成/保存编辑后刷新）时回到预览模式（渲染期调整，避免 effect 级联渲染）
  const [prevMindmap, setPrevMindmap] = useState(mindmap)
  if (mindmap !== prevMindmap) {
    setPrevMindmap(mindmap)
    setViewMode('preview')
  }

  // 发起生成（POST storyboard-outline/generate → run_id → 任务交给全局 AgentRunDock 跟踪）
  const executeGenerate = (prompt: string) =>
    launch({
      kind: 'storyboard_outline',
      label: '分镜大纲',
      close: () => {
        setExtraPrompt(prompt)
        setPromptModal({ open: false, extraPrompt: '' })
      },
      invoke: () => stepApi.generateStoryboardOutline(session.session_id, prompt || undefined),
    })

  // 已有大纲时重新生成需二次确认级联清空；无大纲（失败重试）直接执行
  const handleModalOk = () => {
    if (!mindmap) {
      void executeGenerate(promptModal.extraPrompt)
      return
    }
    Modal.confirm({
      title: '确认重新生成分镜大纲？',
      icon: <ExclamationCircleOutlined />,
      content: '重新生成将清空分镜配置、已生成的分镜提示词与视频数据，此操作不可撤销。是否继续？',
      onOk: () => executeGenerate(promptModal.extraPrompt),
    })
  }

  const saveEdit = async () => {
    if (!editingMarkdown.trim()) {
      message.warning('大纲内容不能为空')
      return
    }
    setSaving(true)
    try {
      await stepApi.updateStoryboardOutline(session.session_id, editingMarkdown)
      message.success('分镜大纲已保存')
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
      <Card title="分镜大纲" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成第 1 步：从剧本选集</Text>
      </Card>
    )
  }

  return (
    <>
    <Card
      title={
        <span>
          {isCompleted && <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />}
          分镜大纲
          {outlineData?.edited && (
            <Tag color="blue" style={{ marginLeft: 12 }}>
              已人工修改
            </Tag>
          )}
          {segmentCount > 0 && (
            <Tag style={{ marginLeft: 8 }}>{segmentCount} 个分镜</Tag>
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
                if (mode === 'edit') setEditingMarkdown(editableMindmap)
                setViewMode(mode)
              }}
              options={[
                { value: 'preview', icon: <EyeOutlined />, label: '导图预览' },
                { value: 'edit', icon: <EditFilled />, label: '编辑' },
              ]}
            />
            <Button
              icon={<RedoOutlined />}
              disabled={outlineRunning || starting}
              onClick={() => setPromptModal({ open: true, extraPrompt })}
            >
              重新生成
            </Button>
          </Space>
        ) : undefined
      }
    >
      {!mindmap && (
        <Text type="secondary">
          基于第 1 步选定的剧本分集生成本集分镜大纲（思维导图 + 分镜列表），生成后可人工编辑导图；
          下一步「分镜管理」将基于导图中产出的分镜列表进行配置。
        </Text>
      )}

      {(outlineRunning || outlineError) && (
        <RunTaskBanner
          active={outlineRunning}
          error={outlineError}
          activeText={mindmap ? '正在重新生成分镜大纲，完成后将替换当前大纲' : '分镜大纲生成中'}
        />
      )}

      {!mindmap && (
        <div style={{ marginTop: 16, maxWidth: 640 }}>
          <div style={{ marginBottom: 4 }}>
            <Text type="secondary">补充要求（可选）</Text>
          </div>
          <PresetPromptSelect onPick={(t) => setExtraPrompt((p) => (p ? `${p}；${t}` : t))} />
          <TextArea
            rows={3}
            value={extraPrompt}
            onChange={(e) => setExtraPrompt(e.target.value)}
            placeholder="例如：节奏更紧凑；开场用空镜；把高潮拆成 3 个分镜"
          />
          <div style={{ marginTop: 16 }}>
            <Button
              type="primary"
              size="large"
              icon={<ThunderboltOutlined />}
              loading={starting || outlineRunning}
              onClick={() => executeGenerate(extraPrompt)}
            >
              生成分镜大纲
            </Button>
          </div>
        </div>
      )}

      {mindmap && viewMode === 'preview' && (
        <div style={{ marginTop: 16 }}>
          {segments.length > 0 && (
            <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
              分镜标题后的「Ns · overlap Ns」为 AI 分析的建议时长与衔接参考值，可在第 3 步「分镜管理」中调整
            </Text>
          )}
          <MindmapView markdown={previewMindmap} height={520} />
        </div>
      )}

      {mindmap && viewMode === 'edit' && (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary">
              直接编辑 markdown：### 分镜标题，其下 `- ` 列表行为分镜内容；保存后同步更新导图与分镜列表，
              内容有变化或增删的分镜需在第 3 步重新生成提示词
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
            下游已有分镜配置 / 视频数据，重新生成大纲将清空这些数据；仅保存编辑不会清空
          </span>
        </div>
      )}

    </Card>
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          重新生成分镜大纲 - 补充要求
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
        <Text type="secondary">
          {mindmap
            ? '重新生成将级联清空分镜配置、分镜提示词与视频数据；可输入补充要求（可选）。'
            : '上次生成失败，可调整补充要求后重试（可选）。'}
        </Text>
      </div>
      <PresetPromptSelect
        onPick={(t) =>
          setPromptModal((m) => ({ ...m, extraPrompt: m.extraPrompt ? `${m.extraPrompt}；${t}` : t }))
        }
      />
      <TextArea
        rows={4}
        value={promptModal.extraPrompt}
        onChange={(e) => setPromptModal((m) => ({ ...m, extraPrompt: e.target.value }))}
        placeholder="例如：节奏更紧凑；开场用空镜；把高潮拆成 3 个分镜"
      />
    </Modal>
    </>
  )
}

export default StepStoryboardOutline
