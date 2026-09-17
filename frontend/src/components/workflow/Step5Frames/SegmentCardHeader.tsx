/**
 * 分片卡片头部组件
 */
import React from 'react'
import { Space, Tag, Typography, Button, Tooltip, Select, Dropdown, Checkbox } from 'antd'
import type { MenuProps } from 'antd'
import {
  FileTextOutlined,
  EditOutlined,
  DeleteOutlined,
  PlayCircleOutlined,
  DownOutlined,
  PictureOutlined,
  VideoCameraOutlined,
} from '@ant-design/icons'
import type { SegmentInfo, FrameData } from './types'

const { Text } = Typography

interface SegmentCardHeaderProps {
  segmentIndex: number
  segment: SegmentInfo
  frame: FrameData | undefined
  isGenerating: boolean
  changingVideoMode: number | null
  generateSingleLoading: number | null
  onViewScript: (index: number) => void
  onEditScript: (index: number) => void
  onDeleteSegment: (index: number) => void
  onVideoModeChange: (index: number, mode: string) => void
  onGenerateSingleFrame: (index: number, frameType: 'first' | 'last') => void
  onGenerateSingleFrames: (index: number) => void
  onFirstFrameModeChange?: (index: number, mode: string | undefined) => void
  onLastFrameModeChange?: (index: number, mode: string) => void
}

// 首帧参考模式选项（特殊模式 reuse_prev / use_video_snapshot 由系统或其他控件管理）
const FIRST_FRAME_REF_MODES = [
  { value: 'generate', label: '首帧: 仅素材图' },
  { value: 'generate_continuous', label: '首帧: 参考前片尾帧' },
  { value: 'all_reference', label: '首帧: 全能参考' },
]

// 尾帧参考模式选项（特殊模式 reuse_next 由系统配对管理）
const LAST_FRAME_REF_MODES = [
  { value: 'generate', label: '尾帧: 仅素材图' },
  { value: 'generate_continuous', label: '尾帧: 连贯生成' },
  { value: 'all_reference', label: '尾帧: 全能参考' },
]

