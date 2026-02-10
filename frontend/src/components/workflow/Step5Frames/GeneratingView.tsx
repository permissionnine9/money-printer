/**
 * 生成中/后台生成状态视图组件
 */
import React from 'react'
import { Card, Button, Spin, Typography } from 'antd'
import { LoadingOutlined, UndoOutlined } from '@ant-design/icons'

const { Text } = Typography

interface GeneratingViewProps {
  onReset: () => void
}

export const GeneratingView: React.FC<GeneratingViewProps> = ({ onReset }) => {
  return (
    <Card
      title={
        <span>
          <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          首尾帧生成中...
        </span>
      }
      extra={
        <Button
          icon={<UndoOutlined />}
          onClick={onReset}
        >
          重置
        </Button>
      }
      style={{ marginTop: 16 }}
    >
      <div style={{ textAlign: 'center', padding: '40px 0' }}>
        <Spin size="large" />
        <div style={{ marginTop: 16 }}>
          <Text type="secondary">正在生成首尾帧，请稍候...</Text>
        </div>
      </div>
    </Card>
  )
}
