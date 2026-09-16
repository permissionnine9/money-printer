/**
 * 分片列表组件（用于初始状态）
 */
import React from 'react'
import { Row, Col, Card, Space, Tag, Typography, Button, Tooltip, Select, Checkbox } from 'antd'
import {
  FileTextOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import type { SegmentInfo } from './types'

const { Text } = Typography

interface SegmentListProps {
  segments: SegmentInfo[]
  changingVideoMode: number | null
  generateSingleLoading: number | null
  onViewScript: (index: number) => void
  onEditScript: (index: number) => void
  onDeleteSegment: (index: number) => void
  onVideoModeChange: (index: number, mode: string) => void
  onGenerateSingleFrames: (index: number) => void
  onGenerateSingleFrame?: (index: number, frameType: 'first' | 'last') => void
  onFirstFrameModeChange?: (index: number, mode: string | undefined) => void
}

export const SegmentList: React.FC<SegmentListProps> = ({
  segments,
  changingVideoMode,
  generateSingleLoading,
  onViewScript,
  onEditScript,
  onDeleteSegment,
  onVideoModeChange,
  onGenerateSingleFrames,
  onGenerateSingleFrame,
  onFirstFrameModeChange,
}) => {
  return (
    <Row gutter={[16, 16]}>
      {segments.map((segment, index) => (
        <Col span={24} key={index}>
          <Card size="small" style={{ background: '#fafafa' }}>
            <Row justify="space-between" align="middle">
              <Col>
                <Space>
                  <Tag color="blue">分片 {index + 1}</Tag>
                  <Tag>{segment.duration} 秒</Tag>
                  <Text ellipsis style={{ maxWidth: 300 }}>
                    {segment.content?.substring(0, 50)}...
                  </Text>
                  {/* 视频生成模式选择 */}
                  <Tooltip title="选择视频生成模式：首尾帧模式（约束强）或首帧+参考图模式（更自由）">
                    <Select
                      size="small"
                      value={segment?.video_generation_mode || 'first_last_frame'}
                      onChange={(value) => onVideoModeChange(index, value)}
                      loading={changingVideoMode === index}
                      disabled={changingVideoMode === index}
                      style={{ width: 160 }}
                      options={[
                        {
                          value: 'first_last_frame',
                          label: (
                            <Space size={4}>
                              <PictureOutlined />
                              <span>首尾帧模式</span>
                            </Space>
                          ),
                        },
                        {
                          value: 'first_frame_reference',
                          label: (
                            <Space size={4}>
                              <VideoCameraOutlined />
                              <span>首帧+参考图</span>
                            </Space>
                          ),
                        },
                      ]}
                    />
                  </Tooltip>
                  {/* 非第一个分片，显示使用视频快照选项 */}
                  {index > 0 && onFirstFrameModeChange && (
                    <Tooltip title="使用上一个分片生成视频的结尾帧作为本分片的首帧">
                      <Checkbox
                        checked={segment?.first_frame_mode === 'use_video_snapshot'}
                        onChange={(e) => {
                          const checked = e.target.checked
                          onFirstFrameModeChange(index, checked ? 'use_video_snapshot' : undefined)
                        }}
                        style={{ marginLeft: 8 }}
                      >
                        <span style={{ fontSize: 12 }}>使用上一个分片视频的结尾快照图</span>
                      </Checkbox>
                    </Tooltip>
                  )}
                </Space>
              </Col>
              <Col>
                <Space>
                  <Button
                    size="small"
                    icon={<FileTextOutlined />}
                    onClick={() => onViewScript(index)}
                  >
                    查看
                  </Button>
                  <Button
                    size="small"
                    icon={<EditOutlined />}
                    onClick={() => onEditScript(index)}
                  >
                    编辑脚本
                  </Button>
                  <Button
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={() => onDeleteSegment(index)}
                  >
                    删除
                  </Button>
                  {/* 根据视频生成模式显示不同的按钮文本 */}
                  {(() => {
                    const videoMode = segment?.video_generation_mode
                    const isFirstFrameReference = videoMode === 'first_frame_reference'
                    
                    let buttonText = '生成首尾帧'
                    if (isFirstFrameReference) {
                      buttonText = '生成首帧'
                    }
                    
                    return (
                      <Button
                        type="primary"
                        size="small"
                        icon={<PlayCircleOutlined />}
                        onClick={() => {
                          if (isFirstFrameReference && onGenerateSingleFrame) {
                            // 首帧+参考图模式：只生成首帧
                            onGenerateSingleFrame(index, 'first')
                          } else {
                            // 首尾帧模式：生成首尾两帧
                            onGenerateSingleFrames(index)
                          }
                        }}
                        loading={generateSingleLoading === index}
                      >
                        {buttonText}
                      </Button>
                    )
                  })()}
                </Space>
              </Col>
            </Row>
          </Card>
        </Col>
      ))}
    </Row>
  )
}
