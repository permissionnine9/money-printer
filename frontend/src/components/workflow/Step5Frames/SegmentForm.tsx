/**
 * 分片表单组件 - 用于新增和编辑分片
 */
import React, { memo } from 'react'
import { Form, Input, InputNumber, Space } from 'antd'
import type { SegmentFormData } from './types'

const { TextArea } = Input

interface SegmentFormProps {
  form: ReturnType<typeof Form.useForm>[0]
  initialValues?: Partial<SegmentFormData>
}

export const SegmentForm: React.FC<SegmentFormProps> = memo(({ form, initialValues }) => {
  return (
    <Form
      form={form}
      layout="vertical"
      initialValues={{ duration: 5, ...initialValues }}
    >
      <Form.Item
        name="content"
        label="分片内容"
        rules={[{ required: true, message: '请输入分片内容' }]}
      >
        <TextArea rows={4} placeholder="描述这个镜头的内容..." />
      </Form.Item>
      <Form.Item
        name="duration"
        label="时长(秒)"
        rules={[{ required: true, message: '请输入时长' }]}
      >
        <InputNumber min={1} max={10} style={{ width: '100%' }} />
      </Form.Item>
      <Space style={{ width: '100%' }} size="large">
        <Form.Item
          name="action"
          label="动作"
          style={{ marginBottom: 0, flex: 1 }}
        >
          <Input placeholder="例如：奔跑、转身..." />
        </Form.Item>
        <Form.Item
          name="camera_movement"
          label="镜头运动"
          style={{ marginBottom: 0, flex: 1 }}
        >
          <Input placeholder="例如：推镜、横摇..." />
        </Form.Item>
      </Space>
      <Space style={{ width: '100%', marginTop: 16 }} size="large">
        <Form.Item
          name="composition"
          label="构图"
          style={{ marginBottom: 0, flex: 1 }}
        >
          <Input placeholder="例如：中景、特写..." />
        </Form.Item>
        <Form.Item
          name="atmosphere"
          label="氛围"
          style={{ marginBottom: 0, flex: 1 }}
        >
          <Input placeholder="例如：紧张、欢快..." />
        </Form.Item>
      </Space>
    </Form>
  )
})

SegmentForm.displayName = 'SegmentForm'
