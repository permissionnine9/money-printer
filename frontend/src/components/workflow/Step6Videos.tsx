/**
 * 步骤6：生成视频
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 显示每个视频的生成进度
 */
import React, { useState, useMemo } from 'react'
import {
  Card,
  Button,
  message,
  Spin,
  Typography,
  Row,
  Col,
  Tag,
  Space,
  Popconfirm,
  Modal,
  Form,
  Input,
  InputNumber,
  Image,
  Descriptions,
  Collapse,
} from 'antd'
import {
  VideoCameraOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
  ExclamationCircleOutlined,
  EditOutlined,
  SaveOutlined,
  BulbOutlined,
  CopyOutlined,
} from '@ant-design/icons'
import type { SessionDetail, ScriptSegment, SegmentFrame, VideoParams } from '@/types'
import { stepApi, segmentApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'
import { LazyVideo } from '@/components/common/LazyVideo'

const { TextArea } = Input

const { Text } = Typography

// 辅助函数：处理媒体路径，支持本地路径和完整URL
const getMediaSrc = (path: string | undefined): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `/${path}`
}

interface Step6VideosProps {
  session: SessionDetail
}

export const Step6Videos: React.FC<Step6VideosProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [editModalVisible, setEditModalVisible] = useState(false)
  const [editingVideoIndex, setEditingVideoIndex] = useState<number | null>(null)
  const [editLoading, setEditLoading] = useState(false)
  const [form] = Form.useForm()
  const { refreshSession } = useSessionStore()

  // 优化提示词相关状态
  const [optimizeLoading, setOptimizeLoading] = useState(false)
  const [optimizeRequirement, setOptimizeRequirement] = useState('')
  const [optimizedPrompt, setOptimizedPrompt] = useState('')

  // 检查前置步骤是否完成（考虑步骤5的特殊模式）
  const canExecute = useMemo(() => {
    // 首先检查后端的完成标记
    if (session.completed_steps?.includes('generate_segment_frames')) {
      return true
    }
    
    // 如果没有首尾帧数据或分片数据，视为未完成
    const frames = session.step_results?.generate_segment_frames?.result_data?.segment_frames || []
    const segments = session.step_results?.generate_segment_scripts?.result_data?.segment_scripts || []
    
    if (frames.length === 0 || segments.length === 0) {
      return false
    }
    
    // 检查每个分片是否都已配置完成（考虑特殊模式）
    return frames.every((frame: SegmentFrame) => {
      const segment = segments.find((s: ScriptSegment) => s.index === frame.segment_index)
      if (!segment) return false
      
      const firstPath = frame.first_image_path
      const lastPath = frame.last_image_path
      const videoMode = segment.video_generation_mode
      const firstFrameMode = segment.first_frame_mode
      
      // 首帧+参考图模式：只需要首帧
      if (videoMode === 'first_frame_reference') {
        return !!firstPath
      }
      
      // 视频快照模式：首帧在视频生成阶段获取，只需要尾帧
      if (firstFrameMode === 'use_video_snapshot') {
        return !!lastPath
      }
      
      // 普通模式：需要首尾帧都完成
      return !!firstPath && !!lastPath
    })
  }, [session])
  const stepResult = session.step_results?.generate_videos?.result_data
  const videos = stepResult?.generated_videos || []

  // 获取分片脚本数据（用于预览视频生成信息）
  const segmentScriptsResult = session.step_results?.generate_segment_scripts?.result_data
  const segments: ScriptSegment[] = segmentScriptsResult?.segment_scripts || []

  // 获取首尾帧数据
  const framesResult = session.step_results?.generate_segment_frames?.result_data
  const segmentFrames: SegmentFrame[] = framesResult?.segment_frames || []

  // 获取视频参数
  const submitResult = session.step_results?.submit_script_and_params?.result_data
  const videoParams: VideoParams | null = submitResult?.video_params || null

  // 检查是否有正在进行的视频生成任务
  const hasPendingVideos = videos.length > 0 && videos.some((v: any) => v.task_status === 'pending')
  // 检查是否处于后台生成中状态
  const isBackgroundGenerating = stepResult?._generating === true
  // 综合判断是否正在生成
  const isGenerating = hasPendingVideos || isBackgroundGenerating || loading

  // 轮询任务状态：当有 pending 状态的视频或后台生成中时启用轮询
  usePolling(
    async () => {
      await refreshSession()
    },
    {
      interval: 3000, // 每3秒轮询一次
      enabled: hasPendingVideos || isBackgroundGenerating, // 有 pending 任务或后台生成中时启用轮询
    }
  )

  // 计算视频生成预览信息
  const calculateVideoPreviewInfo = () => {
    const totalSegments = segments.length
    let totalDuration = 0
    const segmentDetails: Array<{ index: number; content: string; duration: number }> = []

    segments.forEach((segment: any) => {
      const duration = segment.duration || 5.0
      totalDuration += duration
      segmentDetails.push({
        index: segment.index,
        content: segment.content,
        duration: duration,
      })
    })

    return { totalSegments, totalDuration, segmentDetails }
  }

  const videoPreviewInfo = calculateVideoPreviewInfo()

  const handleGenerate = async () => {
    // 显示预览对话框
    Modal.confirm({
      title: '视频生成预览',
      width: 700,
      icon: <VideoCameraOutlined />,
      content: (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>统计信息：</Text>
            <ul style={{ marginTop: 8 }}>
              <li>
                <Text>总视频数量：{videoPreviewInfo.totalSegments} 个</Text>
              </li>
              <li>
                <Text>预计总时长：约 {videoPreviewInfo.totalDuration.toFixed(1)} 秒</Text>
              </li>
              <li>
                <Text type="secondary">平均时长：约 {(videoPreviewInfo.totalDuration / (videoPreviewInfo.totalSegments || 1)).toFixed(1)} 秒/个</Text>
              </li>
            </ul>
          </div>

          {videoPreviewInfo.segmentDetails.length > 0 && (
            <div style={{ marginTop: 16, maxHeight: 300, overflowY: 'auto' }}>
              <Text strong>视频列表：</Text>
              <div style={{ marginTop: 8 }}>
                {videoPreviewInfo.segmentDetails.map((detail, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: 8,
                      marginBottom: 8,
                      background: '#fafafa',
                      borderRadius: 4,
                      border: '1px solid #f0f0f0',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong>视频 {detail.index + 1}</Text>
                      <Tag color="blue">{detail.duration} 秒</Tag>
                    </div>
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                      {detail.content.substring(0, 50)}{detail.content.length > 50 ? '...' : ''}
                    </Text>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <Text type="secondary">
              ⏱️ 提示：视频生成需要较长时间，每个视频片段约需 1-2 分钟。预计总耗时约 {Math.ceil(videoPreviewInfo.totalSegments * 1.5)} 分钟。
            </Text>
          </div>

          <div style={{ marginTop: 12, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              💡 生成过程可随时停止，已生成的视频将被保留。您可以稍后继续生成剩余视频。
            </Text>
          </div>
        </div>
      ),
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.generateVideos(session.session_id)
          if (response.success) {
            message.loading('视频生成任务已启动，正在生成中...', 2)
            // 立即刷新以获取pending状态，触发轮询
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
      okText: '确认生成',
      cancelText: '取消',
    })
  }

  const handleRegenerate = () => {
    // 二次确认对话框
    Modal.confirm({
      title: '确认重新生成所有视频？',
      icon: <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
      width: 600,
      content: (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Text>重新生成会重新创建所有视频片段，这将需要较长时间。</Text>
          </div>

          <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 4, marginBottom: 12 }}>
            <Text strong style={{ color: '#0050b3' }}>✅ 数据安全保障：</Text>
            <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
              <li>
                <Text type="secondary">当前所有视频数据会被保留为备份</Text>
              </li>
              <li>
                <Text type="secondary">如果重新生成结果不满意，可以一键恢复</Text>
              </li>
            </ul>
          </div>

          <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <Text strong style={{ color: '#d46b08' }}>⏱️ 预计耗时：</Text>
            <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
              <li>
                <Text type="secondary">每个视频约需 1-2 分钟</Text>
              </li>
              <li>
                <Text type="secondary">总计约 {Math.ceil(videos.length * 1.5)} 分钟</Text>
              </li>
            </ul>
          </div>
        </div>
      ),
      okText: '确认重新生成',
      okType: 'danger',
      cancelText: '取消',
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.regenerateVideos(session.session_id)
          if (response.success) {
            message.loading('视频重新生成任务已启动，正在生成中...', 2)
            // 立即刷新以获取pending状态，触发轮询
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
    })
  }

  const handleCancel = async () => {
    setLoading(true)
    try {
      const response = await stepApi.cancelVideos(session.session_id)
      if (response.success) {
        message.success('取消请求已发送，正在停止生成任务...')
        // 立即刷新以获取最新状态
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

  const handleRestoreBackup = () => {
    // 二次确认对话框
    Modal.confirm({
      title: '确认恢复备份的视频？',
      icon: <ExclamationCircleOutlined style={{ color: '#1890ff' }} />,
      width: 500,
      content: (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Text>将恢复到重新生成之前的状态，当前正在生成的视频会被丢弃。</Text>
          </div>

          <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text strong style={{ color: '#0050b3' }}>恢复后：</Text>
            <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
              <li>
                <Text type="secondary">所有视频立即恢复到之前的版本</Text>
              </li>
              <li>
                <Text type="secondary">可以再次尝试重新生成</Text>
              </li>
            </ul>
          </div>
        </div>
      ),
      okText: '确认恢复',
      okType: 'primary',
      cancelText: '取消',
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.restoreVideosBackup(session.session_id)
          if (response.success) {
            message.success(response.message || '备份已恢复')
            // 立即刷新以获取恢复后的状态
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
    })
  }

  // 打开视频编辑弹窗
  const handleOpenEditModal = (index: number) => {
    const segment = segments[index]
    if (segment) {
      form.setFieldsValue({
        content: segment.content,
        duration: segment.duration,
        action: segment.action,
        camera_movement: segment.camera_movement,
        composition: segment.composition,
        atmosphere: segment.atmosphere,
      })
    }
    setEditingVideoIndex(index)
    setEditModalVisible(true)
  }

  // 关闭视频编辑弹窗
  const handleCloseEditModal = () => {
    setEditModalVisible(false)
    setEditingVideoIndex(null)
    form.resetFields()
    // 重置优化提示词相关状态
    setOptimizeRequirement('')
    setOptimizedPrompt('')
  }

  // 优化分片提示词
  const handleOptimizePrompt = async () => {
    if (editingVideoIndex === null) return

    setOptimizeLoading(true)
    setOptimizedPrompt('')

    try {
      const response = await stepApi.optimizeSegmentPrompt(
        session.session_id,
        editingVideoIndex,
        optimizeRequirement
      )

      if (response.success && response.data?.optimized_prompt) {
        setOptimizedPrompt(response.data.optimized_prompt)
        message.success('提示词优化完成')
      } else {
        message.error(response.message || '优化失败')
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setOptimizeLoading(false)
    }
  }

  // 复制优化结果到剪贴板
  const handleCopyOptimizedPrompt = async () => {
    if (!optimizedPrompt) return

    try {
      await navigator.clipboard.writeText(optimizedPrompt)
      message.success('已复制到剪贴板')
    } catch {
      message.error('复制失败，请手动复制')
    }
  }

  // 保存分片脚本修改
  const handleSaveSegment = async () => {
    if (editingVideoIndex === null) return

    try {
      const values = await form.validateFields()
      setEditLoading(true)

      const response = await segmentApi.update(session.session_id, editingVideoIndex, {
        ...values,
        index: editingVideoIndex,
      })

      if (response.success) {
        message.success('分片脚本修改成功')
        await refreshSession()
        handleCloseEditModal()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setEditLoading(false)
    }
  }

  // 获取当前编辑视频的首尾帧
  const getCurrentEditFrame = (): SegmentFrame | null => {
    if (editingVideoIndex === null) return null
    return segmentFrames.find(f => f.segment_index === editingVideoIndex) || null
  }

  // 获取当前编辑的分片脚本
  const getCurrentEditSegment = (): ScriptSegment | null => {
    if (editingVideoIndex === null) return null
    return segments[editingVideoIndex] || null
  }

  // 根据 task_status 判断视频状态（优先使用 task_status）
  const getVideoStatus = (video: any): 'completed' | 'pending' | 'failed' | 'cancelled' => {
    // 优先使用 task_status
    if (video.task_status) {
      return video.task_status as 'completed' | 'pending' | 'failed' | 'cancelled'
    }
    // 兼容旧数据：根据 video_path 判断
    if (!video.video_path) return 'pending'
    if (video.video_path.startsWith('生成失败')) return 'failed'
    return 'completed'
  }

  // 渲染状态标签
  const renderStatusTag = (status: string) => {
    switch (status) {
      case 'pending':
        return <Tag icon={<LoadingOutlined />} color="processing">生成中</Tag>
      case 'completed':
        return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>
      case 'failed':
        return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
      case 'cancelled':
        return <Tag icon={<StopOutlined />} color="warning">已取消</Tag>
      default:
        return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
    }
  }

  if (!canExecute) {
    // 计算步骤5的完成状态详情
    const frames = session.step_results?.generate_segment_frames?.result_data?.segment_frames || []
    const segmentScripts = session.step_results?.generate_segment_scripts?.result_data?.segment_scripts || []
    
    const incompleteSegments: number[] = []
    frames.forEach((frame: SegmentFrame) => {
      const segment = segmentScripts.find((s: ScriptSegment) => s.index === frame.segment_index)
      if (!segment) {
        incompleteSegments.push(frame.segment_index + 1)
        return
      }
      
      const firstPath = frame.first_image_path
      const lastPath = frame.last_image_path
      const videoMode = segment.video_generation_mode
      const firstFrameMode = segment.first_frame_mode
      
      let isComplete = false
      if (videoMode === 'first_frame_reference') {
        isComplete = !!firstPath
      } else if (firstFrameMode === 'use_video_snapshot') {
        isComplete = !!lastPath
      } else {
        isComplete = !!firstPath && !!lastPath
      }
      
      if (!isComplete) {
        incompleteSegments.push(frame.segment_index + 1)
      }
    })
    
    return (
      <Card title="生成视频" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">请先完成步骤5：配置首尾帧</Text>
        </div>
        {incompleteSegments.length > 0 && (
          <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4, marginBottom: 16 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <Text type="warning">
              以下分片还需要配置帧：{incompleteSegments.join(', ')}
            </Text>
            <div style={{ marginTop: 8, fontSize: 12, color: '#666' }}>
              💡 提示：您可以在步骤5中为这些分片生成首尾帧，或将它们设置为特殊模式（如"首帧+参考图"、"使用视频快照"）
            </div>
          </div>
        )}
      </Card>
    )
  }

  // 当有视频数据时显示（包括生成中和已完成状态）
  if (videos.length > 0) {
    const completedCount = videos.filter((v: any) => getVideoStatus(v) === 'completed').length
    const failedCount = videos.filter((v: any) => getVideoStatus(v) === 'failed').length
    const cancelledCount = videos.filter((v: any) => getVideoStatus(v) === 'cancelled').length
    const pendingCount = videos.filter((v: any) => getVideoStatus(v) === 'pending').length
    const totalCount = videos.length

    // 判断是否全部完成（没有 pending 也没有正在后台生成）
    const isAllCompleted = completedCount === totalCount && !isBackgroundGenerating
    // 判断是否已被取消（有取消的视频且没有正在生成的）
    const isCancelled = cancelledCount > 0 && pendingCount === 0 && !isBackgroundGenerating

    const title = isAllCompleted ? (
      <span>
        <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
        视频生成完成 ({completedCount}/{totalCount})
      </span>
    ) : isCancelled ? (
      <span>
        <StopOutlined style={{ color: '#faad14', marginRight: 8 }} />
        视频生成已停止 ({completedCount}/{totalCount} 已完成)
        {cancelledCount > 0 && <Tag color="warning" style={{ marginLeft: 8 }}>{cancelledCount}个已取消</Tag>}
        {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
      </span>
    ) : (
      <span>
        <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
        视频生成中 ({completedCount}/{totalCount})
        {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
      </span>
    )

    // 检查是否有备份数据
    const hasBackup = stepResult?._backed_up_count > 0 || videos.some((v: any) => v._old_video_path)

    return (
      <>
        <Card
          title={title}
          extra={
            <Space>
              {isGenerating && !stepResult?._cancelled && (
                <Popconfirm
                  title="确认停止生成视频？"
                  description="已生成的视频会被保留，未生成的视频将停止。"
                  onConfirm={handleCancel}
                  okText="确认停止"
                  cancelText="取消"
                >
                  <Button
                    danger
                    icon={<StopOutlined />}
                    loading={loading}
                  >
                    停止生成
                  </Button>
                </Popconfirm>
              )}
              {hasBackup && !isGenerating && (
                <Button
                  icon={<ReloadOutlined />}
                  onClick={handleRestoreBackup}
                  loading={loading}
                  disabled={loading}
                >
                  恢复备份
                </Button>
              )}
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={handleRegenerate}
                loading={isGenerating}
                disabled={isGenerating}
              >
                {isGenerating ? '生成中...' : '重新生成'}
              </Button>
            </Space>
          }
          style={{ marginTop: 16 }}
        >
          <Row gutter={[16, 16]}>
            {videos.map((video: any, index: number) => (
              <Col xs={24} sm={12} key={index}>
                <Card
                  size="small"
                  title={
                    <span>
                      <Tag color="blue">视频 {index + 1}</Tag>
                      {renderStatusTag(getVideoStatus(video))}
                    </span>
                  }
                  extra={
                    video.video_path && !video.video_path.startsWith('生成失败') ? (
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => handleOpenEditModal(index)}
                      >
                        编辑
                      </Button>
                    ) : null
                  }
                >
                  {video.video_path && !video.video_path.startsWith('生成失败') && getVideoStatus(video) === 'completed' ? (
                    <div>
                      <LazyVideo
                        src={getMediaSrc(video.video_path)}
                        poster={video.first_frame_path ? getMediaSrc(video.first_frame_path) : undefined}
                        placeholderHeight={200}
                      />
                    </div>
                  ) : getVideoStatus(video) === 'pending' ? (
                    <div
                      style={{
                        height: 200,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: '#f5f5f5',
                      }}
                    >
                      <Spin />
                      <Text style={{ marginTop: 16 }}>视频生成中...</Text>
                    </div>
                  ) : getVideoStatus(video) === 'cancelled' ? (
                    <div
                      style={{
                        height: 200,
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: '#fffbe6',
                      }}
                    >
                      <StopOutlined style={{ fontSize: 32, color: '#faad14' }} />
                      <Text type="warning" style={{ marginTop: 8 }}>已取消</Text>
                    </div>
                  ) : (
                    <div
                      style={{
                        height: 200,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        background: '#fff2f0',
                      }}
                    >
                      <Text type="danger">生成失败</Text>
                    </div>
                  )}
                </Card>
              </Col>
            ))}
          </Row>

          {/* 完成后显示合并提示 */}
          {isAllCompleted && (
            <Card style={{ marginTop: 16, background: '#f6ffed', border: '1px solid #b7eb8f' }}>
              <div style={{ textAlign: 'center' }}>
                <CheckCircleOutlined style={{ fontSize: 32, color: '#52c41a' }} />
                <div style={{ marginTop: 8 }}>
                  <Text strong>所有视频片段生成完成！</Text>
                </div>
                <Text type="secondary">您可以下载各个视频片段，或使用视频编辑软件进行合并。</Text>
              </div>
            </Card>
          )}
        </Card>

        {/* 视频编辑弹窗 */}
        <Modal
          title={
            <span>
              <EditOutlined style={{ marginRight: 8 }} />
              编辑视频 {editingVideoIndex !== null ? editingVideoIndex + 1 : ''}
            </span>
          }
          open={editModalVisible}
          onCancel={handleCloseEditModal}
          footer={[
            <Button key="cancel" onClick={handleCloseEditModal}>
              取消
            </Button>,
            <Button
              key="regenerate"
              type="primary"
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={async () => {
                if (editingVideoIndex === null) return
                setLoading(true)
                try {
                  const response = await stepApi.regenerateSingleVideo(session.session_id, editingVideoIndex)
                  if (response.success) {
                    message.success('视频重新生成任务已启动')
                    handleCloseEditModal()
                    // 立即刷新以获取pending状态，触发轮询
                    await refreshSession()
                  } else {
                    message.error(response.message)
                  }
                } catch (error) {
                  message.error((error as Error).message)
                } finally {
                  setLoading(false)
                }
              }}
            >
              重新生成这个视频
            </Button>,
          ]}
          width={900}
          destroyOnClose
        >
          {editingVideoIndex !== null && (
            <div>
              {/* 首尾帧图片展示 */}
              <div style={{ marginBottom: 24 }}>
                <Text strong style={{ display: 'block', marginBottom: 12 }}>首尾帧图片：</Text>
                <Row gutter={16}>
                  <Col span={12}>
                    <Card size="small" title="首帧">
                      {getCurrentEditFrame()?.first_image_path ? (
                        <Image
                          src={getMediaSrc(getCurrentEditFrame()?.first_image_path)}
                          style={{ width: '100%', maxHeight: 200, objectFit: 'contain' }}
                          preview={{ mask: '点击预览' }}
                        />
                      ) : (
                        <div style={{ height: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
                          <Text type="secondary">暂无首帧</Text>
                        </div>
                      )}
                    </Card>
                  </Col>
                  <Col span={12}>
                    <Card size="small" title="尾帧">
                      {getCurrentEditFrame()?.last_image_path ? (
                        <Image
                          src={getMediaSrc(getCurrentEditFrame()?.last_image_path)}
                          style={{ width: '100%', maxHeight: 200, objectFit: 'contain' }}
                          preview={{ mask: '点击预览' }}
                        />
                      ) : (
                        <div style={{ height: 150, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
                          <Text type="secondary">暂无尾帧</Text>
                        </div>
                      )}
                    </Card>
                  </Col>
                </Row>
              </div>

              {/* 视频参数 + 分片脚本 横向布局 */}
              <Row gutter={16}>
                {/* 左侧：视频参数 */}
                {videoParams && (
                  <Col span={6}>
                    <div style={{ marginBottom: 16 }}>
                      <Text strong style={{ display: 'block', marginBottom: 8 }}>视频参数：</Text>
                      <Descriptions bordered size="small" column={1}>
                        <Descriptions.Item label="分辨率">{videoParams.resolution}</Descriptions.Item>
                        <Descriptions.Item label="宽高比">{videoParams.aspect_ratio}</Descriptions.Item>
                        <Descriptions.Item label="语言">{videoParams.language}</Descriptions.Item>
                        <Descriptions.Item label="风格">{videoParams.style}</Descriptions.Item>
                        <Descriptions.Item label="视角">{videoParams.perspective}</Descriptions.Item>
                        <Descriptions.Item label="时长">{getCurrentEditSegment()?.duration || '-'} 秒</Descriptions.Item>
                      </Descriptions>
                    </div>
                  </Col>
                )}

                {/* 右侧：分片脚本编辑表单 */}
                <Col span={videoParams ? 18 : 24}>
                  <div>
                    <Text strong style={{ display: 'block', marginBottom: 8 }}>分片脚本（可编辑）：</Text>
                    <Form form={form} layout="vertical" size="small">
                      <Form.Item
                        name="content"
                        // label="内容"
                        rules={[{ required: true, message: '请输入分片内容' }]}
                        style={{ marginBottom: 8 }}
                      >
                        <TextArea rows={3} placeholder="描述这个镜头的内容..." />
                      </Form.Item>
                      <Row gutter={8}>
                        <Col span={8}>
                          <Form.Item
                            name="duration"
                            label="时长(秒)"
                            rules={[{ required: true, message: '请输入时长' }]}
                            style={{ marginBottom: 4 }}
                          >
                            <InputNumber min={1} max={10} style={{ width: '100%' }} />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="action" label="动作" style={{ marginBottom: 4 }}>
                            <Input placeholder="奔跑、转身..." />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="camera_movement" label="镜头运动" style={{ marginBottom: 4 }}>
                            <Input placeholder="推镜、横摇..." />
                          </Form.Item>
                        </Col>

                      </Row>
                      <Row gutter={8}>
                        <Col span={8}>
                          <Form.Item name="composition" label="构图" style={{ marginBottom: 4 }}>
                            <Input placeholder="中景、特写..." />
                          </Form.Item>
                        </Col>
                        <Col span={8}>
                          <Form.Item name="atmosphere" label="氛围" style={{ marginBottom: 8 }}>
                            <Input placeholder="紧张、欢快..." />
                          </Form.Item>
                        </Col>
                        <Col span={8} style={{ display: 'flex', alignItems: 'flex-end', paddingBottom: 8 }}>
                          <Button
                            type="primary"
                            icon={<SaveOutlined />}
                            loading={editLoading}
                            onClick={handleSaveSegment}
                            size="small"
                          >
                            保存分片脚本
                          </Button>
                        </Col>
                      </Row>
                    </Form>
                    <div style={{ padding: 8, background: '#fff7e6', borderRadius: 4 }}>
                      <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
                      <Text type="warning" style={{ fontSize: 12 }}>
                        注意：修改分片脚本后，需要重新生成首尾帧和视频才能看到效果
                      </Text>
                    </div>
                  </div>
                </Col>
              </Row>

              {/* AI 优化提示词 - 折叠面板 */}
              <Collapse
                size="small"
                style={{ marginTop: 16 }}
                items={[{
                  key: 'ai-optimize',
                  label: (
                    <span>
                      <BulbOutlined style={{ marginRight: 8, color: '#faad14' }} />
                      AI 优化分片提示词
                    </span>
                  ),
                  children: (
                    <div>
                      <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
                        <Input
                          value={optimizeRequirement}
                          onChange={(e) => setOptimizeRequirement(e.target.value)}
                          placeholder="自定义要求（可选）：如增加动作细节、调整氛围..."
                          style={{ flex: 1 }}
                        />
                        <Button
                          type="primary"
                          icon={<BulbOutlined />}
                          loading={optimizeLoading}
                          onClick={handleOptimizePrompt}
                        >
                          {optimizeLoading ? '分析中...' : '生成'}
                        </Button>
                      </Space.Compact>

                      {optimizedPrompt && (
                        <div>
                          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                            <Text type="secondary" style={{ fontSize: 12 }}>基于首尾帧图片分析生成，可复制到上方使用</Text>
                            <Button type="link" icon={<CopyOutlined />} onClick={handleCopyOptimizedPrompt} size="small">
                              复制
                            </Button>
                          </div>
                          <div
                            style={{
                              padding: 8,
                              background: '#f6ffed',
                              border: '1px solid #b7eb8f',
                              borderRadius: 4,
                              maxHeight: 200,
                              overflowY: 'auto',
                              whiteSpace: 'pre-wrap',
                              fontSize: 12,
                              lineHeight: 1.5,
                            }}
                          >
                            {optimizedPrompt}
                          </div>
                        </div>
                      )}
                    </div>
                  ),
                }]}
              />
            </div>
          )}
        </Modal>
      </>
    )
  }

  // 初始状态：显示生成按钮
  return (
    <Card title="生成视频" style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Text>使用即梦基于首尾帧生成视频片段，每个片段5-10秒。</Text>
      </div>

      {/* 预览统计信息 */}
      {segments.length > 0 && (
        <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 4 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>生成任务预览：</Text>
          <Row gutter={16}>
            <Col span={6}>
              <Text type="secondary">视频数量：</Text>
              <Text strong>{videoPreviewInfo.totalSegments} 个</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">预计总时长：</Text>
              <Text strong style={{ color: '#1890ff' }}>约 {videoPreviewInfo.totalDuration.toFixed(1)} 秒</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">平均时长：</Text>
              <Text strong>约 {(videoPreviewInfo.totalDuration / (videoPreviewInfo.totalSegments || 1)).toFixed(1)} 秒</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">预计耗时：</Text>
              <Text strong style={{ color: '#fa8c16' }}>约 {Math.ceil(videoPreviewInfo.totalSegments * 1.5)} 分钟</Text>
            </Col>
          </Row>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ⏱️ 视频生成需要较长时间，每个片段约需 1-2 分钟。生成过程可随时停止，已完成的视频将被保留。
            </Text>
          </div>
        </div>
      )}

      <Spin spinning={isGenerating}>
        <Button
          type="primary"
          icon={<VideoCameraOutlined />}
          onClick={handleGenerate}
          loading={isGenerating}
          disabled={isGenerating}
          size="large"
        >
          {isGenerating ? '生成中...' : '开始生成视频'}
        </Button>
      </Spin>
    </Card>
  )
}
