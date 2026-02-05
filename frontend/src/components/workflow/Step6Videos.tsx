/**
 * 步骤6：生成视频
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 显示每个视频的生成进度
 */
import React, { useState } from 'react'
import { Card, Button, message, Spin, Typography, Row, Col, Tag, Space, Popconfirm, Modal } from 'antd'
import {
  VideoCameraOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'

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
  const { refreshSession } = useSessionStore()

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('generate_segment_frames')
  const stepResult = session.step_results?.generate_videos?.result_data
  const videos = stepResult?.generated_videos || []

  // 获取分片脚本数据（用于预览视频生成信息）
  const segmentScriptsResult = session.step_results?.generate_segment_scripts?.result_data
  const segments = segmentScriptsResult?.segment_scripts || []

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

  const handleRegenerate = async () => {
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

  // 根据 task_status 判断视频状态（优先使用 task_status）
  const getVideoStatus = (video: any): 'completed' | 'pending' | 'failed' => {
    // 优先使用 task_status
    if (video.task_status) {
      return video.task_status as 'completed' | 'pending' | 'failed'
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
      default:
        return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
    }
  }

  if (!canExecute) {
    return (
      <Card title="生成视频" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤5：生成首尾帧</Text>
      </Card>
    )
  }

  // 当有视频数据时显示（包括生成中和已完成状态）
  if (videos.length > 0) {
    const completedCount = videos.filter((v: any) => getVideoStatus(v) === 'completed').length
    const failedCount = videos.filter((v: any) => getVideoStatus(v) === 'failed').length
    const totalCount = videos.length

    const isAllCompleted = completedCount === totalCount && !isBackgroundGenerating
    const title = isAllCompleted ? (
      <span>
        <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
        视频生成完成 ({completedCount}/{totalCount})
      </span>
    ) : (
      <span>
        <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
        视频生成中 ({completedCount}/{totalCount})
        {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
      </span>
    )

    return (
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
              >
                {video.video_path && !video.video_path.startsWith('生成失败') ? (
                  <div>
                    <video
                      src={getMediaSrc(video.video_path)}
                      controls
                      style={{ width: '100%', maxHeight: 300 }}
                      poster={video.first_frame_path ? getMediaSrc(video.first_frame_path) : undefined}
                    >
                      您的浏览器不支持视频播放
                    </video>
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
