/**
 * 步骤4：生成分片脚本
 */
import React, { useState } from 'react'
import {
  Card,
  Button,
  message,
  Spin,
  Typography,
  Form,
  Input,
  InputNumber,
  Space,
  Collapse,
  Popconfirm,
  Tag,
  Modal,
} from 'antd'
import {
  ScissorOutlined,
  CheckCircleOutlined,
  EditOutlined,
  DeleteOutlined,
  SaveOutlined,
  CloseOutlined,
  ReloadOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { SessionDetail, ScriptSegment } from '@/types'
import { stepApi, segmentApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { Text, Paragraph } = Typography
const { TextArea } = Input

interface Step4SegmentsProps {
  session: SessionDetail
}

export const Step4Segments: React.FC<Step4SegmentsProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [promptModalVisible, setPromptModalVisible] = useState(false)
  const [extraPrompt, setExtraPrompt] = useState('')
  const [isRegenerate, setIsRegenerate] = useState(false)
  const [form] = Form.useForm()
  const { refreshSession } = useSessionStore()

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('generate_material_images')
  const isCompleted = session.completed_steps?.includes('generate_segment_scripts')
  const stepResult = session.step_results?.generate_segment_scripts?.result_data
  const segments: ScriptSegment[] = stepResult?.segment_scripts || []

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_segment_frames', 'generate_videos'].includes(step)
  ).length || 0

  // 打开提示词输入弹窗
  const showPromptModal = (regenerate: boolean) => {
    setIsRegenerate(regenerate)
    setExtraPrompt('')
    setPromptModalVisible(true)
  }

  // 执行生成（带可选的自定义提示词）
  const executeGenerate = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.generateSegments(session.session_id, prompt || undefined)
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

  // 执行重新生成（带可选的自定义提示词）
  const executeRegenerate = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.regenerateSegments(session.session_id, prompt || undefined)
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

  // 处理弹窗确认
  const handlePromptModalOk = () => {
    if (isRegenerate) {
      // 如果是重新生成，需要检查后续步骤
      if (completedSubsequentSteps > 0) {
        Modal.confirm({
          title: '确认重新生成分片脚本？',
          icon: <ExclamationCircleOutlined />,
          content: (
            <div>
              <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
              <ul>
                {session.completed_steps?.includes('generate_segment_frames') && <li>步骤5：生成首尾帧</li>}
                {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
              </ul>
              <p>此操作不可撤销，是否继续？</p>
            </div>
          ),
          onOk: () => executeRegenerate(extraPrompt),
        })
      } else {
        executeRegenerate(extraPrompt)
      }
    } else {
      executeGenerate(extraPrompt)
    }
  }

  const handleGenerate = () => {
    showPromptModal(false)
  }

  const handleRegenerate = () => {
    showPromptModal(true)
  }

  const handleEdit = (index: number, segment: ScriptSegment) => {
    setEditingIndex(index)
    form.setFieldsValue(segment)
  }

  const handleCancelEdit = () => {
    setEditingIndex(null)
    form.resetFields()
  }

  const handleSave = async (index: number) => {
    try {
      const values = await form.validateFields()
      setActionLoading(index)
      // 确保传递 index 到后端
      const response = await segmentApi.update(session.session_id, index, { ...values, index })
      if (response.success) {
        message.success(response.message)
        setEditingIndex(null)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setActionLoading(null)
    }
  }

  const handleDelete = async (index: number) => {
    setActionLoading(index)
    try {
      const response = await segmentApi.delete(session.session_id, index)
      if (response.success) {
        message.success(response.message)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setActionLoading(null)
    }
  }

  // 提示词输入弹窗
  const promptModal = (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          {isRegenerate ? '重新生成分片脚本' : '生成分片脚本'} - 自定义提示词
        </span>
      }
      open={promptModalVisible}
      onOk={handlePromptModalOk}
      onCancel={() => setPromptModalVisible(false)}
      okText={isRegenerate ? '开始重新生成' : '开始生成'}
      cancelText="取消"
      width={600}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          输入自定义提示词来控制分片生成的方向和风格（可选，留空则使用默认策略）
        </Text>
      </div>
      <TextArea
        value={extraPrompt}
        onChange={(e) => setExtraPrompt(e.target.value)}
        placeholder="例如：&#10;- 增加更多动作细节描述&#10;- 控制每个分片的时长不超过6秒&#10;- 强调镜头运动的多样性&#10;- 增加特定的拍摄角度要求"
        rows={6}
        style={{ marginBottom: 16 }}
      />
      <div style={{ padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          提示：自定义提示词将影响 LLM 对脚本的分片方式和细节描述。您可以指定分片策略、镜头要求、时长控制等。
        </Text>
      </div>
    </Modal>
  )

  if (!canExecute) {
    return (
      <Card title="生成分片脚本" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤3：生成素材图</Text>
      </Card>
    )
  }

  if (isCompleted && segments.length > 0) {
    return (
      <>
        <Card
          title={
            <span>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
              分片脚本生成完成 ({segments.length} 个分片)
            </span>
          }
          style={{ marginTop: 16 }}
          extra={
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={handleRegenerate}
              loading={loading}
            >
              重新生成分片
            </Button>
          }
        >
          {completedSubsequentSteps > 0 && (
            <div style={{ marginBottom: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
              <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
              <span style={{ color: '#ad6800' }}>
                后续已完成 {completedSubsequentSteps} 个步骤，重新生成将重置这些步骤
              </span>
            </div>
          )}
          <Collapse
            items={segments.map((segment, index) => ({
            key: index,
            label: (
              <Space>
                <Tag color="blue">分片 {index + 1}</Tag>
                <span>{segment.duration}秒</span>
                <Text ellipsis style={{ maxWidth: 400 }}>
                  {segment.content?.substring(0, 50)}...
                </Text>
              </Space>
            ),
            extra: editingIndex !== index && (
              <Space onClick={(e) => e.stopPropagation()}>
                <Button
                  type="text"
                  icon={<EditOutlined />}
                  onClick={() => handleEdit(index, segment)}
                />
                <Popconfirm
                  title="确定删除此分片？"
                  onConfirm={() => handleDelete(index)}
                  okText="确定"
                  cancelText="取消"
                >
                  <Button
                    type="text"
                    danger
                    icon={<DeleteOutlined />}
                    loading={actionLoading === index}
                  />
                </Popconfirm>
              </Space>
            ),
            children:
              editingIndex === index ? (
                <Form form={form} layout="vertical">
                  <Form.Item name="content" label="内容" rules={[{ required: true }]}>
                    <TextArea rows={4} />
                  </Form.Item>
                  <Space>
                    <Form.Item name="duration" label="时长(秒)" style={{ marginBottom: 0 }}>
                      <InputNumber min={1} max={10} />
                    </Form.Item>
                    <Form.Item name="action" label="动作" style={{ marginBottom: 0 }}>
                      <Input />
                    </Form.Item>
                    <Form.Item name="camera_movement" label="镜头运动" style={{ marginBottom: 0 }}>
                      <Input />
                    </Form.Item>
                  </Space>
                  <div style={{ marginTop: 16 }}>
                    <Space>
                      <Button
                        type="primary"
                        icon={<SaveOutlined />}
                        onClick={() => handleSave(index)}
                        loading={actionLoading === index}
                      >
                        保存
                      </Button>
                      <Button icon={<CloseOutlined />} onClick={handleCancelEdit}>
                        取消
                      </Button>
                    </Space>
                  </div>
                </Form>
              ) : (
                <div>
                  <Paragraph>
                    <strong>内容：</strong>
                    {segment.content}
                  </Paragraph>
                  <Space wrap>
                    {segment.action && <Tag>动作: {segment.action}</Tag>}
                    {segment.camera_movement && <Tag>镜头: {segment.camera_movement}</Tag>}
                    {segment.composition && <Tag>构图: {segment.composition}</Tag>}
                    {segment.atmosphere && <Tag>氛围: {segment.atmosphere}</Tag>}
                  </Space>
                </div>
              ),
          }))}
        />
        </Card>
        {promptModal}
      </>
    )
  }

  return (
    <>
      <Card title="生成分片脚本" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text>LLM 将把优化后的脚本切割成多个分镜头片段，每个片段8秒以内。</Text>
        </div>
        <Spin spinning={loading}>
          <Button
            type="primary"
            icon={<ScissorOutlined />}
            onClick={handleGenerate}
            loading={loading}
            size="large"
          >
            开始生成分片
          </Button>
        </Spin>
      </Card>
      {promptModal}
    </>
  )
}
