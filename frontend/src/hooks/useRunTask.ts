/**
 * 全局 Agent 任务的组件侧派生状态、发起守卫与发起入口（含排队中任务与 POST 在途防重）
 */
import { useState } from 'react'
import { message } from 'antd'
import type { AgentRunKind, AgentRunTask } from '@/stores/agentRunStore'
import { hasRunningRun, isActiveRun, useAgentRunStore } from '@/stores/agentRunStore'

/** 同会话同类型（可限定实体）当前进行中/排队中的任务对象（无则 undefined；派生 episodeId 等） */
export const useActiveRun = (sessionId: string, kind: AgentRunKind, entityId?: string) =>
  useAgentRunStore((s) => s.runs.find((r) => isActiveRun(r, sessionId, kind, entityId)))

/** 同会话同类型是否有进行中/排队中的任务（按钮禁用等派生） */
export const useRunActive = (sessionId: string, kind: AgentRunKind, entityId?: string) =>
  useAgentRunStore((s) => s.runs.some((r) => isActiveRun(r, sessionId, kind, entityId)))

/** 同会话同类型最新一次失败任务的错误信息（空串表示无；取消不算失败，重新发起后自动清除） */
export const useRunError = (sessionId: string, kind: AgentRunKind, entityId?: string) =>
  useAgentRunStore((s) => {
    for (let i = s.runs.length - 1; i >= 0; i--) {
      const r = s.runs[i]
      if (
        r.sessionId === sessionId &&
        r.kind === kind &&
        (entityId === undefined || r.entityId === entityId) &&
        r.status === 'error'
      ) {
        return r.error || ''
      }
    }
    return ''
  })

/** 发起前守卫：POST 在途（starting）或已有进行中/排队任务时拦截并提示；返回 true 表示被拦截 */
export const guardRunStart = (sessionId: string, kind: AgentRunKind, label: string, starting: boolean): boolean => {
  if (starting || hasRunningRun(sessionId, kind)) {
    message.warning(`${label}任务进行中（见右上角后台任务），请等待完成后再试`)
    return true
  }
  return false
}

export interface StartRunOptions {
  kind: AgentRunKind
  /** 守卫提示名（如「故事大纲」；默认成功提示为 `${label}生成已发起，进度见右上角后台任务`） */
  label: string
  /** 发起请求并返回 run_id（内部含响应解包与 run_id 校验） */
  invoke: () => Promise<string>
  /** 发起前执行（如关闭参数弹窗） */
  close?: () => void
  /** addRun 附带的任务判别字段（episodeId / segmentIndex / segmentTitle / entityId / entityName） */
  extra?: Partial<Pick<AgentRunTask, 'episodeId' | 'segmentIndex' | 'segmentTitle' | 'entityId' | 'entityName'>>
  /** 成功提示文案（默认 `${label}生成已发起，进度见右上角后台任务`） */
  infoText?: string
  /** 自定义「任务进行中」守卫（返回 true 拦截并自行提示；默认 kind 级，分镜级任务传分镜粒度） */
  guard?: () => boolean
}

/**
 * 发起全局 Agent 任务的统一入口（收敛各 Step 组件逐字复制的发起样板）：
 * 守卫 → setStarting → 关弹窗 → POST → addRun → message.info → catch → finally
 */
export const useStartRun = (sessionId: string) => {
  const [starting, setStarting] = useState(false)

  const launch = async (opts: StartRunOptions): Promise<boolean> => {
    if (starting) return false
    const blocked = opts.guard
      ? opts.guard()
      : guardRunStart(sessionId, opts.kind, opts.label, false)
    if (blocked) return false
    setStarting(true)
    opts.close?.()
    try {
      const runId = await opts.invoke()
      useAgentRunStore.getState().addRun({ runId, sessionId, kind: opts.kind, ...opts.extra })
      message.info(opts.infoText || `${opts.label}生成已发起，进度见右上角后台任务`)
      return true
    } catch (e) {
      message.error((e as Error).message)
      return false
    } finally {
      setStarting(false)
    }
  }

  return { starting, launch }
}
