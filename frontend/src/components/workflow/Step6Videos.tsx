/**
 * 步骤 4（索引3）：生成视频（远程 ComfyUI 整段生成，远程不可用时 mock）
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 完成后展示最终视频 + timeline_data
 *
 * 分镜数据来源：优先旧 generate_segment_scripts（legacy 会话），否则读
 * storyboard_outline.segments（content=已生成提示词或分镜大纲）。
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
  DownloadOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'
import { LazyVideo } from '@/components/common/LazyVideo'

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

  // 检查前置步骤是否完成（步骤3 分镜管理）
  const canExecute = useMemo(
    () => session.completed_steps?.includes('segment_management') ?? false,
    [session]
  )

  const stepResult = session.step_results?.generate_videos?.result_data
  const videos = stepResult?.generated_videos || []
  // ComfyUI 整段生成的最终视频与时间轴配置
  const finalVideo = stepResult?.final_video
  const timelineData = stepResult?.timeline_data

  // 分镜数据源：优先旧分镜脚本（legacy 会话兜底），否则从分镜大纲映射
  const segments: any[] = useMemo(() => {
    const legacy = session.step_results?.generate_segment_scripts?.result_data?.segment_scripts
    if (legacy?.length) return legacy
    const outlineSegments = session.step_results?.storyboard_outline?.result_data?.segments || []
    const params = session.step_results?.select_episode?.result_data?.video_params || {}
    return outlineSegments.map((seg: any, i: number) => ({
      index: seg.index ?? i,
      content: seg.prompt || seg.outline || '',
      duration: params.max_segment_duration || 15,
    }))
  }, [session])

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

          <div style={{ marginTop: 16, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text type="secondary">
              🔗 视频将通过远程 ComfyUI 服务整段生成：各分片首帧与音频素材会上传到 ComfyUI，
              按 timeline_data 多段时间轴合成最终长视频（相邻段按 overlap 衔接）。远程服务不可用时将生成本地 mock 演示视频。
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
    return (
      <Card title="生成视频" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">请先完成第 3 步：分镜管理（点击「完成分镜配置」）</Text>
        </div>
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
        {/* ===== 最终视频（远程 ComfyUI 整段生成） ===== */}
        {finalVideo?.video_path && !finalVideo.video_path.startsWith('生成失败') && (
          <Card
            size="small"
            style={{ marginBottom: 16, background: '#f6ffed' }}
            title={
              <span>
                <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
                最终视频（远程 ComfyUI 整段生成）
                {finalVideo.mock && (
                  <Tag color="orange" style={{ marginLeft: 12 }}>
                    Mock 演示视频（远程服务暂不可用）
                  </Tag>
                )}
              </span>
            }
            extra={
              <Button
                size="small"
                icon={<DownloadOutlined />}
                href={getMediaSrc(finalVideo.video_path)}
                target="_blank"
              >
                下载视频
              </Button>
            }
          >
            <Row gutter={[16, 16]}>
              <Col xs={24} lg={14}>
                <LazyVideo
                  src={getMediaSrc(finalVideo.video_path)}
                  placeholderHeight={320}
                />
              </Col>
              <Col xs={24} lg={10}>
                <Descriptions bordered size="small" column={1}>
                  <Descriptions.Item label="分段数量">{finalVideo.segment_count} 段</Descriptions.Item>
                  <Descriptions.Item label="段间 overlap">
                    {finalVideo.overlap_seconds} 秒
                  </Descriptions.Item>
                  <Descriptions.Item label="参考图">{timelineData?.images?.length || 0} 张</Descriptions.Item>
                  <Descriptions.Item label="参考音频">{timelineData?.audios?.length || 0} 个</Descriptions.Item>
                  <Descriptions.Item label="任务ID">
                    <Text copyable style={{ fontSize: 12 }}>{finalVideo.prompt_id || '-'}</Text>
                  </Descriptions.Item>
                </Descriptions>
              </Col>
            </Row>
            {timelineData && (
              <Collapse
                style={{ marginTop: 16 }}
                items={[
                  {
                    key: 'timeline',
                    label: 'timeline_data（提交给 ComfyUI 的时间轴配置）',
                    children: (
                      <pre
                        style={{
                          maxHeight: 300,
                          overflow: 'auto',
                          fontSize: 12,
                          background: '#fafafa',
                          padding: 12,
                          borderRadius: 4,
                        }}
                      >
                        {JSON.stringify(timelineData, null, 2)}
                      </pre>
                    ),
                  },
                ]}
              />
            )}
          </Card>
        )}
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
    )
  }

  // 初始状态：显示生成按钮
  return (
    <Card title="生成视频" style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Text>基于分镜提示词与首帧素材，通过远程 ComfyUI 整段生成视频。</Text>
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
