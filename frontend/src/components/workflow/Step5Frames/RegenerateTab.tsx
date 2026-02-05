/**
 * 重新生成Tab内容组件
 */
import React, { memo, useCallback, useRef, useEffect, useState } from 'react'
import {
  Button,
  Typography,
  Row,
  Col,
  Image,
  Space,
  Radio,
  Tag,
  Upload,
  message,
  Input,
} from 'antd'
import { ReloadOutlined, CheckCircleOutlined, CloseCircleOutlined, PlusOutlined } from '@ant-design/icons'
import type { EditModalState, MaterialImage, EditFrameInfo } from './types'
import { uploadApi } from '@/api/client'
import { getImageSrc } from './utils'

const { Text } = Typography
const { TextArea } = Input

interface RegenerateTabProps {
  editModal: EditModalState
  setEditModal: React.Dispatch<React.SetStateAction<EditModalState>>
  editFrameInfo: EditFrameInfo
  materialImages: MaterialImage[]
  customPrompt: string
  setCustomPrompt: (value: string) => void
  currentFramePrompt: string
  setCurrentFramePrompt: (value: string) => void
  actionLoading: string | null
  onRegenerate: () => void
}

// 使用防抖的输入框组件，避免频繁更新父组件状态导致重渲染
// 使用内部状态管理输入值，保证输入流畅，同时防抖更新父组件
const DebouncedTextArea: React.FC<{
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rows?: number
}> = memo(({ value, onChange, placeholder, rows = 4 }) => {
  const [internalValue, setInternalValue] = useState(value)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // 当外部 value 改变时（如弹窗打开），同步到内部状态
  useEffect(() => {
    setInternalValue(value)
  }, [value])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value
    setInternalValue(newValue) // 立即更新内部状态，保证输入流畅

    // 清除之前的定时器
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current)
    }

    // 延迟更新父组件状态（1000ms 防抖，大幅减少父组件重渲染）
    timeoutRef.current = setTimeout(() => {
      onChange(newValue)
    }, 1000)
  }, [onChange])

  // 清理定时器
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current)
      }
    }
  }, [])

  return (
    <TextArea
      placeholder={placeholder}
      rows={rows}
      value={internalValue}
      onChange={handleChange}
    />
  )
})

DebouncedTextArea.displayName = 'DebouncedTextArea'

