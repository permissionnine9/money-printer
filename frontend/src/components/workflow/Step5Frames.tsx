/**
 * 步骤5：生成首尾帧
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 显示每个帧的生成进度
 */
import React, { useState, useMemo, useCallback, useEffect } from 'react'
import {
  Card,
  Button,
  message,
  Typography,
  Row,
  Col,
  Space,
  Tag,
  Modal,
  Tabs,
  Form,
  InputNumber,
  Tooltip,
} from 'antd'
import {
  BorderOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  UploadOutlined,
  ExclamationCircleOutlined,
  LoadingOutlined,
  CloseCircleOutlined,
  UndoOutlined,
  FileTextOutlined,
  CopyOutlined,
  PlusOutlined,
  StopOutlined,
  InfoCircleOutlined,
} from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi, frameApi, uploadApi, segmentApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'
import { RegenerateTab } from './Step5Frames/RegenerateTab'
import { CopyTab } from './Step5Frames/CopyTab'
import { UploadTab } from './Step5Frames/UploadTab'
import { SegmentCard } from './Step5Frames/SegmentCard'
import { InitialView } from './Step5Frames/InitialView'
import { GeneratingView } from './Step5Frames/GeneratingView'
import { AddSegmentModal } from './Step5Frames/AddSegmentModal'
import { EditScriptModal } from './Step5Frames/EditScriptModal'
import { GeneratePreviewModal } from './Step5Frames/GeneratePreviewModal'
import type {
  MaterialImage,
  FrameData,
  SegmentInfo,
  EditFrameInfo,
  EditModalState,
  ReuseInfo,
} from './Step5Frames/types'

const { Text } = Typography

interface Step5FramesProps {
  session: SessionDetail
}

