/**
 * Agent run 观流组件：连接 /agent-runs/{run_id}/events 展示状态行 / 思考折叠 / 最新文本，支持取消与断线重连
 */
import React, { useEffect, useRef, useState } from 'react'
import { Button, Collapse, Space, Typography, message } from 'antd'
import { EyeOutlined, StopOutlined } from '@ant-design/icons'
import type { AgentEvent } from '@/types'
import { agentRunApi } from '@/api/client'
import { fetchSSE } from '@/api/sse'
import { useAgentRunStore } from '@/stores/agentRunStore'
import { PromptViewerModal, RunStatusIcon, runStatusText } from '@/components/common'

const { Text } = Typography

export interface AgentRunProgressProps {
  /** 后台 agent run id */
  runId: string
  /** 收到 done 事件（run 终态）后回调 */
  onDone?: (event: AgentEvent) => void
}

const MAX_RETRIES = 6
const RETRY_INTERVAL = 2000

export const AgentRunProgress: React.FC<AgentRunProgressProps> = ({ runId, onDone }) => {
  const [label, setLabel] = useState('')
  const [thinking, setThinking] = useState('')
  const [text, setText] = useState('')
  const [status, setStatus] = useState<'queued' | 'running' | 'success' | 'error' | 'cancelled'>('queued')
  const [queuePosition, setQueuePosition] = useState(-1)
  const [errorMsg, setErrorMsg] = useState('')
  const [cancelling, setCancelling] = useState(false)
  const [prompt, setPrompt] = useState<{ systemPrompt: string; userPrompt: string; model: string } | null>(null)
  const [promptOpen, setPromptOpen] = useState(false)

  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    // 新 run：重置展示状态（初始 queued，started 事件后转 running）
    setLabel('')
    setThinking('')
    setText('')
    setStatus('queued')
    setQueuePosition(-1)
    setErrorMsg('')
    setCancelling(false)
    setPrompt(null)
    setPromptOpen(false)

    let cancelled = false
    let finished = false
    let retries = 0
    let lastSeq = 0
    const controller = new AbortController()

    const fail = (msg: string, reason = '') => {
      finished = true
      setStatus(reason === 'cancelled' ? 'cancelled' : 'error')
      setErrorMsg(msg)
      onDoneRef.current?.({ type: 'done', success: false, error: msg, reason })
    }

    const handleEvent = (ev: AgentEvent) => {
      if (ev.seq && ev.seq > lastSeq) lastSeq = ev.seq
      switch (ev.type) {
        case 'connected':
          setLabel(ev.label || '')
          retries = 0
          break
        case 'queued':
          // 入队回放/实时（幂等）：断线重连重复收到不影响状态
          if (ev.queue_position !== undefined) setQueuePosition(ev.queue_position)
          break
        case 'started':
          setStatus('running')
          useAgentRunStore.getState().markRunRunning(runId)
          break
        case 'prompt':
          // 赋值替换（幂等）：断线重连回放不会重复累积
          setPrompt({
            systemPrompt: ev.system_prompt || '',
            userPrompt: ev.user_prompt || '',
            model: ev.model || '',
          })
          break
        case 'thinking':
          setThinking((prev) => prev + (ev.delta || ''))
          break
        case 'tool_use':
          setThinking((prev) => prev + `\n[调用工具 ${ev.tool}]`)
          break
        case 'text_delta':
          setText((prev) => prev + (ev.delta || ''))
          break
        case 'result':
          if (ev.text) setText(ev.text)
          break
        case 'done':
          // fail()（error 事件路径）已合成过终态通知，跳过防重复 onDone（双 toast）
          if (finished) break
          finished = true
          if (ev.success) {
            setStatus('success')
          } else if (ev.reason === 'cancelled') {
            setStatus('cancelled')
            setErrorMsg(ev.error || '已取消')
          } else {
            setStatus('error')
            setErrorMsg(ev.error || '运行失败')
          }
          onDoneRef.current?.(ev)
          break
        case 'error':
          fail(ev.message || '运行异常', ev.reason)
          break
      }
    }

    const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

    const run = async () => {
      while (!cancelled && !finished) {
        await fetchSSE(
          `/api/v1/agent-runs/${runId}/events${lastSeq ? `?seq=${lastSeq}` : ''}`,
          undefined,
          {
            onEvent: handleEvent,
            onError: (err) => {
              // HTTP 层错误（如 run 不存在）：直接失败；读流中网络中断走重连
              if (/^HTTP/.test(err.message)) fail(err.message)
            },
          },
          controller.signal,
        )
        if (cancelled || finished) break
        retries += 1
        if (retries > MAX_RETRIES) {
          fail('连接中断，已停止重试')
          break
        }
        await sleep(RETRY_INTERVAL)
      }
    }
    void run()

    return () => {
      cancelled = true
      controller.abort()
    }
  }, [runId])

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await agentRunApi.cancel(runId)
      message.info('已请求取消')
    } catch (e) {
      message.error((e as Error).message)
    } finally {
      setCancelling(false)
    }
  }

  const inFlight = status === 'running' || status === 'queued'
  const statusText =
    status === 'queued' && queuePosition > 0
      ? `排队中（前面还有 ${queuePosition} 个任务）…`
      : runStatusText(status)

  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: '12px 16px', background: '#fafafa' }}>
      <div style={{ display: 'flex', flexDirection: 'column', gap:'6px', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space style={{ display: 'flex', flexDirection: 'row', padding:'6px 0', justifyContent: 'space-between', width: "100%",background: 'rgba(100, 100, 100, 0.05)' }}>{prompt && (
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => setPromptOpen(true)}>
            查看提示词
          </Button>
        )}
          {inFlight && (
            <Button size="small" danger icon={<StopOutlined />} loading={cancelling} onClick={handleCancel}>
              取消
            </Button>
          )}
        </Space>
        <Space style={{width:'100%'}}>
          <RunStatusIcon status={status} />
          <Text strong>{label || 'Agent 运行'}</Text>
          <Text type="secondary">{statusText}</Text>
        </Space>

      </div>

      {errorMsg && (
        <div style={{ marginTop: 8 }}>
          <Text type={status === 'cancelled' ? 'secondary' : 'danger'} style={{ fontSize: 13 }}>{errorMsg}</Text>
        </div>
      )}

      {thinking ? (
        <Collapse
          ghost
          size="small"
          style={{ marginTop: 4 }}
          items={[
            {
              key: 'thinking',
              label: <Text type="secondary" style={{ fontSize: 12 }}>思考过程</Text>,
              children: (
                <pre style={{ margin: 0, fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', maxHeight: 200, overflow: 'auto' }}>
                  {thinking}
                </pre>
              ),
            },
          ]}
        />
      ) : null}

      {text ? (
        <div
          style={{
            marginTop: 8,
            fontSize: 13,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
            maxHeight: 180,
            overflow: 'auto',
            background: '#fff',
            border: '1px solid #f0f0f0',
            borderRadius: 6,
            padding: 8,
          }}
        >
          {text}
        </div>
      ) : null}

      <PromptViewerModal
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        systemPrompt={prompt?.systemPrompt}
        userPrompt={prompt?.userPrompt}
        model={prompt?.model}
      />
    </div>
  )
}

export default AgentRunProgress
