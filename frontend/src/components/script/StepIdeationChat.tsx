/**
 * 第 1 步：故事构思（与 AI 编剧 agent 多轮对话，SSE 直跑；确认后收敛故事逻辑并完成步骤）
 */
import React, { useEffect, useRef, useState } from 'react'
import { Button, Card, Collapse, Empty, Input, Space, Spin, Tag, Typography, message } from 'antd'
import { CheckCircleOutlined, CheckOutlined, EyeOutlined, SaveOutlined, SendOutlined, StopOutlined } from '@ant-design/icons'
import type { AgentEvent, IdeationMessage, ScriptSessionDetail } from '@/types'
import { scriptStepApi } from '@/api/client'
import { fetchSSE } from '@/api/sse'
import { PromptViewerModal } from '@/components/common'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'

const { Text } = Typography
const { TextArea } = Input

// AI 回复是否为故事逻辑格式（行首「核心情境：」锚点，与 finalize 输出结构一致；
// 行首+冒号避免盘问解释中顺带提到该词被误判）
const looksLikeStoryLogic = (t: string) => /^核心情境[:：]/m.test(t)

// 编辑框草稿：已 finalize 以文件为准，否则取最近一条格式化的 AI 回复
const draftStoryLogic = (msgs: IdeationMessage[], fileLogic: string): string => {
  if (fileLogic) return fileLogic
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i]
    if (m.role === 'assistant' && looksLikeStoryLogic(m.content)) return m.content
  }
  return ''
}

interface StepIdeationChatProps {
  session: ScriptSessionDetail
}

const BUBBLE_BASE: React.CSSProperties = {
  maxWidth: '78%',
  padding: '8px 12px',
  borderRadius: 8,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  fontSize: 14,
}

