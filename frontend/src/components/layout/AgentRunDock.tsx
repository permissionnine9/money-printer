/**
 * 全局 Agent 后台任务 Dock：右上角任务卡片列表 + 每任务一个进度弹窗。
 * 弹窗不设 destroyOnHidden（收起仅隐藏不卸载），AgentRunProgress 保持挂载、SSE 不断流；
 * 挂在 MainLayout，跨步骤/跨页面持续显示。
 */
import React from 'react'
import { Button, Modal, Spin, Typography, message } from 'antd'
import {
  CheckCircleOutlined,
  CloseCircleOutlined,
  CloseOutlined,
  DownOutlined,
} from '@ant-design/icons'
import type { AgentEvent } from '@/types'
import { useAgentRunStore } from '@/stores/agentRunStore'
import { useSessionStore } from '@/stores/sessionStore'
import { AgentRunProgress } from '@/components/script/AgentRunProgress'
import styles from './AgentRunDock.module.css'

const { Text } = Typography

const segmentName = (segmentIndex: number, segmentTitle?: string) =>
  `分镜 ${segmentIndex + 1}${segmentTitle ? `《${segmentTitle}》` : ''}`

export const AgentRunDock: React.FC = () => {
  const runs = useAgentRunStore((s) => s.runs)
  const { expandRun, collapseRun, removeRun, markRunStatus } = useAgentRunStore()

  // run 终态：成功 → 通知 + 移除 + 刷新会话；失败/取消 → 标红留在列表
  const handleRunDone = async (runId: string, ev: AgentEvent) => {
    const run = useAgentRunStore.getState().runs.find((r) => r.runId === runId)
    if (!run) return
    const name = segmentName(run.segmentIndex, run.segmentTitle)
    if (ev.success) {
      const r = ev.result as { match_status?: string; matched_image_ids?: string[] } | undefined
      const matched = r?.matched_image_ids?.length ?? 0
      if (r?.match_status === 'matched' && matched > 0) {
        message.success(`${name} 提示词已生成，已自动匹配 ${matched} 张参考素材图`)
      } else if (r?.match_status === 'failed') {
        message.warning(`${name} 提示词已生成（参考图自动匹配失败，可在分镜中手动关联素材图）`)
      } else {
        message.success(`${name} 提示词已生成`)
      }
      removeRun(runId)
      // 用户可能已切到其他会话/页面，仅当当前会话匹配时刷新
      if (useSessionStore.getState().currentSession?.session_id === run.sessionId) {
        await useSessionStore.getState().refreshSession()
      }
    } else {
      markRunStatus(runId, 'error', ev.error)
      message.error(`${name} 提示词生成失败：${ev.error || '未知错误'}`)
    }
  }

  if (!runs.length) return null

  return (
    <>
      {/* 右上角固定任务卡片列表（Header 下方） */}
      <div className={styles.dock}>
        {runs.map((run) => (
          <div
            key={run.runId}
            className={`${styles.card}${run.status === 'error' ? ` ${styles.cardError}` : ''}`}
            onClick={() => expandRun(run.runId)}
          >
            {run.status === 'running' && <Spin size="small" />}
            {run.status === 'error' && <CloseCircleOutlined style={{ color: '#ff4d4f' }} />}
            {run.status === 'success' && <CheckCircleOutlined style={{ color: '#52c41a' }} />}
            <Text className={styles.cardName} ellipsis>
              {segmentName(run.segmentIndex, run.segmentTitle)}
            </Text>
            <Text type="secondary" className={styles.cardStatus}>
              {run.status === 'running' ? '生成中…' : run.status === 'error' ? '失败' : '已完成'}
            </Text>
            {run.status !== 'running' && (
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

      {/* 每任务一个进度弹窗：forceRender 保证收起态添加也挂载，不设 destroyOnHidden 保活 SSE */}
      {runs.map((run) => (
        <Modal
          key={run.runId}
          width={720}
          forceRender
          open={run.expanded}
          title={`生成分镜提示词 - ${segmentName(run.segmentIndex, run.segmentTitle)}`}
          onCancel={() => (run.status === 'running' ? collapseRun(run.runId) : removeRun(run.runId))}
          footer={
            run.status === 'running' ? (
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
