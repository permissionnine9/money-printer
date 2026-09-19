/**
 * 统一提示词查看弹窗：展示本次 Agent run 的最终渲染提示词（system/user 分页签，支持复制）
 */
import React from 'react'
import { Button, Modal, Space, Tabs, Tag, Typography, message } from 'antd'
import { CopyOutlined } from '@ant-design/icons'

const { Text } = Typography

export interface PromptViewerModalProps {
  open: boolean
  onClose: () => void
  systemPrompt?: string
  userPrompt?: string
  model?: string
}

export const PromptViewerModal: React.FC<PromptViewerModalProps> = ({ open, onClose, systemPrompt, userPrompt, model }) => {
  const renderSection = (content: string) => (
    <div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 4 }}>
        <Space size={8}>
          <Text type="secondary" style={{ fontSize: 12 }}>{content.length} 字符</Text>
          <Button
            size="small"
            icon={<CopyOutlined />}
            onClick={() => {
              navigator.clipboard
                .writeText(content)
                .then(() => message.success('已复制'))
                .catch(() => message.error('复制失败'))
            }}
          >
            复制
          </Button>
        </Space>
      </div>
      <pre
        style={{
          margin: 0,
          fontSize: 12,
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
          maxHeight: '55vh',
          overflow: 'auto',
          background: '#fafafa',
          border: '1px solid #f0f0f0',
          borderRadius: 6,
          padding: 12,
        }}
      >
        {content}
      </pre>
    </div>
  )

  const items = [
    { key: 'user', label: '用户提示词', children: renderSection(userPrompt || '') },
    ...(systemPrompt ? [{ key: 'system', label: '系统提示词', children: renderSection(systemPrompt) }] : []),
  ]

  return (
    <Modal
      open={open}
      onCancel={onClose}
      footer={null}
      width={860}
      destroyOnHidden
      title={
        <Space>
          Agent 提示词
          {model && <Tag>{model}</Tag>}
        </Space>
      }
    >
      <Tabs defaultActiveKey="user" items={items} />
    </Modal>
  )
}

export default PromptViewerModal
