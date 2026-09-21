/**
 * Agent 任务状态 → 图标/文案 的单一来源（AgentRunDock 卡片与 AgentRunProgress 共用，
 * 勿在组件里重复映射；store 是 .ts 不能写 JSX，故放组件层）
 */
import React from 'react'
import { Spin } from 'antd'
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  MinusCircleOutlined,
} from '@ant-design/icons'

export type RunStatus = 'queued' | 'running' | 'success' | 'error' | 'cancelled'

export const runStatusText = (status: RunStatus): string => {
  switch (status) {
    case 'queued':
      return '排队中…'
    case 'running':
      return '生成中…'
    case 'error':
      return '失败'
    case 'cancelled':
      return '已取消'
    case 'success':
      return '已完成'
  }
}

export const RunStatusIcon: React.FC<{ status: RunStatus; size?: number }> = ({ status, size = 14 }) => {
  switch (status) {
    case 'queued':
      return <ClockCircleOutlined style={{ color: '#faad14', fontSize: size }} />
    case 'running':
      return <Spin size="small" />
    case 'error':
      return <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: size }} />
    case 'cancelled':
      return <MinusCircleOutlined style={{ color: '#8c8c8c', fontSize: size }} />
    case 'success':
      return <CheckCircleOutlined style={{ color: '#52c41a', fontSize: size }} />
  }
}
