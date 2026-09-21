/**
 * 全局任务状态横幅：进行中/排队中（绿色）与最近失败（红色），进度详情见右上角后台任务
 */
import React from 'react'
import { Spin } from 'antd'
import { CloseCircleOutlined } from '@ant-design/icons'

export interface RunTaskBannerProps {
  /** 进行中（含排队） */
  active: boolean
  /** 最近失败信息（空串表示无） */
  error: string
  /** 进行中提示文案，如「故事大纲生成中」 */
  activeText: string
}

export const RunTaskBanner: React.FC<RunTaskBannerProps> = ({ active, error, activeText }) => {
  if (active) {
    return (
      <div
        style={{
          marginTop: 16,
          padding: 12,
          background: '#f6ffed',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <Spin size="small" />
        <span style={{ color: '#389e0d' }}>{activeText}，进度见右上角后台任务（可切换菜单，任务后台运行）</span>
      </div>
    )
  }
  if (error) {
    return (
      <div
        style={{
          marginTop: 16,
          padding: 12,
          background: '#fff2f0',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        <CloseCircleOutlined style={{ color: '#ff4d4f' }} />
        <span style={{ color: '#cf1322' }}>生成失败：{error}，可重新发起</span>
      </div>
    )
  }
  return null
}
