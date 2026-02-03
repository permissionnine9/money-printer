/**
 * 步骤5：生成首尾帧
 */
import React, { useState } from 'react'
import {
  Card,
  Button,
  message,
  Spin,
  Typography,
  Row,
  Col,
  Image,
  Space,
  Upload,
  Tag,
  Modal,
} from 'antd'
import {
  BorderOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  UploadOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi, frameApi, uploadApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography

// 辅助函数：处理图片路径，支持本地路径和完整URL
const getImageSrc = (path: string | undefined): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `/${path}`
}

interface Step5FramesProps {
  session: SessionDetail
}

export const Step5Frames: React.FC<Step5FramesProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const { refreshSession } = useSessionStore()

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('generate_segment_scripts')
  const isCompleted = session.completed_steps?.includes('generate_segment_frames')
  const stepResult = session.step_results?.generate_segment_frames?.result_data
  const frames = stepResult?.segment_frames || []

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step => 
    ['generate_videos'].includes(step)
  ).length || 0

  const handleGenerate = async () => {
    setLoading(true)
    try {
      const response = await stepApi.generateFrames(session.session_id)
      if (response.success) {
        message.success(response.message)
        // 首尾帧生成是异步的，会通过轮询更新
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerateAll = async () => {
    // 如果有后续步骤已完成，显示确认对话框
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新生成全部首尾帧？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
            </ul>
            <p>此操作不可撤销，是否继续？</p>
          </div>
        ),
        onOk: async () => {
          await executeRegenerateAll()
        },
      })
    } else {
      await executeRegenerateAll()
    }
  }

  const executeRegenerateAll = async () => {
    setLoading(true)
    try {
      const response = await stepApi.regenerateFrames(session.session_id)
      if (response.success) {
        message.success(response.message)
        // 首尾帧生成是异步的，会通过轮询更新
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerate = async (segmentIndex: number, frameType: 'first' | 'last') => {
    const key = `${segmentIndex}-${frameType}`
    setActionLoading(key)
    try {
      const response = await frameApi.regenerate(session.session_id, segmentIndex, frameType)
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

  const handleUpload = async (
    segmentIndex: number,
    frameType: 'first' | 'last',
    file: File
  ) => {
    const key = `upload-${segmentIndex}-${frameType}`
    setActionLoading(key)
    try {
      // 先上传文件
      const uploadResult = await uploadApi.uploadImage(file)
      // 再更新帧
      const response = await frameApi.upload(
        session.session_id,
        segmentIndex,
        frameType,
        uploadResult.file_path
      )
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

  if (!canExecute) {
    return (
      <Card title="生成首尾帧" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤4：生成分片脚本</Text>
      </Card>
    )
  }

  if (isCompleted && frames.length > 0) {
    return (
      <Card
        title={
          <span>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
            首尾帧生成完成 ({frames.length} 个分片)
          </span>
        }
        extra={
          <Button 
            type="primary"
            icon={<ReloadOutlined />} 
            onClick={handleRegenerateAll} 
            loading={loading}
          >
            全部重新生成
          </Button>
        }
        style={{ marginTop: 16 }}
      >
        {completedSubsequentSteps > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <span style={{ color: '#ad6800' }}>
              后续已完成 {completedSubsequentSteps} 个步骤，全部重新生成将重置这些步骤
            </span>
          </div>
        )}
        <Row gutter={[16, 24]}>
          {frames.map((frame: any, index: number) => (
            <Col span={24} key={index}>
              <Card size="small" title={<Tag color="blue">分片 {index + 1}</Tag>}>
                <Row gutter={16}>
                  <Col span={12}>
                    <div style={{ textAlign: 'center' }}>
                      <Text strong>首帧</Text>
                      <div style={{ marginTop: 8 }}>
                        {frame.first_image_path ? (
                          <Image
                            src={getImageSrc(frame.first_image_path)}
                            alt={`分片${index + 1}首帧`}
                            style={{ maxHeight: 200 }}
                            fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                          />
                        ) : (
                          <div
                            style={{
                              height: 150,
                              background: '#f5f5f5',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <Spin tip="生成中..." />
                          </div>
                        )}
                      </div>
                      <Space style={{ marginTop: 8 }}>
                        <Button
                          size="small"
                          icon={<ReloadOutlined />}
                          onClick={() => handleRegenerate(index, 'first')}
                          loading={actionLoading === `${index}-first`}
                        >
                          重新生成
                        </Button>
                        <Upload
                          showUploadList={false}
                          beforeUpload={(file) => {
                            handleUpload(index, 'first', file)
                            return false
                          }}
                          accept="image/*"
                        >
                          <Button
                            size="small"
                            icon={<UploadOutlined />}
                            loading={actionLoading === `upload-${index}-first`}
                          >
                            上传替换
                          </Button>
                        </Upload>
                      </Space>
                    </div>
                  </Col>
                  <Col span={12}>
                    <div style={{ textAlign: 'center' }}>
                      <Text strong>尾帧</Text>
                      <div style={{ marginTop: 8 }}>
                        {frame.last_image_path ? (
                          <Image
                            src={getImageSrc(frame.last_image_path)}
                            alt={`分片${index + 1}尾帧`}
                            style={{ maxHeight: 200 }}
                            fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                          />
                        ) : (
                          <div
                            style={{
                              height: 150,
                              background: '#f5f5f5',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <Spin tip="生成中..." />
                          </div>
                        )}
                      </div>
                      <Space style={{ marginTop: 8 }}>
                        <Button
                          size="small"
                          icon={<ReloadOutlined />}
                          onClick={() => handleRegenerate(index, 'last')}
                          loading={actionLoading === `${index}-last`}
                        >
                          重新生成
                        </Button>
                        <Upload
                          showUploadList={false}
                          beforeUpload={(file) => {
                            handleUpload(index, 'last', file)
                            return false
                          }}
                          accept="image/*"
                        >
                          <Button
                            size="small"
                            icon={<UploadOutlined />}
                            loading={actionLoading === `upload-${index}-last`}
                          >
                            上传替换
                          </Button>
                        </Upload>
                      </Space>
                    </div>
                  </Col>
                </Row>
              </Card>
            </Col>
          ))}
        </Row>
      </Card>
    )
  }

  // 正在生成中
  if (stepResult && !isCompleted) {
    return (
      <Card title="首尾帧生成中..." style={{ marginTop: 16 }}>
        <Spin tip="正在生成首尾帧，请稍候...">
          <div style={{ padding: 50, textAlign: 'center' }}>
            <BorderOutlined style={{ fontSize: 48, color: '#999' }} />
          </div>
        </Spin>
      </Card>
    )
  }

  return (
    <Card title="生成首尾帧" style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Text>基于素材图（图生图），为每个分片生成首尾帧，确保角色/物品一致性。</Text>
      </div>
      <Spin spinning={loading}>
        <Button
          type="primary"
          icon={<BorderOutlined />}
          onClick={handleGenerate}
          loading={loading}
          size="large"
        >
          开始生成首尾帧
        </Button>
      </Spin>
    </Card>
  )
}