export const RegenerateTab: React.FC<RegenerateTabProps> = memo(({
  editModal,
  setEditModal,
  editFrameInfo,
  materialImages,
  customPrompt,
  setCustomPrompt,
  currentFramePrompt,
  setCurrentFramePrompt,
  actionLoading,
  onRegenerate,
}) => {
  // 使用 useCallback 缓存事件处理函数
  const handleRegenerateModeChange = useCallback((e: any) => {
    setEditModal(prev => ({ ...prev, regenerateMode: e.target.value }))
  }, [setEditModal])

  const handleSelectAllMaterials = useCallback(() => {
    setEditModal(prev => ({
      ...prev,
      selectedMaterialIndices: materialImages.map((_, idx) => idx),
    }))
  }, [setEditModal, materialImages])

  const handleClearMaterials = useCallback(() => {
    setEditModal(prev => ({ ...prev, selectedMaterialIndices: [] }))
  }, [setEditModal])

  const handleMaterialClick = useCallback((idx: number) => {
    setEditModal(prev => {
      const currentSelected = prev.selectedMaterialIndices
      if (currentSelected.includes(idx)) {
        return {
          ...prev,
          selectedMaterialIndices: currentSelected.filter(i => i !== idx),
        }
      } else {
        return {
          ...prev,
          selectedMaterialIndices: [...currentSelected, idx].sort((a, b) => a - b),
        }
      }
    })
  }, [setEditModal])

  const handleRemoveUploadedMaterial = useCallback((idx: number) => {
    setEditModal(prev => ({
      ...prev,
      uploadedMaterialPaths: prev.uploadedMaterialPaths.filter((_, i) => i !== idx),
    }))
  }, [setEditModal])

  const handleUpload = useCallback(async (file: File) => {
    try {
      const uploadResult = await uploadApi.uploadImage(file)
      setEditModal(prev => ({
        ...prev,
        uploadedMaterialPaths: [...prev.uploadedMaterialPaths, uploadResult.file_path],
      }))
      message.success('上传成功')
    } catch (error) {
      message.error(`上传失败: ${(error as Error).message}`)
    }
    return false
  }, [setEditModal])

  return (
    <div>
      {/* 当前帧和分片信息 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <div style={{ marginBottom: 8 }}>
            <Text strong>当前{editModal.frameType === 'first' ? '首' : '尾'}帧：</Text>
          </div>
          {editFrameInfo.currentImagePath ? (
            <Image
              src={getImageSrc(editFrameInfo.currentImagePath)}
              alt="当前帧"
              style={{ maxHeight: 120, width: '100%', objectFit: 'contain' }}
              fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
            />
          ) : (
            <div style={{ height: 120, background: '#f5f5f5', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Text type="secondary">暂无图片</Text>
            </div>
          )}
        </Col>
        <Col span={16}>
          <div style={{ marginBottom: 8 }}>
            <Text strong>分片脚本内容：</Text>
          </div>
          <div style={{ padding: 8, background: '#f5f5f5', borderRadius: 4, maxHeight: 120, overflowY: 'auto', fontSize: 12 }}>
            {editFrameInfo.segment ? (
              <>
                <div style={{ marginBottom: 4 }}>
                  <Text type="secondary">内容：</Text>
                  <Text>{editFrameInfo.segment.content}</Text>
                </div>
                {editFrameInfo.segment.action && (
                  <div><Text type="secondary">动作：</Text>{editFrameInfo.segment.action}</div>
                )}
                {editFrameInfo.segment.camera_movement && (
                  <div><Text type="secondary">镜头：</Text>{editFrameInfo.segment.camera_movement}</div>
                )}
                {editFrameInfo.segment.composition && (
                  <div><Text type="secondary">构图：</Text>{editFrameInfo.segment.composition}</div>
                )}
              </>
            ) : (
              <Text type="secondary">无分片信息</Text>
            )}
          </div>
        </Col>
      </Row>

      {/* 参考图模式选择 */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>参考图来源：</Text>
        </div>
        <Radio.Group
          value={editModal.regenerateMode}
          onChange={handleRegenerateModeChange}
          style={{ width: '100%' }}
        >
          <Space direction="vertical" style={{ width: '100%' }}>
            <Radio value="material">
              <Text>基于素材图</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                使用素材图作为参考，保持角色/物品风格一致性
              </Text>
            </Radio>
            <Radio value="current_frame" disabled={!editFrameInfo.currentImagePath}>
              <Text>基于当前帧</Text>
              <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                使用当前已生成的帧作为参考，在此基础上微调
              </Text>
              {!editFrameInfo.currentImagePath && (
                <Tag color="warning" style={{ marginLeft: 8 }}>当前帧暂无图片</Tag>
              )}
            </Radio>
          </Space>
        </Radio.Group>
      </div>

      {/* 根据模式显示不同的参考图选择区域和提示词 */}
      {editModal.regenerateMode === 'material' ? (
        /* 基于素材图模式 */
        <>
          {/* 参考素材图 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Text strong>参考素材图：</Text>
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  已选择 {editModal.selectedMaterialIndices.length}/{materialImages.length} 张
                </Text>
              </div>
              <Space size="small">
                <Button
                  size="small"
                  type="link"
                  onClick={handleSelectAllMaterials}
                >
                  全选
                </Button>
                <Button
                  size="small"
                  type="link"
                  onClick={handleClearMaterials}
                >
                  清空
                </Button>
              </Space>
            </div>
            <div style={{ maxHeight: 200, overflowY: 'auto', padding: 4, border: '1px solid #f0f0f0', borderRadius: 4 }}>
              <Row gutter={[8, 8]}>
                {/* 已有素材图 */}
                {materialImages.map((img, idx) => {
                  const isSelected = editModal.selectedMaterialIndices.includes(idx)
                  return (
                    <Col span={6} key={`material-${idx}`}>
                      <div
                        style={{
                          position: 'relative',
                          cursor: 'pointer',
                          border: isSelected ? '2px solid #1890ff' : '2px solid transparent',
                          borderRadius: 4,
                          padding: 2,
                          transition: 'all 0.2s',
                        }}
                        onClick={() => handleMaterialClick(idx)}
                      >
                        <Image
                          src={getImageSrc(img.image_path)}
                          alt={`素材图${idx + 1}`}
                          style={{ width: '100%', height: 60, objectFit: 'cover', borderRadius: 2 }}
                          preview={false}
                          fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                        />
                        {isSelected && (
                          <div
                            style={{
                              position: 'absolute',
                              top: 4,
                              right: 4,
                              width: 20,
                              height: 20,
                              borderRadius: '50%',
                              background: '#1890ff',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <CheckCircleOutlined style={{ color: 'white', fontSize: 12 }} />
                          </div>
                        )}
                        <div
                          style={{
                            textAlign: 'center',
                            fontSize: 12,
                            marginTop: 2,
                            color: isSelected ? '#1890ff' : '#666',
                          }}
                        >
                          {idx + 1}
                        </div>
                      </div>
                    </Col>
                  )
                })}
                {/* 上传的自定义素材图 */}
                {editModal.uploadedMaterialPaths.map((path, idx) => (
                  <Col span={6} key={`uploaded-${idx}`}>
                    <div
                      style={{
                        position: 'relative',
                        border: '2px solid #52c41a',
                        borderRadius: 4,
                        padding: 2,
                      }}
                    >
                      <Image
                        src={getImageSrc(path)}
                        alt={`上传素材${idx + 1}`}
                        style={{ width: '100%', height: 60, objectFit: 'cover', borderRadius: 2 }}
                        preview={false}
                        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                      />
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<CloseCircleOutlined />}
                        style={{
                          position: 'absolute',
                          top: -6,
                          right: -6,
                          padding: 0,
                          width: 18,
                          height: 18,
                          borderRadius: '50%',
                          background: 'white',
                          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
                        }}
                        onClick={() => handleRemoveUploadedMaterial(idx)}
                      />
                      <div
                        style={{
                          textAlign: 'center',
                          fontSize: 10,
                          marginTop: 2,
                          color: '#52c41a',
                        }}
                      >
                        自定义
                      </div>
                    </div>
                  </Col>
                ))}
                {/* 上传按钮 */}
                <Col span={6}>
                  <Upload
                    showUploadList={false}
                    multiple
                    beforeUpload={handleUpload}
                    accept="image/*"
                    style={{ display: 'block' }}
                  >
                    <div
                      style={{
                        borderRadius: 4,
                        border: '1px dashed #ccc',
                        padding: 2,
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = '#1890ff'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = '#d9d9d9'
                      }}
                    >
                      <div
                        style={{
                          width: '100%',
                          height: 60,
                          borderRadius: 2,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <PlusOutlined style={{ fontSize: 20, color: '#999' }} />
                      </div>
                      <div
                        style={{
                          textAlign: 'center',
                          fontSize: 12,
                          marginTop: 2,
                          color: '#999',
                        }}
                      >
                        上传
                      </div>
                    </div>
                  </Upload>
                </Col>
              </Row>
            </div>
            {(materialImages.length > 0 || editModal.uploadedMaterialPaths.length > 0) && (
              <div style={{ marginTop: 8, padding: 8, background: '#f0f5ff', borderRadius: 4, fontSize: 12 }}>
                <Text type="secondary">
                  💡 点击图片可选择/取消选择，点击"+"可上传自定义素材图。
                </Text>
              </div>
            )}
          </div>

          {/* 素材图模式的提示词 - 使用防抖输入框 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
              <Text strong>生成提示词：</Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>可以修改提示词来调整生成效果</Text>
            </div>
            <DebouncedTextArea
              placeholder="输入生成提示词"
              rows={4}
              value={customPrompt}
              onChange={setCustomPrompt}
            />
          </div>
        </>
      ) : (
        /* 基于当前帧模式 */
        <>
          {/* 当前帧预览 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
              <Text strong>当前帧（主参考）：</Text>
              <Tag color="blue" style={{ marginLeft: 8 }}>必选</Tag>
            </div>
            <div style={{ padding: 12, border: '2px solid #1890ff', borderRadius: 4, background: '#f0f5ff', display: 'inline-block' }}>
              {editFrameInfo.currentImagePath && (
                <Image
                  src={getImageSrc(editFrameInfo.currentImagePath)}
                  alt="当前帧"
                  style={{ maxHeight: 120, objectFit: 'contain' }}
                  fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                />
              )}
            </div>
          </div>

          {/* 可选的素材图参考 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <Text strong>素材图（辅助参考）：</Text>
                <Tag color="default" style={{ marginLeft: 8 }}>可选</Tag>
                <Text type="secondary" style={{ marginLeft: 8 }}>
                  已选择 {editModal.selectedMaterialIndices.length}/{materialImages.length} 张
                  {editModal.uploadedMaterialPaths.length > 0 && ` + ${editModal.uploadedMaterialPaths.length} 张自定义`}
                </Text>
              </div>
              <Space size="small">
                <Button
                  size="small"
                  type="link"
                  onClick={handleSelectAllMaterials}
                >
                  全选
                </Button>
                <Button
                  size="small"
                  type="link"
                  onClick={handleClearMaterials}
                >
                  清空
                </Button>
              </Space>
            </div>
            <div style={{ maxHeight: 150, overflowY: 'auto', padding: 4, border: '1px solid #f0f0f0', borderRadius: 4 }}>
              <Row gutter={[8, 8]}>
                {/* 已有素材图 */}
                {materialImages.map((img, idx) => {
                  const isSelected = editModal.selectedMaterialIndices.includes(idx)
                  return (
                    <Col span={6} key={`material-${idx}`}>
                      <div
                        style={{
                          position: 'relative',
                          cursor: 'pointer',
                          border: isSelected ? '2px solid #1890ff' : '2px solid transparent',
                          borderRadius: 4,
                          padding: 2,
                          transition: 'all 0.2s',
                        }}
                        onClick={() => handleMaterialClick(idx)}
                      >
                        <Image
                          src={getImageSrc(img.image_path)}
                          alt={`素材图${idx + 1}`}
                          style={{ width: '100%', height: 50, objectFit: 'cover', borderRadius: 2 }}
                          preview={false}
                          fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                        />
                        {isSelected && (
                          <div
                            style={{
                              position: 'absolute',
                              top: 2,
                              right: 2,
                              width: 16,
                              height: 16,
                              borderRadius: '50%',
                              background: '#1890ff',
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                            }}
                          >
                            <CheckCircleOutlined style={{ color: 'white', fontSize: 10 }} />
                          </div>
                        )}
                      </div>
                    </Col>
                  )
                })}
                {/* 上传的自定义素材图 */}
                {editModal.uploadedMaterialPaths.map((path, idx) => (
                  <Col span={6} key={`uploaded-${idx}`}>
                    <div
                      style={{
                        position: 'relative',
                        border: '2px solid #52c41a',
                        borderRadius: 4,
                        padding: 2,
                      }}
                    >
                      <Image
                        src={getImageSrc(path)}
                        alt={`上传素材${idx + 1}`}
                        style={{ width: '100%', height: 50, objectFit: 'cover', borderRadius: 2 }}
                        preview={false}
                        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                      />
                      <Button
                        type="text"
                        size="small"
                        danger
                        icon={<CloseCircleOutlined />}
                        style={{
                          position: 'absolute',
                          top: -6,
                          right: -6,
                          padding: 0,
                          width: 16,
                          height: 16,
                          borderRadius: '50%',
                          background: 'white',
                          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
                        }}
                        onClick={() => handleRemoveUploadedMaterial(idx)}
                      />
                      <div
                        style={{
                          textAlign: 'center',
                          fontSize: 10,
                          marginTop: 2,
                          color: '#52c41a',
                        }}
                      >
                        自定义
                      </div>
                    </div>
                  </Col>
                ))}
                {/* 上传按钮 */}
                <Col span={6}>
                  <Upload
                    showUploadList={false}
                    multiple
                    beforeUpload={handleUpload}
                    accept="image/*"
                    style={{ display: 'block' }}
                  >
                    <div
                      style={{
                        borderRadius: 4,
                        border: '1px dashed #ccc',
                        padding: 2,
                        cursor: 'pointer',
                        transition: 'all 0.2s',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = '#1890ff'
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = '#d9d9d9'
                      }}
                    >
                      <div
                        style={{
                          width: '100%',
                          height: 50,
                          borderRadius: 2,
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          justifyContent: 'center',
                        }}
                      >
                        <PlusOutlined style={{ fontSize: 16, color: '#999' }} />
                      </div>
                      <div
                        style={{
                          textAlign: 'center',
                          fontSize: 10,
                          marginTop: 2,
                          color: '#999',
                        }}
                      >
                        上传
                      </div>
                    </div>
                  </Upload>
                </Col>
              </Row>
            </div>
            <div style={{ marginTop: 8, padding: 8, background: '#f0f5ff', borderRadius: 4, fontSize: 12 }}>
              <Text type="secondary">
                💡 可选择素材图作为辅助参考，或点击"+"上传自定义素材图，帮助保持角色/物品的风格一致性。
              </Text>
            </div>
          </div>

          {/* 当前帧模式的独立提示词 - 使用防抖输入框 */}
          <div style={{ marginBottom: 16 }}>
            <div style={{ marginBottom: 8 }}>
              <Text strong>调整指令：</Text>
              <Text type="secondary" style={{ marginLeft: 8 }}>描述你想要的调整，如"让人物微笑"、"增加光照"等</Text>
            </div>
            <DebouncedTextArea
              placeholder="例如：让人物的表情更加开心、增加暖色调光线、调整人物姿态为侧身..."
              rows={3}
              value={currentFramePrompt}
              onChange={setCurrentFramePrompt}
            />
          </div>
        </>
      )}

      <Button
        type="primary"
        icon={<ReloadOutlined />}
        onClick={onRegenerate}
        loading={actionLoading === `${editModal.segmentIndex}-${editModal.frameType}`}
      >
        重新生成
      </Button>
    </div>
  )
})

RegenerateTab.displayName = 'RegenerateTab'
