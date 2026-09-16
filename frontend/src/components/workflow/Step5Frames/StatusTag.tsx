/**
 * 帧状态标签组件
 */
import React from 'react'
import { Tag } from 'antd'
import {
  LoadingOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'

interface StatusTagProps {
  status?: string
}

export const StatusTag: React.FC<StatusTagProps> = ({ status }) => {
  switch (status) {
    case 'pending':
      return <Tag icon={<LoadingOutlined />} color="processing">生成中</Tag>
    case 'completed':
      return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>
    case 'failed':
      return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
    default:
      return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
  }
}
