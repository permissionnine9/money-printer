/**
 * 全局 Agent 任务 Dock：右上角默认收起为一枚带计数徽标的悬浮按钮（不遮挡页面），
 * 点击展开任务卡片列表，点卡片打开进度弹窗。
 * 弹窗不设 destroyOnHidden（收起仅隐藏不卸载），AgentRunProgress 保持挂载、SSE 不断流；
 * 挂在 MainLayout，跨步骤/跨页面持续显示。
 */
import React, { useState } from 'react'
import { Badge, Button, Modal, Spin, Typography, message } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  DownOutlined,
} from '@ant-design/icons'
import type { AgentEvent } from '@/types'
import { RUN_KIND_LABEL, runDisplayName, useAgentRunStore } from '@/stores/agentRunStore'
import { useSessionStore } from '@/stores/sessionStore'
import { useScriptSessionStore } from '@/stores/scriptSessionStore'
import { AgentRunProgress } from '@/components/script/AgentRunProgress'
import styles from './AgentRunDock.module.css'

const { Text } = Typography

export const AgentRunDock: React.FC = () => {
  const runs = useAgentRunStore((s) => s.runs)
  const { expandRun, collapseRun, removeRun, markRunStatus } = useAgentRunStore()
  const [open, setOpen] = useState(false)

  // 任务清空时复位列表展开态（渲染期调整，避免 effect 级联渲染），下次任务到来仍是默认收起
  const [prevRunsLen, setPrevRunsLen] = useState(runs.length)
  if (runs.length !== prevRunsLen) {
    setPrevRunsLen(runs.length)
    if (runs.length === 0) setOpen(false)
  }

  const runningCount = runs.filter((r) => r.status === 'running' || r.status === 'queued').length
  const errorCount = runs.filter((r) => r.status === 'error').length

  // run 终态：成功 → 按类型通知 + 移除 + 刷新所属会话；失败/取消 → 标红留在列表
  const handleRunDone = async (runId: string, ev: AgentEvent) => {
    const run = useAgentRunStore.getState().runs.find((r) => r.runId === runId)
    if (!run) return
    const name = runDisplayName(run)
    if (ev.success) {
      switch (run.kind) {
        case 'segment_prompt': {
          const r = ev.result as { match_status?: string; matched_image_ids?: string[] } | undefined
          const matched = r?.matched_image_ids?.length ?? 0
          if (r?.match_status === 'matched' && matched > 0) {
            message.success(`${name} 提示词已生成，已自动匹配 ${matched} 张参考素材图`)
          } else if (r?.match_status === 'failed') {
            message.warning(`${name} 提示词已生成（参考图自动匹配失败，可在分镜中手动关联素材图）`)
          } else {
            message.success(`${name} 提示词已生成`)
          }
          break
        }
        case 'outline':
          message.success('故事大纲生成完成')
          break
        case 'episodes':
          message.success(run.episodeId ? `${run.episodeId} 重新设计完成` : '分集设计生成完成')
          break
        case 'storyboard_outline':
          message.success('分镜大纲生成完成')
          break
      }
      removeRun(runId)
      // 用户可能已切到其他会话/页面，仅当当前会话匹配时刷新
      const store =
        run.kind === 'outline' || run.kind === 'episodes'
          ? useScriptSessionStore.getState()
          : useSessionStore.getState()
      if (store.currentSession?.session_id === run.sessionId) {
        await store.refreshSession()
      }
    } else {
      markRunStatus(runId, 'error', ev.error)
      // 用户主动取消不算失败，中性提示（文案含「已取消」的均视为取消路径）
      if ((ev.error || '').includes('已取消')) {
        message.info(`${runDisplayName(run)} 已取消`)
      } else {
        message.error(`${RUN_KIND_LABEL[run.kind]}生成失败：${ev.error || '未知错误'}`)
      }
    }
  }

  if (!runs.length) return null

  return (
    <>
      {/* 右上角悬浮按钮（默认收起态）：进行中转圈 + 失败红标 + 计数徽标（有失败时红色，否则蓝色），点击展开列表 */}
      <div className={styles.toggle} onClick={() => setOpen((o) => !o)}>
        <Badge count={runs.length} size="small" color={errorCount ? '#ff4d4f' : 'blue'}>
          <span className={styles.toggleInner}>
            {runningCount > 0 && <Spin size="small" />}
            {errorCount > 0 && <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 14 }} />}
            <span>后台任务</span>
            <DownOutlined style={{ fontSize: 11, transform: open ? 'rotate(180deg)' : undefined }} />
          </span>
        </Badge>
      </div>

      {/* 展开后的任务卡片列表（悬浮按钮下方） */}
      {open && (
        <div className={styles.dock}>
          {runs.map((run) => (
            <div
              key={run.runId}
              className={`${styles.card}${run.status === 'error' ? ` ${styles.cardError}` : ''}`}
              onClick={() => {
                expandRun(run.runId)
                setOpen(false)
              }}
            >
              {run.status === 'queued' && <ClockCircleOutlined style={{ color: '#faad14', fontSize: 14 }} />}
              {run.status === 'running' && <Spin size="small" />}
              {run.status === 'error' && <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
              {run.status === 'success' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
              <Text className={styles.cardName} ellipsis>
                {runDisplayName(run)}
              </Text>
              <Text type="secondary" className={styles.cardStatus}>
                {run.status === 'queued'
                  ? '排队中…'
                  : run.status === 'running'
                    ? '生成中…'
                    : run.status === 'error'
                      ? (run.error || '').includes('已取消')
                        ? '已取消'
                        : '失败'
                      : '已完成'}
              </Text>
              {(run.status === 'success' || run.status === 'error') && (
                <CloseOutlined
                  className={styles.cardClose}
                  onClick={(e) => {
                    e.stopPropagation()
                    removeRun(run.runId)
                  }}
                />
              )}
            </div>
          ))}
        </div>
      )}

      {/* 每任务一个进度弹窗：forceRender 保证收起态添加也挂载，不设 destroyOnHidden 保活 SSE */}
      {runs.map((run) => (
        <Modal
          key={run.runId}
          width={720}
          forceRender
          open={run.expanded}
          title={
            run.kind === 'segment_prompt'
              ? `生成分镜提示词 - ${runDisplayName(run)}`
              : run.episodeId
                ? `重新设计 ${run.episodeId}`
                : `生成${RUN_KIND_LABEL[run.kind]}`
          }
          onCancel={() => ((run.status === 'running' || run.status === 'queued') ? collapseRun(run.runId) : removeRun(run.runId))}
          footer={
            run.status === 'running' || run.status === 'queued' ? (
              [<Button key="collapse" onClick={() => collapseRun(run.runId)}>
                收起到右上角（可继续其他操作，任务后台运行）
              </Button>]
            ) : (
              [<Button key="close" type="primary" onClick={() => removeRun(run.runId)}>
                关闭
              </Button>]
            )
          }
        >
          <AgentRunProgress runId={run.runId} onDone={(ev) => handleRunDone(run.runId, ev)} />
        </Modal>
      ))}
    </>
  )
}

export default AgentRunDock
