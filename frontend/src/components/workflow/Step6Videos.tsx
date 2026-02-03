/**
 * 步骤6：生成视频
 */
import React, { useState } from 'react'
import { Card, Button, message, Spin, Typography, Row, Col, Tag, Progress } from 'antd'
import {
  VideoCameraOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

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
  const isCompleted = session.completed_steps?.includes('generate_videos')
  const stepResult = session.step_results?.generate_videos?.result_data
  const videos = stepResult?.generated_videos || []

  const handleGenerate = async () => {
    setLoading(true)
    try {
      const response = await stepApi.generateVideos(session.session_id)
      if (response.success) {
        message.success(response.message)
        // 视频生成是异步的，会通过轮询更新
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleRegenerate = async () => {
    setLoading(true)
    try {
      const response = await stepApi.regenerateVideos(session.session_id)
      if (response.success) {
        message.success(response.message)
        // 视频生成是异步的，会通过轮询更新
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  // 根据 video_path 判断视频状态
  const getVideoStatus = (video: any): 'completed' | 'pending' | 'failed' => {
    if (!video.video_path) return 'pending'
    if (video.video_path.startsWith('生成失败')) return 'failed'
    return 'completed'
  }

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'completed':
        return 'success'
      case 'pending':
        return 'processing'
      case 'failed':
        return 'error'
      default:
        return 'default'
    }
  }

  const getStatusText = (status: string) => {
    switch (status) {
      case 'completed':
        return '已完成'
      case 'pending':
        return '生成中'
      case 'failed':
        return '失败'
      default:
        return status
    }
  }

  if (!canExecute) {
    return (
      <Card title="生成视频" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤5：生成首尾帧</Text>
      </Card>
    )
  }

  if (isCompleted && videos.length > 0) {
    const completedCount = videos.filter((v: any) => getVideoStatus(v) === 'completed').length
    const totalCount = videos.length

    return (
      <Card
        title={
          <span>
            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
            视频生成完成 ({completedCount}/{totalCount})
          </span>
        }
        extra={
          <Button 
            type="primary"
            icon={<ReloadOutlined />} 
            onClick={handleRegenerate} 
            loading={loading}
          >
            重新生成
          </Button>
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
                    <Tag color={getStatusColor(getVideoStatus(video))}>{getStatusText(getVideoStatus(video))}</Tag>
                  </span>
                }
              >
                {video.video_path && !video.video_path.startsWith('生成失败') ? (
                  <div>
                    <video
                      src={getMediaSrc(video.video_path)}
                      controls
                      style={{ width: '100%', maxHeight: 300 }}
                      poster={video.first_frame_path ? `/${video.first_frame_path}` : undefined}
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
        {completedCount === totalCount && (
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

  // 正在生成中
  if (stepResult && !isCompleted) {
    const completedCount = videos.filter((v: any) => getVideoStatus(v) === 'completed').length
    const totalCount = videos.length
    const percent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0

    return (
      <Card title="视频生成中..." style={{ marginTop: 16 }}>
        <div style={{ textAlign: 'center', padding: 24 }}>
          <Progress type="circle" percent={percent} />
          <div style={{ marginTop: 16 }}>
            <Text>
              已完成 {completedCount} / {totalCount} 个视频
            </Text>
          </div>
        </div>
      </Card>
    )
  }

  return (
    <Card title="生成视频" style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Text>使用即梦基于首尾帧生成视频片段，每个片段5-10秒。</Text>
      </div>
      <Spin spinning={loading}>
        <Button
          type="primary"
          icon={<VideoCameraOutlined />}
          onClick={handleGenerate}
          loading={loading}
          size="large"
        >
          开始生成视频
        </Button>
      </Spin>
    </Card>
  )
}
