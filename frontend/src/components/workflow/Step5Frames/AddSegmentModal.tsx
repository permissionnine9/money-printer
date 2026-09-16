/**
 * 插入分片弹窗组件
 */
import React from 'react'
import { Modal, Form, Typography } from 'antd'
import { PlusOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { SegmentForm } from './SegmentForm'

const { Text } = Typography

interface AddSegmentModalProps {
  visible: boolean
  insertAfterIndex: number
  form: ReturnType<typeof Form.useForm>[0]
  loading: boolean
  onOk: () => void
  onCancel: () => void
}

export const AddSegmentModal: React.FC<AddSegmentModalProps> = ({
  visible,
  insertAfterIndex,
  form,
  loading,
  onOk,
  onCancel,
}) => {
  return (
    <Modal
      title={
        <span>
          <PlusOutlined style={{ marginRight: 8 }} />
          插入新分片
        </span>
      }
      open={visible}
      onOk={onOk}
      onCancel={onCancel}
      okText="添加"
      cancelText="取消"
      confirmLoading={loading}
      width={700}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          {insertAfterIndex === -1
            ? '将在所有分片末尾添加新分片'
            : `将在分片 ${insertAfterIndex + 1} 之后插入新分片`}
        </Text>
      </div>
      <SegmentForm form={form} />
      <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
        <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
        <Text type="warning" style={{ fontSize: 12 }}>
          注意：插入新分片后，已有的首尾帧和视频数据将被清空，需要重新生成
        </Text>
      </div>
    </Modal>
  )
}
