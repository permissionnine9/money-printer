/**
 * 复制帧Tab内容组件
 */
import React, { memo } from 'react'
import { Button, Typography, Radio, Row, Col, Image } from 'antd'
import { CopyOutlined } from '@ant-design/icons'
import type { EditModalState, AvailableFrame } from './types'
import { getImageSrc } from './utils'

const { Text } = Typography

interface CopyTabProps {
  editModal: EditModalState
  setEditModal: React.Dispatch<React.SetStateAction<EditModalState>>
  availableFramesForCopy: AvailableFrame[]
  actionLoading: string | null
  onCopyFrame: () => void
}

export const CopyTab: React.FC<CopyTabProps> = memo(({
  editModal,
  setEditModal,
  availableFramesForCopy,
  actionLoading,
  onCopyFrame,
}) => {
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          从其他分片中选择一个已生成的帧来替换当前帧。
        </Text>
      </div>
      {availableFramesForCopy.length === 0 ? (
        <div style={{ padding: 24, textAlign: 'center', background: '#fafafa', borderRadius: 4 }}>
          <Text type="secondary">暂无可选择的帧</Text>
        </div>
      ) : (
        <>
          <Radio.Group
            value={
              editModal.selectedSourceSegment !== null && editModal.selectedSourceFrameType !== null
                ? `${editModal.selectedSourceSegment}-${editModal.selectedSourceFrameType}`
                : null
            }
            onChange={(e) => {
              const [segIdx, fType] = e.target.value.split('-')
              setEditModal(prev => ({
                ...prev,
                selectedSourceSegment: parseInt(segIdx),
                selectedSourceFrameType: fType as 'first' | 'last',
              }))
            }}
            style={{ width: '100%' }}
          >
            <Row gutter={[12, 12]} style={{ maxHeight: "450px", overflow: "auto" }}>
              {availableFramesForCopy.map((item) => (
                <Col span={8} key={`${item.segmentIndex}-${item.frameType}`}>
                  <Radio.Button
                    value={`${item.segmentIndex}-${item.frameType}`}
                    style={{
                      width: '100%',
                      height: 'auto',
                      padding: 8,
                      textAlign: 'center',
                    }}
                  >
                    <div>
                      <Image
                        src={getImageSrc(item.imagePath)}
                        alt={item.label}
                        style={{ maxHeight: 80, maxWidth: '100%' }}
                        preview={false}
                        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                      />
                      <div style={{ marginTop: 4, fontSize: 12 }}>{item.label}</div>
                    </div>
                  </Radio.Button>
                </Col>
              ))}
            </Row>
          </Radio.Group>
          <div style={{ marginTop: 16 }}>
            <Button
              type="primary"
              icon={<CopyOutlined />}
              onClick={onCopyFrame}
              loading={actionLoading === `copy-${editModal.segmentIndex}-${editModal.frameType}`}
              disabled={editModal.selectedSourceSegment === null}
            >
              使用所选帧
            </Button>
          </div>
        </>
      )}
    </div>
  )
})

CopyTab.displayName = 'CopyTab'
