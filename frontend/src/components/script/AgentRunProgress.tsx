/**
 * Agent run 观流组件：连接 /agent-runs/{run_id}/events 展示状态行 / 思考折叠 / 最新文本，支持取消与断线重连
 */
import React, { useEffect, useRef, useState } from 'react'
import { Button, Collapse, Space, Spin, Typography, message } from 'antd'
import { CheckCircleOutlined, CloseCircleOutlined, StopOutlined } from '@ant-design/icons'
import type { AgentEvent } from '@/types'
import { agentRunApi } from '@/api/client'
import { fetchSSE } from '@/api/sse'

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
  const [status, setStatus] = useState<'running' | 'success' | 'error'>('running')
  const [errorMsg, setErrorMsg] = useState('')
  const [cancelling, setCancelling] = useState(false)

  const onDoneRef = useRef(onDone)
  useEffect(() => {
    onDoneRef.current = onDone
  }, [onDone])

  useEffect(() => {
    // 新 run：重置展示状态
    setLabel('')
    setThinking('')
    setText('')
    setStatus('running')
    setErrorMsg('')
    setCancelling(false)

    let cancelled = false
    let finished = false
    let retries = 0
    let lastSeq = 0
    const controller = new AbortController()

    const fail = (msg: string) => {
      finished = true
      setStatus('error')
      setErrorMsg(msg)
      onDoneRef.current?.({ type: 'done', success: false, error: msg })
    }

    const handleEvent = (ev: AgentEvent) => {
      if (ev.seq && ev.seq > lastSeq) lastSeq = ev.seq
      switch (ev.type) {
        case 'connected':
          setLabel(ev.label || '')
          retries = 0
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
          finished = true
          if (ev.success) {
            setStatus('success')
          } else {
            setStatus('error')
            setErrorMsg(ev.error || '运行失败')
          }
          onDoneRef.current?.(ev)
          break
        case 'error':
          fail(ev.message || '运行异常')
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

  const statusText = status === 'running' ? '进行中…' : status === 'success' ? '已完成' : '失败'

  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, padding: '12px 16px', background: '#fafafa' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <Space>
          {status === 'running' && <Spin size="small" />}
          {status === 'success' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
          {status === 'error' && <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
          <Text strong>{label || 'Agent 运行'}</Text>
          <Text type="secondary">{statusText}</Text>
        </Space>
        {status === 'running' && (
          <Button size="small" danger icon={<StopOutlined />} loading={cancelling} onClick={handleCancel}>
            取消
          </Button>
        )}
      </div>

      {errorMsg && (
        <div style={{ marginTop: 8 }}>
          <Text type="danger" style={{ fontSize: 13 }}>{errorMsg}</Text>
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
    </div>
  )
}

export default AgentRunProgress