export const SegmentCardHeader: React.FC<SegmentCardHeaderProps> = ({
  segmentIndex,
  segment,
  frame,
  isGenerating,
  changingVideoMode,
  generateSingleLoading,
  onViewScript,
  onEditScript,
  onDeleteSegment,
  onVideoModeChange,
  onGenerateSingleFrame,
  onGenerateSingleFrames,
  onFirstFrameModeChange,
  onLastFrameModeChange,
}) => {
  const videoMode = segment?.video_generation_mode
  const isFirstFrameReference = videoMode === 'first_frame_reference'
  const isUseVideoSnapshot = segment?.first_frame_mode === 'use_video_snapshot'

  // 首帧参考模式下拉当前值（特殊模式时不显示为当前值）
  const firstFrameMode: string | undefined = segment?.first_frame_mode
  const firstFrameRefMode: string | undefined = FIRST_FRAME_REF_MODES.some(m => m.value === firstFrameMode)
    ? firstFrameMode
    : undefined
  const lastFrameMode: string | undefined = segment?.last_frame_mode
  const lastFrameRefMode: string | undefined = LAST_FRAME_REF_MODES.some(m => m.value === lastFrameMode)
    ? lastFrameMode
    : undefined

  // 首帧+参考图模式：只需要首帧
  // 视频快照模式：只需要尾帧
  // 首尾帧模式：需要两个帧
  const needFirst = !isUseVideoSnapshot && (!frame || frame.first_status === 'waiting')
  const needLast = !isFirstFrameReference && (!frame || frame.last_status === 'waiting')

  // 构建下拉菜单项
  interface MenuItemDef {
    key: string
    label: string
    icon: React.ReactNode
    onClick: () => void
  }

  const menuItems: MenuItemDef[] = []

  if (needFirst) {
    menuItems.push({
      key: 'first',
      label: `${frame?.first_image_path ? '（重新）' : ''}生成首帧`,
      icon: <PlayCircleOutlined />,
      onClick: () => onGenerateSingleFrame(segmentIndex, 'first')
    })
  }

  if (needLast) {
    menuItems.push({
      key: 'last',
      label: `${frame?.last_image_path ? '（重新）' : ''}生成尾帧`,
      icon: <PlayCircleOutlined />,
      onClick: () => onGenerateSingleFrame(segmentIndex, 'last')
    })
  }

  // 只有在需要两个帧时才显示"生成首尾帧"选项
  if (needFirst && needLast) {
    menuItems.push({
      key: 'both',
      label: `${(frame?.first_image_path || frame?.last_image_path) ? '（重新）' : ''}生成首尾帧`,
      icon: <PlayCircleOutlined />,
      onClick: () => onGenerateSingleFrames(segmentIndex)
    })
  }

  // 根据模式决定按钮文案
  let buttonText = '生成帧'
  if (isFirstFrameReference) {
    buttonText = '生成首帧'
  } else if (isUseVideoSnapshot) {
    buttonText = '生成尾帧'
  }

  return (
    <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
      <Space>
        <Tag color="blue">分片 {segmentIndex + 1}</Tag>
        <Tag>{segment?.duration || 0} 秒</Tag>
        <Text ellipsis style={{ maxWidth: 300 }}>
          {segment?.content?.substring(0, 40)}...
        </Text>
        {/* 视频生成模式选择 */}
        <Tooltip title="选择视频生成模式：首尾帧模式（约束强）或首帧+参考图模式（更自由）">
          <Select
            size="small"
            value={segment?.video_generation_mode || 'first_last_frame'}
            onChange={(value) => onVideoModeChange(segmentIndex, value)}
            loading={changingVideoMode === segmentIndex}
            disabled={isGenerating || changingVideoMode === segmentIndex}
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
        {/* 首帧参考模式选择（含全能参考模式） */}
        {onFirstFrameModeChange && (
          <Tooltip title="首帧生成参考模式：仅素材图 / 参考前一分片尾帧保持连贯 / 全能参考（素材图+前片尾帧+后片首帧等全部可用素材）">
            <Select
              size="small"
              value={firstFrameRefMode}
              placeholder={isUseVideoSnapshot ? '首帧: 视频快照' : '首帧: 系统模式'}
              onChange={(value) => onFirstFrameModeChange(segmentIndex, value)}
              loading={changingVideoMode === segmentIndex}
              disabled={isGenerating || isUseVideoSnapshot || changingVideoMode === segmentIndex}
              style={{ width: 160 }}
              options={FIRST_FRAME_REF_MODES}
            />
          </Tooltip>
        )}
        {/* 尾帧参考模式选择（含全能参考模式） */}
        {onLastFrameModeChange && (
          <Tooltip title="尾帧生成参考模式：仅素材图 / 连贯生成（后片首帧参考此帧）/ 全能参考（素材图+前片尾帧+后片首帧等全部可用素材）">
            <Select
              size="small"
              value={lastFrameRefMode}
              placeholder="尾帧: 系统模式"
              onChange={(value: string) => onLastFrameModeChange(segmentIndex, value)}
              loading={changingVideoMode === segmentIndex}
              disabled={isGenerating || changingVideoMode === segmentIndex}
              style={{ width: 160 }}
              options={LAST_FRAME_REF_MODES}
            />
          </Tooltip>
        )}
        {/* 非第一个分片，显示使用视频快照选项 */}
        {segmentIndex > 0 && onFirstFrameModeChange && (
          <Tooltip title="使用上一个分片生成视频的结尾帧作为本分片的首帧">
            <Checkbox
              checked={isUseVideoSnapshot}
              onChange={(e) => {
                const checked = e.target.checked
                onFirstFrameModeChange(segmentIndex, checked ? 'use_video_snapshot' : undefined)
              }}
              disabled={isGenerating}
              style={{ marginLeft: 8 }}
            >
              <span style={{ fontSize: 12 }}>使用上一个分片视频的结尾快照图</span>
            </Checkbox>
          </Tooltip>
        )}
      </Space>
      <Space>
        <Button
          size="small"
          icon={<FileTextOutlined />}
          onClick={() => onViewScript(segmentIndex)}
        >
          查看
        </Button>
        <Button
          size="small"
          icon={<EditOutlined />}
          onClick={() => onEditScript(segmentIndex)}
          disabled={isGenerating}
        >
          编辑脚本
        </Button>
        <Button
          size="small"
          danger
          icon={<DeleteOutlined />}
          onClick={() => onDeleteSegment(segmentIndex)}
          disabled={isGenerating}
        >
          删除
        </Button>
        {/* 分片操作区域 - 根据模式联动显示不同的生成按钮 */}
        {!needFirst && !needLast ? null : (
          <div style={{ textAlign: 'center', borderTop: '1px solid #f0f0f0' }}>
            {menuItems.length === 1 ? (
              // 只有一个选项时直接显示按钮
              <Button
                type="primary"
                size="small"
                icon={<PlayCircleOutlined />}
                loading={generateSingleLoading === segmentIndex}
                onClick={menuItems[0]!.onClick}
              >
                {buttonText}
              </Button>
            ) : (
              // 多个选项时显示下拉菜单
              <Dropdown
                trigger={['click']}
                menu={{ items: menuItems as unknown as MenuProps['items'] }}
              >
                <Button
                  type="primary"
                  size="small"
                  loading={generateSingleLoading === segmentIndex}
                >
                  {buttonText} <DownOutlined />
                </Button>
              </Dropdown>
            )}
          </div>
        )}
      </Space>
    </Space>
  )
}
