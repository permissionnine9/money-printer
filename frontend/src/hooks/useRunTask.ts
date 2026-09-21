/**
 * 全局 Agent 任务的组件侧派生状态与发起守卫（含排队中任务与 POST 在途防重）
 */
import { message } from 'antd'
import type { AgentRunKind } from '@/stores/agentRunStore'
import { hasRunningRun, useAgentRunStore } from '@/stores/agentRunStore'

/** 同会话同类型是否有进行中/排队中的任务（按钮禁用等派生） */
export const useRunActive = (sessionId: string, kind: AgentRunKind) =>
  useAgentRunStore((s) =>
    s.runs.some(
      (r) => r.sessionId === sessionId && r.kind === kind && (r.status === 'running' || r.status === 'queued'),
    ),
  )

/** 同会话同类型最近一次失败任务的错误信息（无则空串，任务卡片被移除后自动消失） */
export const useRunError = (sessionId: string, kind: AgentRunKind) =>
  useAgentRunStore((s) => {
    const r = s.runs.find((x) => x.sessionId === sessionId && x.kind === kind && x.status === 'error')
    return r?.error || ''
  })

/** 发起前守卫：POST 在途（starting）或已有进行中/排队任务时拦截并提示；返回 true 表示被拦截 */
export const guardRunStart = (sessionId: string, kind: AgentRunKind, label: string, starting: boolean): boolean => {
  if (starting || hasRunningRun(sessionId, kind)) {
    message.warning(`${label}任务进行中（见右上角后台任务），请等待完成后再试`)
    return true
  }
  return false
}