export const Step5Frames: React.FC<Step5FramesProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const refreshSession = useSessionStore(useCallback((state) => state.refreshSession, []))

  // 编辑弹窗状态
  const [editModal, setEditModal] = useState<EditModalState>({
    visible: false,
    segmentIndex: 0,
    frameType: 'first',
    activeTab: 'regenerate',
    selectedSourceSegment: null,
    selectedSourceFrameType: null,
    selectedMaterialIndices: [],
    regenerateMode: 'material',
    uploadedMaterialPaths: [],
  })

  // 输入框状态
  const [customPrompt, setCustomPrompt] = useState('')
  const [currentFramePrompt, setCurrentFramePrompt] = useState('')

  // 插入分片弹窗状态
  const [addModalVisible, setAddModalVisible] = useState(false)
  const [insertAfterIndex, setInsertAfterIndex] = useState<number>(-1)
  const [addForm] = Form.useForm()
  const [addLoading, setAddLoading] = useState(false)

  // 单个分片生成首尾帧的loading状态
  const [generateSingleLoading, setGenerateSingleLoading] = useState<number | null>(null)

  // 单个帧重新生成的loading状态
  const [regeneratingFrames, setRegeneratingFrames] = useState<Record<string, boolean>>({})

  // 编辑分片脚本弹窗状态
  const [editScriptModalVisible, setEditScriptModalVisible] = useState(false)
  const [editingSegmentIndex, setEditingSegmentIndex] = useState<number | null>(null)
  const [editScriptForm] = Form.useForm()
  const [editScriptLoading, setEditScriptLoading] = useState(false)

  // 视频生成模式变更loading状态
  const [changingVideoMode, setChangingVideoMode] = useState<number | null>(null)

  // 相邻分片 overlap 参数（秒），从步骤1的视频参数读取
  const videoParamsData = session.step_results?.submit_script_and_params?.result_data?.video_params
  const savedOverlap = typeof videoParamsData?.overlap_seconds === 'number' ? videoParamsData.overlap_seconds : 0
  const [overlapValue, setOverlapValue] = useState<number>(savedOverlap)
  // 保存后同步输入框显示值
  useEffect(() => {
    setOverlapValue(savedOverlap)
  }, [savedOverlap])

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('generate_segment_scripts')

  const stepResult = session.step_results?.generate_segment_frames?.result_data
  const frames = useMemo<FrameData[]>(
    () => stepResult?.segment_frames || [],
    [stepResult?.segment_frames]
  )

  // 获取分片脚本数据
  const segmentScriptsResult = session.step_results?.generate_segment_scripts?.result_data
  const segments = useMemo<SegmentInfo[]>(
    () => segmentScriptsResult?.segment_scripts || [],
    [segmentScriptsResult?.segment_scripts]
  )

  // 计算第五步是否完成
  const isCompleted = useMemo(() => {
    const backendCompleted = session.completed_steps?.includes('generate_segment_frames')
    if (backendCompleted) return true
    if (frames.length === 0 || segments.length === 0) return false

    return frames.every((frame: FrameData) => {
      const segmentIndex = frame.segment_index
      const segment = segments[segmentIndex]
      if (!segment) return false

      const firstPath = frame.first_image_path
      const lastPath = frame.last_image_path
      const videoMode = segment.video_generation_mode
      const firstFrameMode = segment.first_frame_mode

      if (videoMode === 'first_frame_reference') {
        return !!firstPath
      }
      if (firstFrameMode === 'use_video_snapshot') {
        return !!lastPath
      }
      return !!firstPath && !!lastPath
    })
  }, [session.completed_steps, frames, segments])

  // 获取素材图数据
  const materialResult = session.step_results?.generate_material_images?.result_data
  const materialImages = useMemo<MaterialImage[]>(
    () => materialResult?.material_images || [],
    [materialResult?.material_images]
  )

  // 缓存编辑帧信息
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
  }, [editModal.segmentIndex, editModal.frameType, editModal.visible, frames, segments])

  // 检查是否有正在进行的帧生成任务
  const hasPendingFrames = frames.length > 0 && frames.some(
    (frame: FrameData) => frame.first_status === 'pending' || frame.last_status === 'pending'
  )
  const isBackgroundGenerating = stepResult?._generating === true
  const isCancelled = stepResult?._cancelled === true
  const isGenerating = hasPendingFrames || isBackgroundGenerating || loading

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_videos'].includes(step)
  ).length || 0

  // 轮询任务状态
  usePolling(
    async () => {
      await refreshSession()
    },
    {
      interval: 3000,
      enabled: hasPendingFrames || isBackgroundGenerating,
    }
  )

  // 计算复用信息
  const reuseInfo = useMemo<ReuseInfo>(() => {
    let generateCount = 0
    let reuseCount = 0
    const reuseDetails: Array<{ segmentIndex: number; frameType: string; sourceSegment: number }> = []

    segments.forEach((segment: SegmentInfo, index: number) => {
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
      generateCount++
    })

    return { generateCount, reuseCount, reuseDetails, totalSegments: segments.length }
  }, [segments])

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

  // 处理视频生成模式变更
  const handleVideoModeChange = async (segmentIndex: number, mode: string) => {
    setChangingVideoMode(segmentIndex)
    try {
      const segment = segments[segmentIndex]
      if (!segment) return
      const response = await segmentApi.update(session.session_id, segmentIndex, {
        ...segment,
        index: segmentIndex,
        video_generation_mode: mode,
      })
      if (response.success) {
        message.success(`分片 ${segmentIndex + 1} 视频生成模式已更新`)
        await refreshSession()
        if (mode === 'first_frame_reference') {
          try {
            const checkResult = await frameApi.checkCompletion(session.session_id)
            if (checkResult.step_completed) {
              message.success('步骤5已完成：所有首尾帧已配置完成，可以进入步骤6')
              await refreshSession()
            }
          } catch (e) {
            console.error(e)
            // 忽略检查错误
          }
        }
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setChangingVideoMode(null)
    }
  }

  // 处理首帧模式变更（使用视频快照或普通生成）
  const handleFirstFrameModeChange = async (segmentIndex: number, mode: string | undefined) => {
    setChangingVideoMode(segmentIndex)
    try {
      const segment = segments[segmentIndex]
      if (!segment) return
      const response = await segmentApi.update(session.session_id, segmentIndex, {
        ...segment,
        index: segmentIndex,
        first_frame_mode: mode,
      })
      if (response.success) {
        if (mode === 'use_video_snapshot') {
          message.success(`分片 ${segmentIndex + 1} 将使用上一个分片视频的结尾快照图作为首帧`)
        } else {
          message.success(`分片 ${segmentIndex + 1} 首帧模式已更新`)
        }
        await refreshSession()
        // 检查步骤是否完成
        try {
          const checkResult = await frameApi.checkCompletion(session.session_id)
          if (checkResult.step_completed) {
            message.success('步骤5已完成：所有首尾帧已配置完成，可以进入步骤6')
            await refreshSession()
          }
        } catch (e) {
          console.error(e)
          // 忽略检查错误
        }
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setChangingVideoMode(null)
    }
  }

  // 处理尾帧参考模式变更（含全能参考模式）
  const handleLastFrameModeChange = async (segmentIndex: number, mode: string) => {
    setChangingVideoMode(segmentIndex)
    try {
      const segment = segments[segmentIndex]
      if (!segment) return
      const response = await segmentApi.update(session.session_id, segmentIndex, {
        ...segment,
        index: segmentIndex,
        last_frame_mode: mode,
      })
      if (response.success) {
        const modeNames: Record<string, string> = {
          generate: '仅素材图',
          generate_continuous: '连贯生成',
          all_reference: '全能参考（素材图+前片尾帧+后片首帧）',
        }
        message.success(`分片 ${segmentIndex + 1} 尾帧参考模式已更新：${modeNames[mode] || mode}`)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setChangingVideoMode(null)
    }
  }

  // 保存相邻分片 overlap 参数
  const handleSaveOverlap = async () => {
    try {
      const response = await frameApi.updateOverlap(session.session_id, overlapValue)
      if (response.success) {
        message.success(response.message)
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
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

  // 查看分片脚本文案
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
    addForm.setFieldsValue({ duration: 5 })
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
      const frame = frames.find(f => f.segment_index === segmentIndex)
      const results = []
      const messages = []

      if (!frame || frame.first_status === 'waiting') {
        const firstResult = await frameApi.regenerate(session.session_id, segmentIndex, 'first')
        results.push(firstResult)
        messages.push(firstResult.success ? '首帧生成成功' : '首帧生成失败')
      }

      if (!frame || frame.last_status === 'waiting') {
        const lastResult = await frameApi.regenerate(session.session_id, segmentIndex, 'last')
        results.push(lastResult)
        messages.push(lastResult.success ? '尾帧生成成功' : '尾帧生成失败')
      }

      const successCount = results.filter(r => r.success).length
      if (successCount === results.length) {
        message.success(`分片 ${segmentIndex + 1} 的${results.length > 1 ? '首尾帧' : '帧'}生成成功`)
      } else {
        message.error(messages.join('，'))
      }
      await refreshSession()
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setGenerateSingleLoading(null)
    }
  }

  // 生成单个帧
  const handleGenerateSingleFrame = async (segmentIndex: number, frameType: 'first' | 'last') => {
    setGenerateSingleLoading(segmentIndex)
    try {
      const result = await frameApi.regenerate(session.session_id, segmentIndex, frameType)
      if (result.success) {
        message.success(`分片 ${segmentIndex + 1} 的${frameType === 'first' ? '首帧' : '尾帧'}生成成功`)
        await refreshSession()
      } else {
        message.error(`分片 ${segmentIndex + 1} 的${frameType === 'first' ? '首帧' : '尾帧'}生成失败`)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setGenerateSingleLoading(null)
    }
  }

  // 处理生成
  const handleGenerate = async () => {
    Modal.confirm({
      title: '首尾帧生成预览',
      width: 600,
      icon: <BorderOutlined />,
      content: <GeneratePreviewModal reuseInfo={reuseInfo} />,
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.generateFrames(session.session_id)
          if (response.success) {
            message.loading('首尾帧生成任务已启动，正在生成中...', 2)
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

  // 停止生成
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

  // 重置
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

  // 全部重新生成
  const handleRegenerateAll = async () => {
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新生成全部首尾帧？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {session.completed_steps?.includes('generate_videos') && <li>步骤7：生成视频</li>}
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
    const originalPrompt = prompt || ''
    const allMaterialIndices = materialImages.map((_: unknown, idx: number) => idx)
    setCustomPrompt(originalPrompt)
    setCurrentFramePrompt(originalPrompt)
    setEditModal({
      visible: true,
      segmentIndex,
      frameType,
      activeTab: 'regenerate',
      selectedSourceSegment: null,
      selectedSourceFrameType: null,
      selectedMaterialIndices: allMaterialIndices,
      regenerateMode: 'material',
      uploadedMaterialPaths: [],
    })
  }, [materialImages])

  // 关闭编辑弹窗
  const handleCloseEditModal = useCallback(() => {
    setEditModal((prev: EditModalState) => ({ ...prev, visible: false }))
  }, [])

  // 在编辑弹窗中执行重新生成
  const handleEditRegenerate = useCallback(async () => {
    const { segmentIndex, frameType, selectedMaterialIndices, regenerateMode, uploadedMaterialPaths } = editModal
    const key = `${segmentIndex}-${frameType}`

    let referenceImages: string[] = []
    let promptToUse: string | undefined

    if (regenerateMode === 'material') {
      const selectedMaterialPaths = selectedMaterialIndices
        .map(idx => materialImages[idx]?.image_path)
        .filter(Boolean) as string[]
      referenceImages = [...selectedMaterialPaths, ...uploadedMaterialPaths]
      if (referenceImages.length === 0) {
        message.warning('请至少选择一张素材图或上传自定义素材图作为参考')
        return
      }
      promptToUse = customPrompt || undefined
    } else {
      if (!editFrameInfo.currentImagePath) {
        message.warning('当前帧暂无图片，无法使用此模式')
        return
      }
      referenceImages = [editFrameInfo.currentImagePath]
      const selectedMaterialPaths = selectedMaterialIndices
        .map(idx => materialImages[idx]?.image_path)
        .filter(Boolean) as string[]
      referenceImages = [...referenceImages, ...selectedMaterialPaths, ...uploadedMaterialPaths]
      promptToUse = currentFramePrompt || undefined
    }

    handleCloseEditModal()
    setRegeneratingFrames((prev: Record<string, boolean>) => ({ ...prev, [key]: true }))

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
        await refreshSession()
        try {
          const checkResult = await frameApi.checkCompletion(session.session_id)
          if (checkResult.step_completed) {
            message.success('步骤5已完成：所有首尾帧已配置完成，可以进入步骤6')
            await refreshSession()
          }
        } catch (e) {
          console.error(e)
          // 忽略检查错误
        }
      } else {
        message.error(`分片 ${segmentIndex + 1} ${frameType === 'first' ? '首帧' : '尾帧'} 生成失败: ${response.message}`)
      }
    } catch (error) {
      message.error(`分片 ${segmentIndex + 1} ${frameType === 'first' ? '首帧' : '尾帧'} 生成失败: ${(error as Error).message}`)
    } finally {
      setRegeneratingFrames((prev: Record<string, boolean>) => ({ ...prev, [key]: false }))
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
        try {
          const checkResult = await frameApi.checkCompletion(session.session_id)
          if (checkResult.step_completed) {
            message.success('步骤5已完成：所有首尾帧已配置完成，可以进入步骤6')
            await refreshSession()
          }
        } catch (e) {
          // 忽略检查错误
        }
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
        try {
          const checkResult = await frameApi.checkCompletion(session.session_id)
          if (checkResult.step_completed) {
            message.success('步骤5已完成：所有首尾帧已配置完成，可以进入步骤6')
            await refreshSession()
          }
        } catch (e) {
          // 忽略检查错误
        }
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setActionLoading(null)
    }
  }

  // 获取所有可选的帧
  const availableFramesForCopy = useMemo(() => {
    const available: Array<{
      segmentIndex: number
      frameType: 'first' | 'last'
      imagePath: string
      label: string
    }> = []

    frames.forEach((frame: FrameData, idx: number) => {
      if (frame.first_status === 'completed' && frame.first_image_path) {
        if (!(idx === editModal.segmentIndex && editModal.frameType === 'first')) {
          available.push({
            segmentIndex: idx,
            frameType: 'first',
            imagePath: frame.first_image_path,
            label: `分片 ${idx + 1} 首帧`,
          })
        }
      }
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

  // 前置步骤未完成的显示
  if (!canExecute) {
    return (
      <Card title="生成首尾帧" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤5：生成分片脚本</Text>
      </Card>
    )
  }

  // 后台生成中但还没有帧数据
  if (isBackgroundGenerating && frames.length === 0) {
    return <GeneratingView onReset={handleReset} />
  }

  // 初始状态：显示分片列表和生成按钮
  if (frames.length === 0) {
    return (
      <>
        <InitialView
          segments={segments}
          reuseInfo={reuseInfo}
          isGenerating={isGenerating}
          changingVideoMode={changingVideoMode}
          generateSingleLoading={generateSingleLoading}
          addModalVisible={addModalVisible}
          onGenerate={handleGenerate}
          onViewScript={handleViewScript}
          onEditScript={handleEditScript}
          onDeleteSegment={handleDeleteSegment}
          onVideoModeChange={handleVideoModeChange}
          onGenerateSingleFrames={handleGenerateSingleFrames}
          onGenerateSingleFrame={handleGenerateSingleFrame}
          onShowAddModal={showAddModal}
          onFirstFrameModeChange={handleFirstFrameModeChange}
        />
        <AddSegmentModal
          visible={addModalVisible}
          insertAfterIndex={insertAfterIndex}
          form={addForm}
          loading={addLoading}
          onOk={handleAddSegment}
          onCancel={() => setAddModalVisible(false)}
        />
        <EditScriptModal
          visible={editScriptModalVisible}
          editingSegmentIndex={editingSegmentIndex}
          form={editScriptForm}
          loading={editScriptLoading}
          onOk={handleSaveScript}
          onCancel={() => {
            setEditScriptModalVisible(false)
            setEditingSegmentIndex(null)
          }}
        />
      </>
    )
  }

  // 统计完成情况
  let completedCount = 0
  let failedCount = 0
  let totalRequiredFrames = 0

  frames.forEach((frame: FrameData) => {
    const segmentIndex = frame.segment_index
    const segment = segments[segmentIndex]
    const videoMode = segment?.video_generation_mode
    const firstFrameMode = segment?.first_frame_mode

    if (videoMode === 'first_frame_reference') {
      totalRequiredFrames += 1
      if (frame.first_status === 'completed') completedCount += 1
      if (frame.first_status === 'failed') failedCount += 1
    } else if (firstFrameMode === 'use_video_snapshot') {
      totalRequiredFrames += 1
      if (frame.last_status === 'completed') completedCount += 1
      if (frame.last_status === 'failed') failedCount += 1
    } else {
      totalRequiredFrames += 2
      if (frame.first_status === 'completed') completedCount += 1
      if (frame.first_status === 'failed') failedCount += 1
      if (frame.last_status === 'completed') completedCount += 1
      if (frame.last_status === 'failed') failedCount += 1
    }
  })

  const totalFrames = frames.length * 2
  const isAllCompleted = completedCount === totalRequiredFrames && !isBackgroundGenerating && totalRequiredFrames > 0
  const specialModeCount = frames.filter((f: FrameData) => {
    const seg = segments[f.segment_index]
    return seg?.video_generation_mode === 'first_frame_reference' ||
      seg?.first_frame_mode === 'use_video_snapshot'
  }).length

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
        首尾帧配置完成 ({frames.length} 个分片{specialModeCount > 0 && <span>，含{specialModeCount}个特殊模式</span>})
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
              <Button danger icon={<StopOutlined />} onClick={handleCancel}>
                停止生成
              </Button>
              <Button icon={<UndoOutlined />} onClick={handleReset}>
                重置
              </Button>
            </>
          ) : isCancelled ? (
            <Button type="primary" icon={<ReloadOutlined />} onClick={handleReset}>
              重置并重新生成
            </Button>
          ) : (
            <Button type="primary" icon={<ReloadOutlined />} onClick={handleRegenerateAll}>
              全部重新生成
            </Button>
          )}
        </Space>
      }
      style={{ marginTop: 16 }}
    >
      {/* 相邻分片 overlap 参数设置（用于步骤7视频生成的段间过渡衔接） */}
      <div
        style={{
          marginBottom: 16,
          padding: 12,
          background: '#f0f5ff',
          borderRadius: 4,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 8,
        }}
      >
        <Text>
          <Tooltip title="相邻两个分片视频段之间的重叠时长（秒），生成视频时用于段间过渡衔接，保证画面连贯。将自动对齐到 ComfyUI 要求的帧数规则（0 或 5+17n 帧）。">
            <InfoCircleOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          </Tooltip>
          相邻分片 overlap（段间重叠）
        </Text>
        <Space>
          <Space.Compact>
            <InputNumber
              min={0}
              max={5}
              step={0.5}
              value={overlapValue}
              onChange={(v) => setOverlapValue(typeof v === 'number' ? v : 0)}
              style={{ width: 100 }}
            />
            <Button disabled style={{ pointerEvents: 'none' }}>秒</Button>
          </Space.Compact>
          <Button size="small" type="primary" onClick={handleSaveOverlap}>
            保存 overlap
          </Button>
        </Space>
      </div>
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
        {segments.map((segment: SegmentInfo, segIdx: number) => {
          const frame = frames.find((f: FrameData) => f.segment_index === segIdx)
          return (
            <Col span={24} key={segIdx}>
              <SegmentCard
                segmentIndex={segIdx}
                segment={segment}
                frame={frame}
                isGenerating={isGenerating}
                changingVideoMode={changingVideoMode}
                generateSingleLoading={generateSingleLoading}
                regeneratingFrames={regeneratingFrames}
                actionLoading={actionLoading}
                isFirstSegment={segIdx === 0}
                onViewScript={handleViewScript}
                onEditScript={handleEditScript}
                onDeleteSegment={handleDeleteSegment}
                onVideoModeChange={handleVideoModeChange}
                onGenerateSingleFrame={handleGenerateSingleFrame}
                onGenerateSingleFrames={handleGenerateSingleFrames}
                onEditFrame={handleOpenEditModal}
                onInsertSegment={showAddModal}
                onFirstFrameModeChange={handleFirstFrameModeChange}
                onLastFrameModeChange={handleLastFrameModeChange}
              />
            </Col>
          )
        })}
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
          onChange={(key) => setEditModal((prev: EditModalState) => ({ ...prev, activeTab: key }))}
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
      <AddSegmentModal
        visible={addModalVisible}
        insertAfterIndex={insertAfterIndex}
        form={addForm}
        loading={addLoading}
        onOk={handleAddSegment}
        onCancel={() => setAddModalVisible(false)}
      />

      {/* 编辑分片脚本弹窗 */}
      <EditScriptModal
        visible={editScriptModalVisible}
        editingSegmentIndex={editingSegmentIndex}
        form={editScriptForm}
        loading={editScriptLoading}
        onOk={handleSaveScript}
        onCancel={() => {
          setEditScriptModalVisible(false)
          setEditingSegmentIndex(null)
        }}
      />
    </Card>
  )
}
