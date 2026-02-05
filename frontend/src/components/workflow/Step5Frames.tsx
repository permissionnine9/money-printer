/**
 * 步骤5：生成首尾帧
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 显示每个帧的生成进度
 */
import React, { useState, useMemo, useCallback } from 'react'
import {
  Card,
  Button,
  message,
  Spin,
  Typography,
  Row,
  Col,
  Image,
  Space,
  Tag,
  Modal,
  Tabs,
  Form,
} from 'antd'
import {
  BorderOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  UploadOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  ClockCircleOutlined,
  StopOutlined,
  UndoOutlined,
  FileTextOutlined,
  EditOutlined,
  CopyOutlined,
  PlusOutlined,
  PlayCircleOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi, frameApi, uploadApi, segmentApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'
import { SegmentForm } from './Step5Frames/SegmentForm'
import { RegenerateTab } from './Step5Frames/RegenerateTab'
import { CopyTab } from './Step5Frames/CopyTab'
import { UploadTab } from './Step5Frames/UploadTab'
import { getImageSrc } from './Step5Frames/utils'
import type {
  MaterialImage,
  FrameData,
  SegmentInfo,
  EditFrameInfo,
  EditModalState,
} from './Step5Frames/types'

const { Text } = Typography


interface Step5FramesProps {
  session: SessionDetail
}

export const Step5Frames: React.FC<Step5FramesProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  // 使用选择器只获取需要的 action，避免订阅整个 store 导致不必要的重渲染
  const refreshSession = useSessionStore(useCallback((state) => state.refreshSession, []))

  // 编辑弹窗状态（不包含频繁变化的输入框值）
  const [editModal, setEditModal] = useState<EditModalState>({
    visible: false,
    segmentIndex: 0,
    frameType: 'first',
    activeTab: 'regenerate',
    selectedSourceSegment: null,
    selectedSourceFrameType: null,
    selectedMaterialIndices: [], // 初始为空数组，表示使用全部素材图
    regenerateMode: 'material', // 默认基于素材图模式
    uploadedMaterialPaths: [], // 上传的自定义素材图路径
  })

  // 将输入框状态独立出来，避免频繁更新 editModal 导致整个组件重渲染
  const [customPrompt, setCustomPrompt] = useState('')
  const [currentFramePrompt, setCurrentFramePrompt] = useState('')

  // 插入分片弹窗状态
  const [addModalVisible, setAddModalVisible] = useState(false)
  const [insertAfterIndex, setInsertAfterIndex] = useState<number>(-1)
  const [addForm] = Form.useForm()
  const [addLoading, setAddLoading] = useState(false)

  // 单个分片生成首尾帧的loading状态
  const [generateSingleLoading, setGenerateSingleLoading] = useState<number | null>(null)

  // 单个帧重新生成的loading状态（key: `${segmentIndex}-${frameType}`）
  const [regeneratingFrames, setRegeneratingFrames] = useState<Record<string, boolean>>({})

  // 编辑分片脚本弹窗状态
  const [editScriptModalVisible, setEditScriptModalVisible] = useState(false)
  const [editingSegmentIndex, setEditingSegmentIndex] = useState<number | null>(null)
  const [editScriptForm] = Form.useForm()
  const [editScriptLoading, setEditScriptLoading] = useState(false)

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('generate_segment_scripts')
  const isCompleted = session.completed_steps?.includes('generate_segment_frames')
  const stepResult = session.step_results?.generate_segment_frames?.result_data

  // 使用 useMemo 包装，避免每次渲染创建新数组导致依赖变化
  const frames = useMemo<FrameData[]>(
    () => stepResult?.segment_frames || [],
    [stepResult?.segment_frames]
  )

  // 获取分片脚本数据（用于预览复用情况和显示脚本内容）
  const segmentScriptsResult = session.step_results?.generate_segment_scripts?.result_data
  const segments = useMemo<SegmentInfo[]>(
    () => segmentScriptsResult?.segment_scripts || [],
    [segmentScriptsResult?.segment_scripts]
  )

  // 获取素材图数据（用于编辑弹窗显示参考图）
  const materialResult = session.step_results?.generate_material_images?.result_data
  const materialImages = useMemo<MaterialImage[]>(
    () => materialResult?.material_images || [],
    [materialResult?.material_images]
  )

  // 缓存编辑帧信息，只依赖 editModal 中的 segmentIndex 和 frameType，避免 frames/segments 更新时频繁重算
  const editFrameInfo = useMemo<EditFrameInfo>(() => {
    const { segmentIndex, frameType } = editModal
    const frame = frames.find((f) => f.segment_index === segmentIndex)
    const segment = segments[segmentIndex]
    const originalPrompt = frame
      ? (frameType === 'first' ? frame.first_prompt : frame.last_prompt) || ''
      : ''
    const currentImagePath = frame
      ? (frameType === 'first' ? frame.first_image_path : frame.last_image_path) || ''
      : ''

    return { frame, segment, originalPrompt, currentImagePath }
    // 注意：只有弹窗打开时才需要重新计算，避免轮询导致的频繁重渲染
  }, [editModal.segmentIndex, editModal.frameType, editModal.visible, frames, segments])

  // 打开编辑分片脚本弹窗
  const handleEditScript = (segmentIndex: number) => {
    const segment = segments[segmentIndex]
    if (!segment) return

    setEditingSegmentIndex(segmentIndex)
    editScriptForm.setFieldsValue(segment)
    setEditScriptModalVisible(true)
  }

  // 保存编辑的分片脚本
  const handleSaveScript = async () => {
    if (editingSegmentIndex === null) return

    try {
      const values = await editScriptForm.validateFields()
      setEditScriptLoading(true)

      const response = await segmentApi.update(session.session_id, editingSegmentIndex, {
        ...values,
        index: editingSegmentIndex,
      })

      if (response.success) {
        message.success(response.message)
        setEditScriptModalVisible(false)
        setEditingSegmentIndex(null)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setEditScriptLoading(false)
    }
  }

  // 删除分片脚本
  const handleDeleteSegment = async (index: number) => {
    Modal.confirm({
      title: '确定删除此分片？',
      icon: <ExclamationCircleOutlined />,
      content: '删除后相关的首尾帧数据也会被清除，此操作不可撤销。',
      onOk: async () => {
        try {
          const response = await segmentApi.delete(session.session_id, index)
          if (response.success) {
            message.success(response.message)
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        }
      },
    })
  }

  // 查看分片脚本文案（只读）
  const handleViewScript = (segmentIndex: number) => {
    const segment = segments[segmentIndex]
    if (!segment) return

    Modal.info({
      title: `分片 ${segmentIndex + 1} 的脚本文案`,
      width: 600,
      icon: <FileTextOutlined />,
      content: (
        <div style={{ marginTop: 16 }}>
          <div style={{ marginBottom: 12 }}>
            <Text type="secondary">时长：</Text>
            <Tag color="blue">{segment.duration} 秒</Tag>
          </div>
          <div style={{
            padding: 16,
            background: '#f5f5f5',
            borderRadius: 4,
            maxHeight: 300,
            overflowY: 'auto'
          }}>
            <Text style={{ whiteSpace: 'pre-wrap', lineHeight: 1.8 }}>
              {segment.content}
            </Text>
          </div>
          {segment.action && (
            <div style={{ marginTop: 12 }}>
              <Text type="secondary">动作：</Text>
              <Text>{segment.action}</Text>
            </div>
          )}
          {segment.camera_movement && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">镜头运动：</Text>
              <Text>{segment.camera_movement}</Text>
            </div>
          )}
          {segment.composition && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">构图：</Text>
              <Text>{segment.composition}</Text>
            </div>
          )}
          {segment.atmosphere && (
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">氛围：</Text>
              <Text>{segment.atmosphere}</Text>
            </div>
          )}
        </div>
      ),
      okText: '关闭',
    })
  }

  // 显示插入分片弹窗
  const showAddModal = (afterIndex: number) => {
    setInsertAfterIndex(afterIndex)
    addForm.resetFields()
    addForm.setFieldsValue({
      duration: 5,
    })
    setAddModalVisible(true)
  }

  // 处理插入分片
  const handleAddSegment = async () => {
    try {
      const values = await addForm.validateFields()
      setAddLoading(true)

      const response = await segmentApi.add(session.session_id, values, insertAfterIndex)
      if (response.success) {
        message.success(response.message)
        setAddModalVisible(false)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setAddLoading(false)
    }
  }

  // 为单个分片生成首尾帧
  const handleGenerateSingleFrames = async (segmentIndex: number) => {
    setGenerateSingleLoading(segmentIndex)
    try {
      // 同时生成首帧和尾帧
      const [firstResult, lastResult] = await Promise.all([
        frameApi.regenerate(session.session_id, segmentIndex, 'first'),
        frameApi.regenerate(session.session_id, segmentIndex, 'last'),
      ])

      if (firstResult.success && lastResult.success) {
        message.success(`分片 ${segmentIndex + 1} 的首尾帧生成成功`)
      } else {
        const errors = []
        if (!firstResult.success) errors.push('首帧生成失败')
        if (!lastResult.success) errors.push('尾帧生成失败')
        message.error(errors.join('，'))
      }
      await refreshSession()
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setGenerateSingleLoading(null)
    }
  }

  // 检查是否有正在进行的帧生成任务
  const hasPendingFrames = frames.length > 0 && frames.some(
    (frame: any) => frame.first_status === 'pending' || frame.last_status === 'pending'
  )
  // 检查是否处于后台生成中状态
  const isBackgroundGenerating = stepResult?._generating === true
  // 检查是否已被取消
  const isCancelled = stepResult?._cancelled === true
  // 综合判断是否正在生成
  const isGenerating = hasPendingFrames || isBackgroundGenerating || loading

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_videos'].includes(step)
  ).length || 0

  // 轮询任务状态：当有 pending 状态的帧或后台生成中时启用轮询
  usePolling(
    async () => {
      await refreshSession()
    },
    {
      interval: 3000, // 每3秒轮询一次
      enabled: hasPendingFrames || isBackgroundGenerating, // 有 pending 任务或后台生成中时启用轮询
    }
  )

  // 计算复用信息（使用 useMemo 避免重复计算）
  const reuseInfo = useMemo(() => {
    let generateCount = 0
    let reuseCount = 0
    const reuseDetails: Array<{ segmentIndex: number; frameType: string; sourceSegment: number }> = []

    segments.forEach((segment: any, index: number) => {
      // 首帧
      if (segment.first_frame_mode === 'reuse_prev' && index > 0) {
        reuseCount++
        reuseDetails.push({
          segmentIndex: index,
          frameType: 'first',
          sourceSegment: index - 1,
        })
      } else {
        generateCount++
      }

      // 尾帧（总是生成，不管是否被下一分片复用）
      generateCount++
    })

    return { generateCount, reuseCount, reuseDetails, totalSegments: segments.length }
  }, [segments])

  const handleGenerate = async () => {
    // 显示预览对话框
    Modal.confirm({
      title: '首尾帧生成预览',
      width: 600,
      icon: <BorderOutlined />,
      content: (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>统计信息：</Text>
            <ul style={{ marginTop: 8 }}>
              <li>
                <Text>总分片数：{reuseInfo.totalSegments} 个</Text>
              </li>
              <li>
                <Text>需要生成：{reuseInfo.generateCount} 张图片</Text>
              </li>
              <li>
                <Text style={{ color: '#52c41a' }}>
                  将复用：{reuseInfo.reuseCount} 张图片
                </Text>
              </li>
              <li>
                <Text>总帧数：{reuseInfo.totalSegments * 2} 张（{reuseInfo.generateCount} 生成 + {reuseInfo.reuseCount} 复用）</Text>
              </li>
            </ul>
          </div>

          {reuseInfo.reuseDetails.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <Text strong>复用详情1：</Text>
              <ul style={{ marginTop: 8, maxHeight: '200px', overflowY: 'auto', backgroundColor: '#efefef', padding: '2px 4px' }}>
                {reuseInfo.reuseDetails.map((detail, idx) => (
                  <li key={idx}>
                    <Text type="secondary">
                      分片 <span style={{ color: "red" }}>{detail.segmentIndex + 1}</span> 的首帧 → 复用自分片 <span style={{ color: "red" }}>{detail.sourceSegment + 1}</span> 的尾帧
                    </Text>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div style={{ marginTop: 16, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text type="secondary">
              💡 提示：相邻分片如果需要100%画面连续（如同一场景的连续动作），将自动复用帧以节省生成成本。
            </Text>
          </div>
        </div>
      ),
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.generateFrames(session.session_id)
          if (response.success) {
            message.loading('首尾帧生成任务已启动，正在生成中...', 2)
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

  const handleCancel = async () => {
    Modal.confirm({
      title: '确认停止生成？',
      icon: <ExclamationCircleOutlined />,
      content: '停止后，已提交的任务将继续完成，未提交的任务将不再执行。是否继续？',
      onOk: async () => {
        try {
          const response = await stepApi.cancelFrames(session.session_id)
          if (response.success) {
            message.success('停止请求已发送')
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        }
      },
    })
  }

  const handleReset = async () => {
    Modal.confirm({
      title: '确认重置首尾帧生成？',
      icon: <ExclamationCircleOutlined />,
      content: (
        <div>
          <p>重置将清空所有已生成的首尾帧数据，状态恢复为"未开始"。</p>
          {completedSubsequentSteps > 0 && (
            <p style={{ color: '#ff4d4f' }}>
              同时将清空后续 {completedSubsequentSteps} 个已完成的步骤数据。
            </p>
          )}
          <p>此操作不可撤销，是否继续？</p>
        </div>
      ),
      onOk: async () => {
        try {
          const response = await stepApi.resetFrames(session.session_id)
          if (response.success) {
            message.success('首尾帧状态已重置')
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        }
      },
      okText: '确认重置',
      okButtonProps: { danger: true },
      cancelText: '取消',
    })
  }

  const handleRegenerateAll = async () => {
    // 如果有后续步骤已完成，显示确认对话框
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新生成全部首尾帧？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
            </ul>
            <p>此操作不可撤销，是否继续？</p>
          </div>
        ),
        onOk: async () => {
          await executeRegenerateAll()
        },
      })
    } else {
      await executeRegenerateAll()
    }
  }

  const executeRegenerateAll = async () => {
    setLoading(true)
    try {
      const response = await stepApi.regenerateFrames(session.session_id)
      if (response.success) {
        message.loading('首尾帧重新生成任务已启动，正在生成中...', 2)
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
  }

  // 打开编辑弹窗
  const handleOpenEditModal = useCallback((segmentIndex: number, frameType: 'first' | 'last', prompt: string) => {
    // 直接使用传入的提示词，避免闭包中 frames 数据过时的问题
    const originalPrompt = prompt || ''

    // 默认全选所有素材图（原本生成首尾帧时使用的就是全部素材图）
    const allMaterialIndices = materialImages.map((_: any, idx: number) => idx)

    // 设置独立的输入框状态
    // 基于素材图模式：使用原始提示词
    setCustomPrompt(originalPrompt)
    // 基于当前帧模式：也使用原始提示词作为基础，用户可以在此基础上修改调整指令
    setCurrentFramePrompt(originalPrompt)

    setEditModal({
      visible: true,
      segmentIndex,
      frameType,
      activeTab: 'regenerate',
      selectedSourceSegment: null,
      selectedSourceFrameType: null,
      selectedMaterialIndices: allMaterialIndices, // 默认全选所有素材图
      regenerateMode: 'material', // 默认基于素材图模式
      uploadedMaterialPaths: [], // 重置上传的素材图
    })
  }, [materialImages])

  // 关闭编辑弹窗
  const handleCloseEditModal = useCallback(() => {
    setEditModal(prev => ({ ...prev, visible: false }))
  }, [])

  // 在编辑弹窗中执行重新生成
  const handleEditRegenerate = useCallback(async () => {
    const { segmentIndex, frameType, selectedMaterialIndices, regenerateMode, uploadedMaterialPaths } = editModal
    const key = `${segmentIndex}-${frameType}`
    console.log('handleEditRegenerate', key)

    let referenceImages: string[] = []
    let promptToUse: string | undefined

    if (regenerateMode === 'material') {
      // 基于素材图模式：获取选中的素材图路径列表
      const selectedMaterialPaths = selectedMaterialIndices
        .map(idx => materialImages[idx]?.image_path)
        .filter(Boolean)

      // 合并选中的素材图和上传的自定义素材图
      referenceImages = [...selectedMaterialPaths, ...uploadedMaterialPaths]

      // 如果没有任何素材图（选中的 + 上传的），给出提示
      if (referenceImages.length === 0) {
        message.warning('请至少选择一张素材图或上传自定义素材图作为参考')
        return
      }
      // 使用原始提示词
      promptToUse = customPrompt || undefined
    } else {
      // 基于当前帧模式：使用当前帧图片 + 可选的素材图作为参考
      if (!editFrameInfo.currentImagePath) {
        message.warning('当前帧暂无图片，无法使用此模式')
        return
      }
      // 当前帧作为第一个参考图（主参考）
      referenceImages = [editFrameInfo.currentImagePath]
      // 如果选择了素材图，也加入参考列表（辅助参考）
      const selectedMaterialPaths = selectedMaterialIndices
        .map(idx => materialImages[idx]?.image_path)
        .filter(Boolean)
      // 合并选中的素材图和上传的自定义素材图
      referenceImages = [...referenceImages, ...selectedMaterialPaths, ...uploadedMaterialPaths]
      // 使用当前帧模式的独立提示词
      promptToUse = currentFramePrompt || undefined
    }

    // 立即关闭弹窗，设置帧的 loading 状态
    handleCloseEditModal()
    setRegeneratingFrames(prev => ({ ...prev, [key]: true }))

    // 后台执行生成
    try {
      const response = await frameApi.regenerate(
        session.session_id,
        segmentIndex,
        frameType,
        promptToUse,
        referenceImages
      )
      if (response.success) {
        message.success(`分片 ${segmentIndex + 1} ${frameType === 'first' ? '首帧' : '尾帧'} 生成成功`)
      } else {
        message.error(`分片 ${segmentIndex + 1} ${frameType === 'first' ? '首帧' : '尾帧'} 生成失败: ${response.message}`)
      }
      await refreshSession()
    } catch (error) {
      message.error(`分片 ${segmentIndex + 1} ${frameType === 'first' ? '首帧' : '尾帧'} 生成失败: ${(error as Error).message}`)
    } finally {
      setRegeneratingFrames(prev => ({ ...prev, [key]: false }))
    }
  }, [editModal, customPrompt, currentFramePrompt, editFrameInfo.currentImagePath, materialImages, session.session_id, refreshSession, handleCloseEditModal])

  // 在编辑弹窗中执行复制帧
  const handleEditCopyFrame = async () => {
    const { segmentIndex, frameType, selectedSourceSegment, selectedSourceFrameType } = editModal
    if (selectedSourceSegment === null || selectedSourceFrameType === null) {
      message.warning('请选择要复制的帧')
      return
    }
    const key = `copy-${segmentIndex}-${frameType}`
    setActionLoading(key)
    try {
      const response = await frameApi.reuse(
        session.session_id,
        segmentIndex,
        frameType,
        selectedSourceSegment,
        selectedSourceFrameType
      )
      if (response.success) {
        message.success(response.message)
        handleCloseEditModal()
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setActionLoading(null)
    }
  }

  // 在编辑弹窗中执行上传
  const handleEditUpload = async (file: File) => {
    const { segmentIndex, frameType } = editModal
    const key = `upload-${segmentIndex}-${frameType}`
    setActionLoading(key)
    try {
      const uploadResult = await uploadApi.uploadImage(file)
      const response = await frameApi.upload(
        session.session_id,
        segmentIndex,
        frameType,
        uploadResult.file_path
      )
      if (response.success) {
        message.success(response.message)
        handleCloseEditModal()
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setActionLoading(null)
    }
  }

  // 获取所有可选的帧（排除当前帧）- 使用 useMemo 缓存
  const availableFramesForCopy = useMemo(() => {
    const available: Array<{
      segmentIndex: number
      frameType: 'first' | 'last'
      imagePath: string
      label: string
    }> = []

    frames.forEach((frame: any, idx: number) => {
      // 首帧
      if (frame.first_status === 'completed' && frame.first_image_path) {
        // 排除当前正在编辑的帧
        if (!(idx === editModal.segmentIndex && editModal.frameType === 'first')) {
          available.push({
            segmentIndex: idx,
            frameType: 'first',
            imagePath: frame.first_image_path,
            label: `分片 ${idx + 1} 首帧`,
          })
        }
      }
      // 尾帧
      if (frame.last_status === 'completed' && frame.last_image_path) {
        if (!(idx === editModal.segmentIndex && editModal.frameType === 'last')) {
          available.push({
            segmentIndex: idx,
            frameType: 'last',
            imagePath: frame.last_image_path,
            label: `分片 ${idx + 1} 尾帧`,
          })
        }
      }
    })

    return available
  }, [frames, editModal.segmentIndex, editModal.frameType])

  // 渲染帧状态标签
  const renderStatusTag = (status?: string) => {
    switch (status) {
      case 'pending':
        return <Tag icon={<LoadingOutlined />} color="processing">生成中</Tag>
      case 'completed':
        return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>
      case 'failed':
        return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
      default:
        return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
    }
  }

  // 渲染单个帧内容
  const renderFrameContent = (
    imagePath: string | undefined,
    status: string | undefined,
    segmentIndex: number,
    frameType: 'first' | 'last',
    label: string,
    prompt: string | undefined
  ) => {
    const key = `${segmentIndex}-${frameType}`
    const isRegenerating = regeneratingFrames[key] === true
    const isPending = status === 'pending'
    const isFailed = status === 'failed'
    const isFrameCompleted = status === 'completed' && imagePath

    // 检查是否为复用帧
    const segment = segments[segmentIndex]
    const isReusedFrame = frameType === 'first' && segment?.first_frame_mode === 'reuse_prev'

    return (
      <div style={{ textAlign: 'center' }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>{label}</Text>
          <span style={{ marginLeft: 8 }}>
            {isRegenerating ? (
              <Tag icon={<LoadingOutlined />} color="processing">重新生成中</Tag>
            ) : (
              renderStatusTag(status)
            )}
          </span>
          {isReusedFrame && (
            <Tag color="green" style={{ marginLeft: 4 }}>
              复用自分片{segmentIndex}
            </Tag>
          )}
        </div>
        <div style={{ marginTop: 8, position: 'relative' }}>
          {isFrameCompleted ? (
            <>
              <Image
                src={getImageSrc(imagePath)}
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
                height: 150,
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
                <>
                  <Spin tip="重新生成中..." />
                </>
              ) : (
                <>
                  <CloseCircleOutlined style={{ fontSize: 32, color: '#ff4d4f' }} />
                  <Text type="danger">生成失败</Text>
                </>
              )}
            </div>
          ) : (
            <div
              style={{
                height: 150,
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
          )}
        </div>
        {/* 只有完成或失败状态且不在重新生成中才显示操作按钮 */}
        {!isPending && !isGenerating && !isRegenerating && (
          <div style={{ marginTop: 8 }}>
            <Button
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleOpenEditModal(segmentIndex, frameType, prompt || '')}
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

  if (!canExecute) {
    return (
      <Card title="生成首尾帧" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤4：生成分片脚本</Text>
      </Card>
    )
  }

  // 当有帧数据时显示（包括生成中和已完成状态）
  if (frames.length > 0) {
    // 统计完成情况
    const completedFirstCount = frames.filter((f: any) => f.first_status === 'completed').length
    const completedLastCount = frames.filter((f: any) => f.last_status === 'completed').length
    const totalFrames = frames.length * 2
    const completedCount = completedFirstCount + completedLastCount
    const failedFirstCount = frames.filter((f: any) => f.first_status === 'failed').length
    const failedLastCount = frames.filter((f: any) => f.last_status === 'failed').length
    const failedCount = failedFirstCount + failedLastCount

    const isAllCompleted = completedCount === totalFrames && !isBackgroundGenerating
    const title = isCancelled ? (
      <span>
        <CloseCircleOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
        首尾帧生成已取消 ({completedCount}/{totalFrames})
        {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
      </span>
    ) : failedCount > 0 ?
      <span> 生成结果 ({completedCount}/{totalFrames}),{failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}</span>
      : isAllCompleted ? (
        <span>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
          首尾帧生成完成 ({frames.length} 个分片)
        </span>
      ) : (
        <span>
          <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          首尾帧生成中 ({completedCount}/{totalFrames})
          {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
        </span>
      )

    return (
      <Card
        title={title}
        extra={
          <Space>
            {isGenerating ? (
              <>
                <Button
                  danger
                  icon={<StopOutlined />}
                  onClick={handleCancel}
                >
                  停止生成
                </Button>
                <Button
                  icon={<UndoOutlined />}
                  onClick={handleReset}
                >
                  重置
                </Button>
              </>
            ) : isCancelled ? (
              <>
                <Button
                  type="primary"
                  icon={<ReloadOutlined />}
                  onClick={handleReset}
                >
                  重置并重新生成
                </Button>
              </>
            ) : (
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={handleRegenerateAll}
              >
                全部重新生成
              </Button>
            )}
          </Space>
        }
        style={{ marginTop: 16 }}
      >
        {isCancelled && (
          <div style={{ marginBottom: 16, padding: 12, background: '#fff2f0', borderRadius: 4 }}>
            <CloseCircleOutlined style={{ color: '#ff4d4f', marginRight: 8 }} />
            <span style={{ color: '#cf1322' }}>
              生成任务已取消。已完成 {completedCount}/{totalFrames} 个帧的生成。您可以选择重新生成全部首尾帧。
            </span>
          </div>
        )}
        {isCompleted && completedSubsequentSteps > 0 && (
          <div style={{ marginBottom: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <span style={{ color: '#ad6800' }}>
              后续已完成 {completedSubsequentSteps} 个步骤，全部重新生成将重置这些步骤
            </span>
          </div>
        )}
        <Row gutter={[16, 24]}>
          {frames.map((frame: any, index: number) => {
            // 使用帧的 segment_index 而不是数组索引，确保正确关联分片
            const segIdx = frame.segment_index ?? index
            const segment = segments[segIdx]
            return (
            <Col span={24} key={segIdx}>
              {/* 插入按钮（在每个分片之前，从第二个开始） */}
              {index > 0 && !isGenerating && (
                <div style={{ textAlign: 'center', margin: '8px 0 16px' }}>
                  <Button
                    type="dashed"
                    size="small"
                    icon={<PlusOutlined />}
                    onClick={() => showAddModal(segIdx - 1)}
                    style={{ borderStyle: 'dashed', color: '#1890ff' }}
                  >
                    插入分片
                  </Button>
                </div>
              )}
              <Card
                size="small"
                title={
                  <Space style={{ display: 'flex', justifyContent: 'space-between', width: '100%' }}>
                    <Space>
                      <Tag color="blue">分片 {segIdx + 1}</Tag>
                      <Tag>{segment?.duration || 0} 秒</Tag>
                      <Text ellipsis style={{ maxWidth: 300 }}>
                        {segment?.content?.substring(0, 40)}...
                      </Text>
                    </Space>
                    <Space>
                      <Button
                        size="small"
                        icon={<FileTextOutlined />}
                        onClick={() => handleViewScript(segIdx)}
                      >
                        查看
                      </Button>
                      <Button
                        size="small"
                        icon={<EditOutlined />}
                        onClick={() => handleEditScript(segIdx)}
                        disabled={isGenerating}
                      >
                        编辑脚本
                      </Button>
                      <Button
                        size="small"
                        danger
                        icon={<DeleteOutlined />}
                        onClick={() => handleDeleteSegment(segIdx)}
                        disabled={isGenerating}
                      >
                        删除
                      </Button>
                    </Space>
                  </Space>
                }
              >
                <Row gutter={16}>
                  <Col span={12}>
                    {renderFrameContent(
                      frame.first_image_path,
                      frame.first_status,
                      segIdx,
                      'first',
                      '首帧',
                      frame.first_prompt
                    )}
                  </Col>
                  <Col span={12}>
                    {renderFrameContent(
                      frame.last_image_path,
                      frame.last_status,
                      segIdx,
                      'last',
                      '尾帧',
                      frame.last_prompt
                    )}
                  </Col>
                </Row>
              </Card>
            </Col>
          )})}
          {/* 末尾插入按钮 */}
          {!isGenerating && (
            <Col span={24}>
              <div style={{ textAlign: 'center', margin: '16px 0' }}>
                <Button
                  type="dashed"
                  icon={<PlusOutlined />}
                  onClick={() => showAddModal(-1)}
                  style={{ borderStyle: 'dashed', color: '#1890ff' }}
                >
                  在末尾插入分片
                </Button>
              </div>
            </Col>
          )}
        </Row>

        {/* 编辑弹窗 */}
        <Modal
          title={`编辑分片 ${editModal.segmentIndex + 1} 的${editModal.frameType === 'first' ? '首' : '尾'}帧`}
          open={editModal.visible}
          onCancel={handleCloseEditModal}
          footer={null}
          width={700}
        >
          <Tabs
            activeKey={editModal.activeTab}
            onChange={(key) => setEditModal(prev => ({ ...prev, activeTab: key }))}
            items={[
              {
                key: 'regenerate',
                label: <span><ReloadOutlined /> 重新生成</span>,
                children: (
                  <RegenerateTab
                    editModal={editModal}
                    setEditModal={setEditModal}
                    editFrameInfo={editFrameInfo}
                    materialImages={materialImages}
                    customPrompt={customPrompt}
                    setCustomPrompt={setCustomPrompt}
                    currentFramePrompt={currentFramePrompt}
                    setCurrentFramePrompt={setCurrentFramePrompt}
                    actionLoading={actionLoading}
                    onRegenerate={handleEditRegenerate}
                  />
                ),
              },
              {
                key: 'copy',
                label: <span><CopyOutlined /> 选择已有帧</span>,
                children: (
                  <CopyTab
                    editModal={editModal}
                    setEditModal={setEditModal}
                    availableFramesForCopy={availableFramesForCopy}
                    actionLoading={actionLoading}
                    onCopyFrame={handleEditCopyFrame}
                  />
                ),
              },
              {
                key: 'upload',
                label: <span><UploadOutlined /> 上传替换</span>,
                children: (
                  <UploadTab
                    editModal={editModal}
                    actionLoading={actionLoading}
                    onUpload={handleEditUpload}
                  />
                ),
              },
            ]}
          />
        </Modal>

        {/* 插入分片弹窗 */}
        <Modal
          title={
            <span>
              <PlusOutlined style={{ marginRight: 8 }} />
              插入新分片
            </span>
          }
          open={addModalVisible}
          onOk={handleAddSegment}
          onCancel={() => setAddModalVisible(false)}
          okText="添加"
          cancelText="取消"
          confirmLoading={addLoading}
          width={700}
        >
          <div style={{ marginBottom: 16 }}>
            <Text type="secondary">
              {insertAfterIndex === -1
                ? '将在所有分片末尾添加新分片'
                : `将在分片 ${insertAfterIndex + 1} 之后插入新分片`}
            </Text>
          </div>
          <SegmentForm form={addForm} />
          <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <Text type="warning" style={{ fontSize: 12 }}>
              注意：插入新分片后，已有的首尾帧和视频数据将被清空，需要重新生成
            </Text>
          </div>
        </Modal>

        {/* 编辑分片脚本弹窗 */}
        <Modal
          title={
            <span>
              <EditOutlined style={{ marginRight: 8 }} />
              编辑分片 {editingSegmentIndex !== null ? editingSegmentIndex + 1 : ''} 脚本
            </span>
          }
          open={editScriptModalVisible}
          onOk={handleSaveScript}
          onCancel={() => {
            setEditScriptModalVisible(false)
            setEditingSegmentIndex(null)
          }}
          okText="保存"
          cancelText="取消"
          confirmLoading={editScriptLoading}
          width={700}
        >
          <SegmentForm form={editScriptForm} />
          <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <Text type="warning" style={{ fontSize: 12 }}>
              注意：修改分片脚本后，该分片的首尾帧需要重新生成以保持内容一致
            </Text>
          </div>
        </Modal>
      </Card>
    )
  }

  // 当后台正在生成但还没有帧数据时显示加载状态
  if (isBackgroundGenerating) {
    return (
      <Card
        title={
          <span>
            <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
            首尾帧生成中...
          </span>
        }
        extra={
          <Button
            icon={<UndoOutlined />}
            onClick={handleReset}
          >
            重置
          </Button>
        }
        style={{ marginTop: 16 }}
      >
        <div style={{ textAlign: 'center', padding: '40px 0' }}>
          <Spin size="large" />
          <div style={{ marginTop: 16 }}>
            <Text type="secondary">正在生成首尾帧，请稍候...</Text>
          </div>
        </div>
      </Card>
    )
  }

  // 初始状态：显示分片列表和生成按钮
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
            onClick={handleGenerate}
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
          <Row gutter={[16, 16]}>
            {segments.map((segment: any, index: number) => (
              <Col span={24} key={index}>
                {/* 插入按钮（在每个分片之前，从第二个开始） */}
                {index > 0 && (
                  <div style={{ textAlign: 'center', margin: '8px 0 16px' }}>
                    <Button
                      type="dashed"
                      size="small"
                      icon={<PlusOutlined />}
                      onClick={() => showAddModal(index - 1)}
                      style={{ borderStyle: 'dashed', color: '#1890ff' }}
                    >
                      插入分片
                    </Button>
                  </div>
                )}
                <Card size="small" style={{ background: '#fafafa' }}>
                  <Row justify="space-between" align="middle">
                    <Col>
                      <Space>
                        <Tag color="blue">分片 {index + 1}</Tag>
                        <Tag>{segment.duration} 秒</Tag>
                        <Text ellipsis style={{ maxWidth: 300 }}>
                          {segment.content?.substring(0, 50)}...
                        </Text>
                      </Space>
                    </Col>
                    <Col>
                      <Space>
                        <Button
                          size="small"
                          icon={<FileTextOutlined />}
                          onClick={() => handleViewScript(index)}
                        >
                          查看
                        </Button>
                        <Button
                          size="small"
                          icon={<EditOutlined />}
                          onClick={() => handleEditScript(index)}
                        >
                          编辑脚本
                        </Button>
                        <Button
                          size="small"
                          danger
                          icon={<DeleteOutlined />}
                          onClick={() => handleDeleteSegment(index)}
                        >
                          删除
                        </Button>
                        <Button
                          type="primary"
                          size="small"
                          icon={<PlayCircleOutlined />}
                          onClick={() => handleGenerateSingleFrames(index)}
                          loading={generateSingleLoading === index}
                        >
                          生成首尾帧
                        </Button>
                      </Space>
                    </Col>
                  </Row>
                </Card>
              </Col>
            ))}
            {/* 末尾插入按钮 */}
            <Col span={24}>
              <div style={{ textAlign: 'center', margin: '16px 0' }}>
                <Button
                  type="dashed"
                  icon={<PlusOutlined />}
                  onClick={() => showAddModal(-1)}
                  style={{ borderStyle: 'dashed', color: '#1890ff' }}
                >
                  在末尾插入分片
                </Button>
              </div>
            </Col>
          </Row>
        </div>
      )}

      {/* 插入分片弹窗 */}
      <Modal
        title={
          <span>
            <PlusOutlined style={{ marginRight: 8 }} />
            插入新分片
          </span>
        }
        open={addModalVisible}
        onOk={handleAddSegment}
        onCancel={() => setAddModalVisible(false)}
        okText="添加"
        cancelText="取消"
        confirmLoading={addLoading}
        width={700}
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            {insertAfterIndex === -1
              ? '将在所有分片末尾添加新分片'
              : `将在分片 ${insertAfterIndex + 1} 之后插入新分片`}
          </Text>
        </div>
        <SegmentForm form={addForm} />
        <div style={{ marginTop: 16, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
          <ExclamationCircleOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          <Text type="secondary" style={{ fontSize: 12 }}>
            提示：添加新分片后，可以点击"生成首尾帧"按钮为该分片单独生成首尾帧
          </Text>
        </div>
      </Modal>

      {/* 编辑分片脚本弹窗 */}
      <Modal
        title={
          <span>
            <EditOutlined style={{ marginRight: 8 }} />
            编辑分片 {editingSegmentIndex !== null ? editingSegmentIndex + 1 : ''} 脚本
          </span>
        }
        open={editScriptModalVisible}
        onOk={handleSaveScript}
        onCancel={() => {
          setEditScriptModalVisible(false)
          setEditingSegmentIndex(null)
        }}
        okText="保存"
        cancelText="取消"
        confirmLoading={editScriptLoading}
        width={700}
      >
        <SegmentForm form={editScriptForm} />
        <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
          <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
          <Text type="warning" style={{ fontSize: 12 }}>
            注意：修改分片脚本后，该分片的首尾帧需要重新生成以保持内容一致
          </Text>
        </div>
      </Modal>
    </Card>
  )
}
