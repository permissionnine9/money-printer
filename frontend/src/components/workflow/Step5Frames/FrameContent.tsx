/**
 * 单个帧内容渲染组件
 */
import React from 'react'
import { Image, Typography, Tag, Spin, Button } from 'antd'
import {
  LoadingOutlined,
  EditOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  VideoCameraOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons'
import { StatusTag } from './StatusTag'
import { getImageSrc } from './utils'
import type { SegmentInfo } from './types'

const { Text } = Typography

interface FrameContentProps {
  imagePath: string | undefined
  status: string | undefined
  segmentIndex: number
  frameType: 'first' | 'last'
  label: string
  prompt: string | undefined
  segment: SegmentInfo | undefined
  isRegenerating: boolean
  isGenerating: boolean
  actionLoading: string | null
  onEdit: (segmentIndex: number, frameType: 'first' | 'last', prompt: string) => void
}

export const FrameContent: React.FC<FrameContentProps> = ({
  imagePath,
  status,
  segmentIndex,
  frameType,
  label,
  prompt,
  segment,
  isRegenerating,
  isGenerating,
  actionLoading,
  onEdit,
}) => {
  const isPending = status === 'pending'
  const isFailed = status === 'failed'
  const isFrameCompleted = status === 'completed' && imagePath
  const isWaiting = !status || status === 'waiting'

  // 检查是否为复用帧或视频快照模式
  const isReusedFrame = frameType === 'first' && segment?.first_frame_mode === 'reuse_prev'
  const isVideoSnapshot = frameType === 'first' && segment?.first_frame_mode === 'use_video_snapshot'

  // 检查是否为首帧+参考图模式下的尾帧（此模式下不需要尾帧）
  const isFirstFrameReferenceMode = segment?.video_generation_mode === 'first_frame_reference'
  const isLastFrameInReferenceMode = frameType === 'last' && isFirstFrameReferenceMode

  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{ marginBottom: 8 }}>
        <Text strong>{label}</Text>
        <span style={{ marginLeft: 8 }}>
          {isRegenerating ? (
            <Tag icon={<LoadingOutlined />} color="processing">重新生成中</Tag>
          ) : isLastFrameInReferenceMode || isVideoSnapshot ? (
            <Tag icon={<CheckCircleOutlined />} color="default">不需生成</Tag>
          ) : (
            <StatusTag status={status} />
          )}
        </span>
        {isReusedFrame && (
          <Tag color="green" style={{ marginLeft: 4 }}>
            复用自分片{segmentIndex}
          </Tag>
        )}
        {isVideoSnapshot && (
          <Tag color="purple" style={{ marginLeft: 4 }}>
            上一分片视频快照
          </Tag>
        )}
        {isLastFrameInReferenceMode && (
          <Tag color="orange" style={{ marginLeft: 4 }}>
            首帧+参考图模式
          </Tag>
        )}
      </div>
      <div style={{ marginTop: 8, position: 'relative' }}>
        {isFrameCompleted ? (
          <>
            <Image
              src={getImageSrc(imagePath!)}
              alt={`分片${segmentIndex + 1}${label}`}
              style={{ maxHeight: 200, opacity: isRegenerating ? 0.5 : 1 }}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            />
            {isRegenerating && (
              <div
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  right: 0,
                  bottom: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: 'rgba(255, 255, 255, 0.7)',
                }}
              >
                <Spin tip="重新生成中..." />
              </div>
            )}
          </>
        ) : isFailed ? (
          <div
            style={{
              height: 200,
              background: '#fff2f0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
              gap: 8,
              position: 'relative',
            }}
          >
            {isRegenerating ? (
              <Spin tip="重新生成中..." />
            ) : (
              <>
                <CloseCircleOutlined style={{ fontSize: 32, color: '#ff4d4f' }} />
                <Text type="danger">生成失败</Text>
              </>
            )}
          </div>
        ) : isPending ? (
          <div
            style={{
              height: 200,
              background: '#f5f5f5',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            <Spin tip="生成中..." />
            <Text type="secondary">请稍候...</Text>
          </div>
        ) : isLastFrameInReferenceMode ? (
          // 首帧+参考图模式下的尾帧显示
          <div
            style={{
              height: 200,
              background: '#f6ffed',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
              gap: 8,
              border: '1px dashed #b7eb8f',
              borderRadius: 4,
            }}
          >
            <VideoCameraOutlined style={{ fontSize: 32, color: '#52c41a' }} />
            <Text type="secondary" style={{ color: '#52c41a' }}>使用首帧+参考图</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>此模式下无需生成尾帧</Text>
          </div>
        ) : isVideoSnapshot && frameType === 'first' ? (
          // 使用上一个分片视频快照作为首帧
          <div
            style={{
              height: 200,
              background: '#f9f0ff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
              gap: 8,
              border: '1px dashed #d3adf7',
              borderRadius: 4,
            }}
          >
            <VideoCameraOutlined style={{ fontSize: 32, color: '#722ed1' }} />
            <Text type="secondary" style={{ color: '#722ed1' }}>使用上一个分片视频的结尾快照图</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>此模式下无需生成首帧</Text>
          </div>
        ) : isWaiting ? (
          <div
            style={{
              height: 200,
              background: '#fafafa',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexDirection: 'column',
              gap: 8,
              border: '1px dashed #d9d9d9',
              borderRadius: 4,
            }}
          >
            <ClockCircleOutlined style={{ fontSize: 24, color: '#8c8c8c' }} />
            <Text type="secondary">等待生成</Text>
          </div>
        ) : null}
      </div>
      {!isPending && !isGenerating && !isRegenerating && !isLastFrameInReferenceMode && !isVideoSnapshot && (
        <div style={{ marginTop: 8 }}>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => onEdit(segmentIndex, frameType, prompt || '')}
            loading={
              actionLoading === `${segmentIndex}-${frameType}` ||
              actionLoading === `upload-${segmentIndex}-${frameType}` ||
              actionLoading === `copy-${segmentIndex}-${frameType}`
            }
          >
            编辑
          </Button>
        </div>
      )}
    </div>
  )
}
