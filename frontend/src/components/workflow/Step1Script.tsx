/**
 * 步骤1：提交脚本
 */
import React, { useState } from 'react'
import { Card, Form, Input, Select, Button, Space, message, Modal } from 'antd'
import { SendOutlined, EditOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import type { VideoParams, SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { TextArea } = Input
const { Option } = Select

interface Step1ScriptProps {
  session: SessionDetail
}

export const Step1Script: React.FC<Step1ScriptProps> = ({ session }) => {
  const [form] = Form.useForm()
  const [loading, setLoading] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const { refreshSession } = useSessionStore()

  // 检查是否已完成此步骤
  const isCompleted = session.completed_steps?.includes('submit_script_and_params')
  const stepResult = session.step_results?.submit_script_and_params?.result_data

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step => 
    ['optimize_script', 'generate_material_images', 'generate_segment_scripts', 
     'generate_segment_frames', 'generate_videos'].includes(step)
  ).length || 0

  const handleSubmit = async (values: { script: string } & VideoParams) => {
    setLoading(true)
    try {
      const { script, ...params } = values
      const response = await stepApi.submitScript(session.session_id, script, params)
      if (response.success) {
        message.success(response.message)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleResubmit = async (values: { script: string } & VideoParams) => {
    // 如果有后续步骤已完成，显示确认对话框
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新提交？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新提交将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {session.completed_steps?.includes('optimize_script') && <li>步骤2：优化脚本</li>}
              {session.completed_steps?.includes('generate_material_images') && <li>步骤3：生成素材图</li>}
              {session.completed_steps?.includes('generate_segment_scripts') && <li>步骤4：生成分片脚本</li>}
              {session.completed_steps?.includes('generate_segment_frames') && <li>步骤5：生成首尾帧</li>}
              {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
            </ul>
            <p>此操作不可撤销，是否继续？</p>
          </div>
        ),
        onOk: async () => {
          await executeResubmit(values)
        },
      })
    } else {
      await executeResubmit(values)
    }
  }

  const executeResubmit = async (values: { script: string } & VideoParams) => {
    setLoading(true)
    try {
      const { script, ...params } = values
      const response = await stepApi.resubmitScript(session.session_id, script, params)
      if (response.success) {
        message.success(response.message)
        setIsEditing(false)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const startEditing = () => {
    setIsEditing(true)
    // 设置表单初始值为当前数据
    form.setFieldsValue({
      script: stepResult?.original_script || '',
      resolution: stepResult?.video_params?.resolution || '1080p',
      aspect_ratio: stepResult?.video_params?.aspect_ratio || '16:9',
      language: stepResult?.video_params?.language || '中文',
      style: stepResult?.video_params?.style || '现实主义',
      camera_view: stepResult?.video_params?.perspective || '第三人称',
    })
  }

  const cancelEditing = () => {
    setIsEditing(false)
    form.resetFields()
  }

  // 已完成状态且不在编辑模式 - 显示结果和重新编辑按钮
  if (isCompleted && stepResult && !isEditing) {
    return (
      <Card 
        title="脚本已提交" 
        style={{ marginTop: 16 }}
        extra={
          <Button 
            type="primary" 
            icon={<EditOutlined />}
            onClick={startEditing}
          >
            重新编辑
          </Button>
        }
      >
        <div style={{ marginBottom: 16 }}>
          <strong>原始脚本：</strong>
          <div
            style={{
              background: '#f5f5f5',
              padding: 12,
              borderRadius: 4,
              whiteSpace: 'pre-wrap',
              maxHeight: 300,
              overflow: 'auto',
            }}
          >
            {stepResult.original_script}
          </div>
        </div>
        <div>
          <strong>视频参数：</strong>
          <div style={{ marginTop: 8 }}>
            <Space wrap>
              <span>分辨率: {stepResult.video_params?.resolution || '1080p'}</span>
              <span>宽高比: {stepResult.video_params?.aspect_ratio || '16:9'}</span>
              <span>语言: {stepResult.video_params?.language || '中文'}</span>
              <span>风格: {stepResult.video_params?.style || '现实主义'}</span>
              <span>视角: {stepResult.video_params?.perspective || '第三人称'}</span>
            </Space>
          </div>
        </div>
        {completedSubsequentSteps > 0 && (
          <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <span style={{ color: '#ad6800' }}>
              后续已完成 {completedSubsequentSteps} 个步骤，重新编辑将重置这些步骤
            </span>
          </div>
        )}
      </Card>
    )
  }

  // 编辑模式或未完成状态 - 显示表单
  return (
    <Card 
      title={isEditing ? "重新编辑脚本和参数" : "提交脚本和参数"} 
      style={{ marginTop: 16 }}
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={isEditing ? handleResubmit : handleSubmit}
        initialValues={
          isEditing
            ? {
                script: stepResult?.original_script || '',
                resolution: stepResult?.video_params?.resolution || '1080p',
                aspect_ratio: stepResult?.video_params?.aspect_ratio || '16:9',
                language: stepResult?.video_params?.language || '中文',
                style: stepResult?.video_params?.style || '现实主义',
                camera_view: stepResult?.video_params?.perspective || '第三人称',
              }
            : {
                resolution: '1080p',
                aspect_ratio: '16:9',
                language: '中文',
                style: '现实主义',
                camera_view: '第三人称',
              }
        }
      >
        <Form.Item
          name="script"
          label="视频脚本"
          rules={[{ required: true, message: '请输入视频脚本' }]}
        >
          <TextArea
            rows={10}
            placeholder="请输入您的视频脚本，AI将自动优化并生成视频..."
          />
        </Form.Item>

        <Space wrap style={{ marginBottom: 16 }}>
          <Form.Item name="resolution" label="分辨率" style={{ marginBottom: 0 }}>
            <Select style={{ width: 120 }}>
              <Option value="720p">720p</Option>
              <Option value="1080p">1080p</Option>
              <Option value="4K">4K</Option>
            </Select>
          </Form.Item>

          <Form.Item name="aspect_ratio" label="宽高比" style={{ marginBottom: 0 }}>
            <Select style={{ width: 120 }}>
              <Option value="16:9">16:9</Option>
              <Option value="4:3">4:3</Option>
              <Option value="1:1">1:1</Option>
              <Option value="9:16">9:16</Option>
              <Option value="21:9">21:9</Option>
            </Select>
          </Form.Item>

          <Form.Item name="language" label="语言" style={{ marginBottom: 0 }}>
            <Select style={{ width: 120 }}>
              <Option value="中文">中文</Option>
              <Option value="英文">英文</Option>
            </Select>
          </Form.Item>

          <Form.Item name="style" label="风格" style={{ marginBottom: 0 }}>
            <Select style={{ width: 150 }}>
              <Option value="现实主义">现实主义</Option>
              <Option value="动画风格">动画风格</Option>
              <Option value="赛博朋克">赛博朋克</Option>
              <Option value="水彩风格">水彩风格</Option>
              <Option value="油画风格">油画风格</Option>
            </Select>
          </Form.Item>

          <Form.Item name="camera_view" label="视角" style={{ marginBottom: 0 }}>
            <Select style={{ width: 150 }}>
              <Option value="第一人称">第一人称</Option>
              <Option value="第三人称">第三人称</Option>
              <Option value="上帝视角">上帝视角</Option>
            </Select>
          </Form.Item>
        </Space>

        <Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SendOutlined />}
              loading={loading}
              size="large"
            >
              {isEditing ? '重新提交' : '提交脚本'}
            </Button>
            {isEditing && (
              <Button size="large" onClick={cancelEditing}>
                取消编辑
              </Button>
            )}
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}
