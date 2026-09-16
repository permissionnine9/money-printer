/**
 * 分片卡片组件
 */
import React from 'react'
import { Card, Row, Col, Button } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { SegmentCardHeader } from './SegmentCardHeader'
import { FrameContent } from './FrameContent'
import type { SegmentInfo, FrameData } from './types'

interface SegmentCardProps {
  segmentIndex: number
  segment: SegmentInfo
  frame: FrameData | undefined
  isGenerating: boolean
  changingVideoMode: number | null
  generateSingleLoading: number | null
  regeneratingFrames: Record<string, boolean>
  actionLoading: string | null
  isFirstSegment: boolean
  onViewScript: (index: number) => void
  onEditScript: (index: number) => void
  onDeleteSegment: (index: number) => void
  onVideoModeChange: (index: number, mode: string) => void
  onGenerateSingleFrame: (index: number, frameType: 'first' | 'last') => void
  onGenerateSingleFrames: (index: number) => void
  onEditFrame: (segmentIndex: number, frameType: 'first' | 'last', prompt: string) => void
  onInsertSegment: (afterIndex: number) => void
  onFirstFrameModeChange?: (index: number, mode: string | undefined) => void
}

export const SegmentCard: React.FC<SegmentCardProps> = ({
  segmentIndex,
  segment,
  frame,
  isGenerating,
  changingVideoMode,
  generateSingleLoading,
  regeneratingFrames,
  actionLoading,
  isFirstSegment,
  onViewScript,
  onEditScript,
  onDeleteSegment,
  onVideoModeChange,
  onGenerateSingleFrame,
  onGenerateSingleFrames,
  onEditFrame,
  onInsertSegment,
  onFirstFrameModeChange,
}) => {
  return (
    <>
      {/* 插入按钮（在每个分片之前，从第二个开始） */}
      {!isFirstSegment && !isGenerating && (
        <div style={{ textAlign: 'center', margin: '8px 0 16px' }}>
          <Button
            type="dashed"
            size="small"
            icon={<PlusOutlined />}
            onClick={() => onInsertSegment(segmentIndex - 1)}
            style={{ borderStyle: 'dashed', color: '#1890ff' }}
          >
            插入分片
          </Button>
        </div>
      )}
      <Card
        size="small"
        title={
          <SegmentCardHeader
            segmentIndex={segmentIndex}
            segment={segment}
            frame={frame}
            isGenerating={isGenerating}
            changingVideoMode={changingVideoMode}
            generateSingleLoading={generateSingleLoading}
            onViewScript={onViewScript}
            onEditScript={onEditScript}
            onDeleteSegment={onDeleteSegment}
            onVideoModeChange={onVideoModeChange}
            onGenerateSingleFrame={onGenerateSingleFrame}
            onGenerateSingleFrames={onGenerateSingleFrames}
            onFirstFrameModeChange={onFirstFrameModeChange}
          />
        }
      >
        <Row gutter={16}>
          <Col span={12}>
            <FrameContent
              imagePath={frame?.first_image_path}
              status={frame?.first_status}
              segmentIndex={segmentIndex}
              frameType="first"
              label="首帧"
              prompt={frame?.first_prompt}
              segment={segment}
              isRegenerating={regeneratingFrames[`${segmentIndex}-first`] === true}
              isGenerating={isGenerating}
              actionLoading={actionLoading}
              onEdit={onEditFrame}
            />
          </Col>
          <Col span={12}>
            <FrameContent
              imagePath={frame?.last_image_path}
              status={frame?.last_status}
              segmentIndex={segmentIndex}
              frameType="last"
              label="尾帧"
              prompt={frame?.last_prompt}
              segment={segment}
              isRegenerating={regeneratingFrames[`${segmentIndex}-last`] === true}
              isGenerating={isGenerating}
              actionLoading={actionLoading}
              onEdit={onEditFrame}
            />
          </Col>
        </Row>
      </Card>
    </>
  )
}
