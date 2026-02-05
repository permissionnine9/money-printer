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
  Checkbox,
  Alert,
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
  PlusOutlined,
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
  const [addModalVisible, setAddModalVisible] = useState(false)
  const [insertAfterIndex, setInsertAfterIndex] = useState<number>(-1)
  const [selectedIndices, setSelectedIndices] = useState<number[]>([])
  const [batchModalVisible, setBatchModalVisible] = useState(false)
  const [batchPrompt, setBatchPrompt] = useState('')
  const [batchLoading, setBatchLoading] = useState(false)
  const [form] = Form.useForm()
  const [addForm] = Form.useForm()
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

  // 显示添加分片弹窗
  const showAddModal = (afterIndex: number) => {
    setInsertAfterIndex(afterIndex)
    addForm.resetFields()
    // 设置默认值
    addForm.setFieldsValue({
      duration: 5,
    })
    setAddModalVisible(true)
  }

  // 处理添加分片
  const handleAddSegment = async () => {
    try {
      const values = await addForm.validateFields()
      setLoading(true)

      const response = await segmentApi.add(session.session_id, values, insertAfterIndex)
      if (response.success) {
        message.success(response.message)
        setAddModalVisible(false)
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

  // 处理勾选分片
  const handleCheckboxChange = (index: number, checked: boolean) => {
    if (checked) {
      setSelectedIndices([...selectedIndices, index].sort((a, b) => a - b))
    } else {
      setSelectedIndices(selectedIndices.filter(i => i !== index))
    }
  }

  // 显示批量修改弹窗
  const showBatchModal = () => {
    if (selectedIndices.length === 0) {
      message.warning('请先选择要修改的分片')
      return
    }
    setBatchPrompt('')
    setBatchModalVisible(true)
  }

  // 处理批量修改
  const handleBatchRegenerate = async () => {
    try {
      setBatchLoading(true)

      const response = await segmentApi.batchRegenerate(
        session.session_id,
        selectedIndices,
        batchPrompt || undefined
      )

      if (response.success) {
        message.success(response.message)
        setSelectedIndices([])
        setBatchModalVisible(false)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setBatchLoading(false)
    }
  }

  // 批量删除
  const handleBatchDelete = () => {
    if (selectedIndices.length === 0) {
      message.warning('请先选择要删除的分片')
      return
    }

    Modal.confirm({
      title: '确认批量删除？',
      icon: <ExclamationCircleOutlined />,
      content: `将删除 ${selectedIndices.length} 个分片，此操作不可撤销。`,
      onOk: async () => {
        setLoading(true)
        try {
          // 从后往前删除，避免索引变化问题
          for (const index of selectedIndices.sort((a, b) => b - a)) {
            await segmentApi.delete(session.session_id, index)
          }
          message.success('批量删除成功')
          setSelectedIndices([])
          await refreshSession()
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
    })
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

  // 添加分片弹窗
  const addSegmentModal = (
    <Modal
      title={
        <span>
          <PlusOutlined style={{ marginRight: 8 }} />
          插入新分片
        </span>
      }
      open={addModalVisible}
      onOk={handleAddSegment}
      onCancel={() => setAddModalVisible(false)}
      okText="添加"
      cancelText="取消"
      width={700}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          {insertAfterIndex === -1
            ? '将在所有分片末尾添加新分片'
            : `将在分片 ${insertAfterIndex + 1} 之后插入新分片`}
        </Text>
      </div>
      <Form form={addForm} layout="vertical">
        <Form.Item
          name="content"
          label="分片内容"
          rules={[{ required: true, message: '请输入分片内容' }]}
        >
          <TextArea
            rows={4}
            placeholder="描述这个镜头的内容..."
          />
        </Form.Item>
        <Form.Item
          name="duration"
          label="时长(秒)"
          rules={[{ required: true, message: '请输入时长' }]}
        >
          <InputNumber min={1} max={10} style={{ width: '100%' }} />
        </Form.Item>
        <Space style={{ width: '100%' }} size="large">
          <Form.Item name="action" label="动作" style={{ marginBottom: 0, flex: 1 }}>
            <Input placeholder="例如：奔跑、转身..." />
          </Form.Item>
          <Form.Item name="camera_movement" label="镜头运动" style={{ marginBottom: 0, flex: 1 }}>
            <Input placeholder="例如：推镜、横摇..." />
          </Form.Item>
        </Space>
        <Space style={{ width: '100%' }} size="large">
          <Form.Item name="composition" label="构图" style={{ marginBottom: 0, flex: 1 }}>
            <Input placeholder="例如：中景、特写..." />
          </Form.Item>
          <Form.Item name="atmosphere" label="氛围" style={{ marginBottom: 0, flex: 1 }}>
            <Input placeholder="例如：紧张、欢快..." />
          </Form.Item>
        </Space>
      </Form>
      <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
        <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
        <Text type="warning" style={{ fontSize: 12 }}>
          注意：插入新分片后，后续步骤（首尾帧、视频生成）的数据将被清空
        </Text>
      </div>
    </Modal>
  )

  // 批量修改弹窗
  const batchRegenerateModal = (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          批量修改分片
        </span>
      }
      open={batchModalVisible}
      onOk={handleBatchRegenerate}
      onCancel={() => !batchLoading && setBatchModalVisible(false)}
      okText="确认批量修改"
      cancelText="取消"
      confirmLoading={batchLoading}
      cancelButtonProps={{ disabled: batchLoading }}
      closable={!batchLoading}
      maskClosable={!batchLoading}
      width={700}
    >
      <Spin spinning={batchLoading} tip="正在批量修改分片...">
        <div style={{ marginBottom: 16 }}>
          <Text strong>已选中 {selectedIndices.length} 个分片：</Text>
          <div style={{ marginTop: 8, padding: 12, background: '#f5f5f5', borderRadius: 4, maxHeight: 200, overflow: 'auto' }}>
            {selectedIndices.map(idx => {
              const seg = segments[idx]
              return (
                <div key={idx} style={{ marginBottom: 8 }}>
                  <Tag color="blue">分片 {idx + 1}</Tag>
                  <Text ellipsis>{seg?.content?.substring(0, 60)}...</Text>
                </div>
              )
            })}
          </div>
        </div>

        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            输入自定义提示词，告诉 LLM 如何修改这些分片（可选）
          </Text>
        </div>

        <TextArea
          value={batchPrompt}
          onChange={(e) => setBatchPrompt(e.target.value)}
          placeholder="例如：&#10;- 增加更多动作细节&#10;- 改为第一人称视角&#10;- 增加悬疑氛围&#10;- 控制每个分片不超过6秒"
          rows={6}
          style={{ marginBottom: 16 }}
          disabled={batchLoading}
        />

        <Alert
          message="重要提示"
          description={
            <div>
              <p>• LLM 可能会改变分片数量（增加或减少），以更好地表达内容</p>
              <p>• 修改后会保留前后未选中的分片，保证整体连贯性</p>
              <p>• 后续步骤（首尾帧、视频生成）的数据将被清空</p>
            </div>
          }
          type="warning"
          showIcon
        />
      </Spin>
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

          {/* 批量操作栏 */}
          {selectedIndices.length > 0 && (
            <div style={{ marginBottom: 16, padding: 12, background: '#e6f7ff', borderRadius: 4, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Text strong>已选中 {selectedIndices.length} 个分片</Text>
              <Space>
                <Button
                  type="primary"
                  icon={<EditOutlined />}
                  onClick={showBatchModal}
                >
                  批量修改
                </Button>
                <Button
                  danger
                  icon={<DeleteOutlined />}
                  onClick={handleBatchDelete}
                >
                  批量删除
                </Button>
                <Button onClick={() => setSelectedIndices([])}>
                  取消选择
                </Button>
              </Space>
            </div>
          )}

          <div>
            {segments.map((segment, index) => (
              <div key={index}>
                {/* 插入按钮（在每个分片之间） */}
                {index > 0 && (
                  <div style={{ textAlign: 'center', margin: '8px 0' }}>
                    <Button
                      type="dashed"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={() => showAddModal(index - 1)}
                      style={{ borderStyle: 'dashed', color: '#1890ff' }}
                    >
                      插入分片
                    </Button>
                  </div>
                )}

                {/* 分片折叠面板 */}
                <Collapse
                  items={[{
                    key: index,
                    label: (
                      <Space>
                        <Checkbox
                          checked={selectedIndices.includes(index)}
                          onChange={(e) => {
                            e.stopPropagation()
                            handleCheckboxChange(index, e.target.checked)
                          }}
                          onClick={(e) => e.stopPropagation()}
                        />
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
                  }]}
                />
              </div>
            ))}

            {/* 末尾插入按钮 */}
            <div style={{ textAlign: 'center', margin: '16px 0' }}>
              <Button
                type="dashed"
                icon={<PlusOutlined />}
                onClick={() => showAddModal(-1)}
                style={{ borderStyle: 'dashed', color: '#1890ff' }}
              >
                在末尾添加分片
              </Button>
            </div>
          </div>
        </Card>
        {promptModal}
        {addSegmentModal}
        {batchRegenerateModal}
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
