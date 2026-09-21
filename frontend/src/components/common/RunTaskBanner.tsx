/**
 * 全局任务状态横幅：进行中/排队中（绿色）与最近失败（红色），进度详情见右上角后台任务
 */
import React from 'react'
import { Alert } from 'antd'
import { LoadingOutlined } from '@ant-design/icons'

export interface RunTaskBannerProps {
  /** 进行中（含排队） */
  active: boolean
  /** 最近失败信息（空串表示无；取消不算失败） */
  error: string
  /** 进行中提示文案，如「故事大纲生成中」 */
  activeText: string
}

export const RunTaskBanner: React.FC<RunTaskBannerProps> = ({ active, error, activeText }) => {
  if (active) {
    return (
      <Alert
        type="success"
        showIcon
        icon={<LoadingOutlined spin />}
        style={{ marginTop: 16 }}
        title={`${activeText}，进度见右上角后台任务（可切换菜单，任务后台运行）`}
      />
    )
  }
  if (error) {
    return (
      <Alert
        type="error"
        showIcon
        style={{ marginTop: 16 }}
        title={`生成失败：${error}，可重新发起`}
      />
    )
  }
  return null
}
