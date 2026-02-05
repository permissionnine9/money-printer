/**
 * 上传Tab内容组件
 */
import React, { memo } from 'react'
import { Upload, Typography, Spin } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import type { EditModalState } from './types'

const { Text } = Typography

interface UploadTabProps {
  editModal: EditModalState
  actionLoading: string | null
  onUpload: (file: File) => void
}

export const UploadTab: React.FC<UploadTabProps> = memo(({
  editModal,
  actionLoading,
  onUpload,
}) => {
  const isUploading = actionLoading === `upload-${editModal.segmentIndex}-${editModal.frameType}`

  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          上传一张图片来替换当前帧，注意图片的尺寸要一致。
        </Text>
      </div>
      <Upload.Dragger
        showUploadList={false}
        beforeUpload={(file) => {
          onUpload(file)
          return false
        }}
        accept="image/*"
        disabled={isUploading}
      >
        {isUploading ? (
          <div style={{ padding: 20 }}>
            <Spin />
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">上传中...</Text>
            </div>
          </div>
        ) : (
          <div style={{ padding: 20 }}>
            <UploadOutlined style={{ fontSize: 32, color: '#1890ff' }} />
            <div style={{ marginTop: 8 }}>
              <Text>点击或拖拽图片到此处上传</Text>
            </div>
          </div>
        )}
      </Upload.Dragger>
    </div>
  )
})

UploadTab.displayName = 'UploadTab'