export const StepIdeationChat: React.FC<StepIdeationChatProps> = ({ session }) => {
  const { refreshSession, loadSessions } = useScriptSessionStore()
  const ideationData = session.step_results?.story_ideation?.result_data
  const isCompleted = session.completed_steps?.includes('story_ideation')
  const storyLogic: string = ideationData?.story_logic || ''
  const storyTitle: string = ideationData?.title || ''

  const [messages, setMessages] = useState<IdeationMessage[]>(ideationData?.messages || [])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState<'' | 'chat' | 'finalize' | 'adopt'>('')
  const [round, setRound] = useState<{ thinking: string; text: string } | null>(null)
  const [storyLogicEdit, setStoryLogicEdit] = useState(storyLogic)
  const [savingLogic, setSavingLogic] = useState(false)
  const [titleEdit, setTitleEdit] = useState(storyTitle)
  const [savingTitle, setSavingTitle] = useState(false)
  const [lastPrompt, setLastPrompt] = useState<{ systemPrompt: string; userPrompt: string; model: string } | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)

  const accRef = useRef({ thinking: '', text: '' })
  const abortRef = useRef<AbortController | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  // 会话切换时从后端还原对话历史
  useEffect(() => {
    setMessages(session.step_results?.story_ideation?.result_data?.messages || [])
    setLastPrompt(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.session_id])

  // 编辑框同步：文件值变化或会话切换时回填（文件值优先，否则带出最近格式化草稿）；
  // 与会话切换合并依赖，避免切会话时被上一个会话的旧值同步覆盖、清空草稿
  useEffect(() => {
    const msgs = session.step_results?.story_ideation?.result_data?.messages || []
    setStoryLogicEdit(draftStoryLogic(msgs, storyLogic))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.session_id, storyLogic])

  // 剧本名同步（同上，合并依赖防切会话旧值覆盖）
  useEffect(() => {
    setTitleEdit(storyTitle)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.session_id, storyTitle])

  // 新消息 / 流式增量时滚动到底部
  useEffect(() => {
    const el = listRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages, round])

  // SSE 直跑一轮（chat=发消息，finalize=收敛故事逻辑）
  const runStream = async (kind: 'chat' | 'finalize', userText?: string) => {
    if (busy) return
    if (kind === 'chat' && !userText?.trim()) return
    if (kind === 'finalize' && messages.length === 0) return
    if (userText?.trim()) {
      setMessages((prev) => [...prev, { role: 'user', content: userText.trim() }])
    }
    setInput('')
    accRef.current = { thinking: '', text: '' }
    setRound({ thinking: '', text: '' })
    setBusy(kind)
    const controller = new AbortController()
    abortRef.current = controller

    const url =
      kind === 'chat'
        ? `/api/v1/script-sessions/${session.session_id}/ideation/message`
        : `/api/v1/script-sessions/${session.session_id}/ideation/finalize`

    let finalContent = ''
    let failed = false
    await fetchSSE(
      url,
      kind === 'chat' ? { message: userText!.trim() } : {},
      {
        onEvent: (ev: AgentEvent) => {
          if (ev.type === 'prompt') {
            // 多轮会话仅含本轮 user 消息（历史轮由 agent 会话保持）
            setLastPrompt({
              systemPrompt: ev.system_prompt || '',
              userPrompt: ev.user_prompt || '',
              model: ev.model || '',
            })
            return
          }
          if (ev.type === 'thinking') {
            accRef.current.thinking += ev.delta || ''
            setRound({ ...accRef.current })
            return
          }
          if (ev.type === 'tool_use') {
            accRef.current.thinking += `\n[调用工具 ${ev.tool}]`
            setRound({ ...accRef.current })
            return
          }
          if (ev.type === 'text_delta') {
            accRef.current.text += ev.delta || ''
            setRound({ ...accRef.current })
            return
          }
          if (ev.type === 'result') {
            if (ev.text) {
              accRef.current.text = ev.text
              setRound({ ...accRef.current })
            }
            return
          }
          if (ev.type === 'final') {
            finalContent = ev.data?.assistant_message || ev.data?.story_logic || accRef.current.text
            return
          }
          if (ev.type === 'error') {
            failed = true
            message.error(ev.message || '生成失败')
          }
        },
        onError: (err: Error) => {
          failed = true
          message.error(err.message)
        },
      },
      controller.signal,
    )

    // 收尾：把本轮 assistant 回复落进消息列表（中断时保留已生成部分）
    const aborted = controller.signal.aborted && !finalContent
    const content = finalContent || accRef.current.text
    if (content) {
      setMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: aborted ? `${content}\n\n（已中断）` : content,
          ...(kind === 'finalize' && finalContent ? { kind: 'story_logic' as const } : {}),
        },
      ])
      // 盘问中 AI 直接给出新版故事逻辑：自动填入下方编辑框，免去手动复制
      // （中断的残缺内容不刷入，避免「（已中断）」标记混入草稿）
      if (kind === 'chat' && !aborted && looksLikeStoryLogic(content)) {
        setStoryLogicEdit(content)
        message.info('AI 给出了新版故事逻辑，已填入下方编辑框')
      }
    }
    setRound(null)
    abortRef.current = null
    setBusy('')
    if (kind === 'finalize') {
      if (finalContent && !failed) {
        message.success('故事逻辑已确认，第 1 步完成')
        await refreshSession()
      }
    } else {
      void refreshSession()
    }
  }

  const handleSend = () => void runStream('chat', input)
  const handleFinalize = () => void runStream('finalize')
  const handleStop = () => abortRef.current?.abort()

  // 采纳编辑框当前内容为故事逻辑并完成第 1 步（不经 LLM 收敛）
  const handleAdopt = async () => {
    if (!storyLogicEdit.trim()) return
    setBusy('adopt')
    try {
      await scriptStepApi.adoptStoryLogic(session.session_id, storyLogicEdit)
      message.success('已采纳故事逻辑，第 1 步完成')
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setBusy('')
    }
  }

  // 手动采纳某条 AI 回复到编辑框
  const adoptMessage = (content: string) => {
    setStoryLogicEdit(content)
    message.success('已采纳到下方故事逻辑编辑框')
  }

  // 保存剧本名（侧栏显示名；生成大纲后以大纲根标题为准）
  const saveTitle = async () => {
    if (!titleEdit.trim()) {
      message.warning('剧名不能为空')
      return
    }
    setSavingTitle(true)
    try {
      await scriptStepApi.setStoryTitle(session.session_id, titleEdit)
      message.success('剧本名已保存')
      await Promise.all([refreshSession(), loadSessions()])
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSavingTitle(false)
    }
  }

  const saveStoryLogic = async () => {
    if (!storyLogicEdit.trim()) {
      message.warning('故事逻辑不能为空')
      return
    }
    setSavingLogic(true)
    try {
      await scriptStepApi.updateStoryLogic(session.session_id, storyLogicEdit)
      message.success('故事逻辑已保存')
      await refreshSession()
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setSavingLogic(false)
    }
  }

  const renderMessage = (m: IdeationMessage, i: number) => {
    const isUser = m.role === 'user'
    return (
      <div key={i} style={{ display: 'flex', justifyContent: isUser ? 'flex-end' : 'flex-start', marginBottom: 12 }}>
        <div
          style={{
            ...BUBBLE_BASE,
            background: isUser ? '#e6f4ff' : '#f5f5f5',
            border: `1px solid ${isUser ? '#91caff' : '#e8e8e8'}`,
          }}
        >
          {m.kind === 'story_logic' && (
            <Tag color="gold" style={{ marginBottom: 4 }}>
              故事逻辑
            </Tag>
          )}
          {m.content}
          {!isUser && m.kind !== 'story_logic' && (
            <div style={{ marginTop: 4, textAlign: 'right' }}>
              <Button type="link" size="small" style={{ padding: 0, height: 'auto', fontSize: 12 }} onClick={() => adoptMessage(m.content)}>
                采纳为故事逻辑
              </Button>
            </div>
          )}
        </div>
      </div>
    )
  }

  const streamingBubble = round ? (
    <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: 12 }}>
      <div style={{ ...BUBBLE_BASE, background: '#f5f5f5', border: '1px solid #e8e8e8' }}>
        {round.thinking ? (
          <Collapse
            ghost
            size="small"
            items={[
              {
                key: 'thinking',
                label: (
                  <Text type="secondary" style={{ fontSize: 12 }}>
                    思考中…
                  </Text>
                ),
                children: (
                  <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 180, overflow: 'auto' }}>
                    {round.thinking}
                  </pre>
                ),
              },
            ]}
          />
        ) : null}
        {round.text ? (
          <div>{round.text}</div>
        ) : (
          <Space>
            <Spin size="small" />
            <Text type="secondary">生成中…</Text>
          </Space>
        )}
      </div>
    </div>
  ) : null

  return (
    <>
      <Card
        title={
          <span>
            故事构思
            {isCompleted && (
              <Tag color="success" style={{ marginLeft: 8 }}>
                已完成
              </Tag>
            )}
          </span>
        }
        style={{ marginTop: 16 }}
      >
        <Text type="secondary">
          与 AI 编剧多轮讨论故事方向（题材 / 人物 / 主线 / 结局走向）。AI 给出的新版故事逻辑会自动填入下方编辑框（也可在消息上点「采纳为故事逻辑」），满意后点「采纳并完成第一步」；需要 AI 汇总整理时点「让 AI 收敛故事逻辑」。
        </Text>

        <div ref={listRef} style={{ marginTop: 16, maxHeight: 420, overflow: 'auto' }}>
          {messages.length === 0 && !round && (
            <Empty description="开始第一轮构思，例如：帮我构思一个 8 集都市悬疑短剧" style={{ marginTop: 48 }} />
          )}
          {messages.map(renderMessage)}
          {streamingBubble}
        </div>

        {lastPrompt && (
          <div style={{ marginTop: 8, textAlign: 'right' }}>
            <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setPromptOpen(true)}>
              查看本轮提示词
            </Button>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder={busy ? '生成中…' : '输入你的故事想法，与 AI 编剧讨论'}
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={busy !== ''}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}  
          />
          {busy ? null : (
            <Button type="primary" icon={<SendOutlined />} disabled={!input.trim()} onClick={handleSend}>
              发送
            </Button>
          )}
        </div>

        <div style={{ marginTop: 16, textAlign: 'center' }}>
          <Button
            type="primary"
            ghost={isCompleted}
            icon={<CheckOutlined />}
            loading={busy === 'adopt'}
            disabled={busy !== '' || !storyLogicEdit.trim()}
            onClick={() => void handleAdopt()}
          >
            {isCompleted ? '重新采纳并更新' : '采纳并完成第一步'}
          </Button>
          <Button
            style={{ marginLeft: 8 }}
            icon={<CheckCircleOutlined />}
            loading={busy === 'finalize'}
            disabled={busy !== '' || messages.length === 0}
            onClick={handleFinalize}
          >
            让 AI 收敛故事逻辑
          </Button>
          {(busy === 'chat' || busy === 'finalize') ? (
            <Button style={{ marginLeft: 8 }} danger icon={<StopOutlined />} onClick={handleStop}>
              停止
            </Button>
          ) : null}

          {messages.length === 0 && !storyLogicEdit && (
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                先聊一轮让 AI 生成故事逻辑，或直接在下方编辑框粘贴后采纳
              </Text>
            </div>
          )}
          {isCompleted && (
            <div style={{ marginTop: 4 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                步骤已完成，仍可继续盘问（直接发送消息）后重新采纳
              </Text>
            </div>
          )}
        </div>
      </Card>

      <Card
        size="small"
        title="故事逻辑"
        style={{ marginTop: 16 }}
        extra={isCompleted ? <Tag color="success">已确认</Tag> : <Tag color="warning">待确认</Tag>}
      >
          <div style={{ display: 'flex', gap: 8, marginBottom: 8, alignItems: 'center' }}>
            <Text type="secondary" style={{ flexShrink: 0 }}>
              剧本名
            </Text>
            <Input
              value={titleEdit}
              onChange={(e) => setTitleEdit(e.target.value)}
              placeholder="侧边栏与会话显示名（AI 收敛时自动起名，可手动修改）"
              maxLength={60}
              onPressEnter={() => void saveTitle()}
              disabled={savingTitle}
            />
            <Button
              icon={<SaveOutlined />}
              loading={savingTitle}
              disabled={savingTitle || !titleEdit.trim() || titleEdit.trim() === storyTitle.trim()}
              onClick={() => void saveTitle()}
            >
              保存
            </Button>
          </div>
          <TextArea
            value={storyLogicEdit}
            onChange={(e) => setStoryLogicEdit(e.target.value)}
            autoSize={{ minRows: 4, maxRows: 12 }}
          />
          <div style={{ marginTop: 8, textAlign: 'right' }}>
            <Button icon={<SaveOutlined />} loading={savingLogic} onClick={saveStoryLogic}>
              保存
            </Button>
          </div>
      </Card>

      <PromptViewerModal
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        systemPrompt={lastPrompt?.systemPrompt}
        userPrompt={lastPrompt?.userPrompt}
        model={lastPrompt?.model}
      />
    </>
  )
}

export default StepIdeationChat
