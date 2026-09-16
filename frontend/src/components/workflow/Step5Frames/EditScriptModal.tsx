/**
 * 编辑分片脚本弹窗组件
 */
import React from 'react'
import { Modal, Form, Typography } from 'antd'
import { EditOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import { SegmentForm } from './SegmentForm'

const { Text } = Typography

interface EditScriptModalProps {
  visible: boolean
  editingSegmentIndex: number | null
  form: ReturnType<typeof Form.useForm>[0]
  loading: boolean
  onOk: () => void
  onCancel: () => void
}

export const EditScriptModal: React.FC<EditScriptModalProps> = ({
  visible,
  editingSegmentIndex,
  form,
  loading,
  onOk,
  onCancel,
}) => {
  return (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          编辑分片 {editingSegmentIndex !== null ? editingSegmentIndex + 1 : ''} 脚本
        </span>
      }
      open={visible}
      onOk={onOk}
      onCancel={onCancel}
      okText="保存"
      cancelText="取消"
      confirmLoading={loading}
      width={700}
    >
      <SegmentForm form={form} />
      <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
        <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
        <Text type="warning" style={{ fontSize: 12 }}>
          注意：修改分片脚本后，该分片的首尾帧需要重新生成以保持内容一致
        </Text>
      </div>
    </Modal>
  )
}
