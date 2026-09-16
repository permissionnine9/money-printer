/**
 * 初始状态视图组件
 */
import React from 'react'
import { Card, Typography, Row, Col, Button, Spin } from 'antd'
import { BorderOutlined, PlusOutlined } from '@ant-design/icons'
import { SegmentList } from './SegmentList'
import type { SegmentInfo, ReuseInfo } from './types'

const { Text } = Typography

interface InitialViewProps {
  segments: SegmentInfo[]
  reuseInfo: ReuseInfo
  isGenerating: boolean
  changingVideoMode: number | null
  generateSingleLoading: number | null
  addModalVisible: boolean
  onGenerate: () => void
  onViewScript: (index: number) => void
  onEditScript: (index: number) => void
  onDeleteSegment: (index: number) => void
  onVideoModeChange: (index: number, mode: string) => void
  onGenerateSingleFrames: (index: number) => void
  onGenerateSingleFrame?: (index: number, frameType: 'first' | 'last') => void
  onShowAddModal: (afterIndex: number) => void
  onFirstFrameModeChange?: (index: number, mode: string | undefined) => void
}

export const InitialView: React.FC<InitialViewProps> = ({
  segments,
  reuseInfo,
  isGenerating,
  changingVideoMode,
  generateSingleLoading,
  onGenerate,
  onViewScript,
  onEditScript,
  onDeleteSegment,
  onVideoModeChange,
  onGenerateSingleFrames,
  onGenerateSingleFrame,
  onShowAddModal,
  onFirstFrameModeChange,
}) => {
  return (
    <Card title="生成首尾帧" style={{ marginTop: 16 }}>
      <div style={{ marginBottom: 16 }}>
        <Text>基于素材图（图生图），为每个分片生成首尾帧，确保角色/物品一致性。</Text>
      </div>

      {/* 预览统计信息 */}
      {segments.length > 0 && (
        <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 4 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>生成任务预览：</Text>
          <Row gutter={16}>
            <Col span={6}>
              <Text type="secondary">总分片数：</Text>
              <Text strong>{reuseInfo.totalSegments} 个</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">需要生成：</Text>
              <Text strong style={{ color: '#1890ff' }}>{reuseInfo.generateCount} 张</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">自动复用：</Text>
              <Text strong style={{ color: '#52c41a' }}>{reuseInfo.reuseCount} 张</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">总帧数：</Text>
              <Text strong>{reuseInfo.totalSegments * 2} 张</Text>
            </Col>
          </Row>
          {reuseInfo.reuseCount > 0 && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary" style={{ fontSize: 12 }}>
                💡 {reuseInfo.reuseCount} 个首帧将从前一分片的尾帧复用，节省生成成本
              </Text>
            </div>
          )}
        </div>
      )}

      <div style={{ marginBottom: 24 }}>
        <Spin spinning={isGenerating}>
          <Button
            type="primary"
            icon={<BorderOutlined />}
            onClick={onGenerate}
            loading={isGenerating}
            disabled={isGenerating}
            size="large"
          >
            {isGenerating ? '生成中...' : '为全部分片生成首尾帧'}
          </Button>
        </Spin>
      </div>

      {/* 分片列表 - 支持插入分片和单独生成首尾帧 */}
      {segments.length > 0 && (
        <div>
          <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text strong>分片列表（{segments.length} 个）</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>
              可以在下方插入新分片，或为单个分片单独生成首尾帧
            </Text>
          </div>
          <SegmentList
            segments={segments}
            changingVideoMode={changingVideoMode}
            generateSingleLoading={generateSingleLoading}
            onViewScript={onViewScript}
            onEditScript={onEditScript}
            onDeleteSegment={onDeleteSegment}
            onVideoModeChange={onVideoModeChange}
            onGenerateSingleFrames={onGenerateSingleFrames}
            onGenerateSingleFrame={onGenerateSingleFrame}
            onFirstFrameModeChange={onFirstFrameModeChange}
          />
          {/* 末尾插入按钮 */}
          <div style={{ textAlign: 'center', margin: '16px 0' }}>
            <Button
              type="dashed"
              icon={<PlusOutlined />}
              onClick={() => onShowAddModal(-1)}
              style={{ borderStyle: 'dashed', color: '#1890ff' }}
            >
              在末尾插入分片
            </Button>
          </div>
        </div>
      )}
    </Card>
  )
}
