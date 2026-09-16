/**
 * 步骤3：生成素材图
 */
import React, { useState } from 'react'
import { Card, Button, message, Spin, Typography, Image, Row, Col, Popconfirm, Tag, Modal, Space, Input, Upload, Tooltip } from 'antd'
import { PictureOutlined, CheckCircleOutlined, ReloadOutlined, DeleteOutlined, LoadingOutlined, ClockCircleOutlined, CloseCircleOutlined, ExclamationCircleOutlined, EditOutlined, PlusOutlined, UploadOutlined } from '@ant-design/icons'
import type { SessionDetail, MaterialImage } from '@/types'
import { stepApi, materialApi, uploadApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'

const { Text } = Typography
const { TextArea } = Input

// 辅助函数：处理图片路径，支持本地路径和完整URL
const getImageSrc = (path: string | undefined): string => {
  if (!path) return ''
  // 如果是完整URL，直接返回
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  // 本地路径，加上前缀
  return `/${path}`
}

interface Step3MaterialsProps {
  session: SessionDetail
}

// 编辑对话框状态接口
interface EditModalState {
  visible: boolean
  index: number
  originalPath: string
  description: string
  referenceImages: string[]
  prompt: string  // 完整提示词
  loading: boolean
}

// 生成配置对话框状态接口
interface GenerateConfigModalState {
  visible: boolean
  isRegenerate: boolean  // 是否为重新生成
  extraPrompt: string
  referenceImages: string[]
  loading: boolean
}

// 新增素材图对话框状态接口
interface AddMaterialModalState {
  visible: boolean
  prompt: string
  description: string
  referenceImages: string[]
  loading: boolean
}

export const Step3Materials: React.FC<Step3MaterialsProps> = ({ session }) => {
  const [actionLoading, setActionLoading] = useState<number | null>(null)
  const [isStartingGenerate, setIsStartingGenerate] = useState(false)
  const { refreshSession } = useSessionStore()

  // 编辑对话框状态
  const [editModal, setEditModal] = useState<EditModalState>({
    visible: false,
    index: -1,
    originalPath: '',
    description: '',
    referenceImages: [],
    prompt: '',
    loading: false,
  })

  // 生成配置对话框状态
  const [generateConfigModal, setGenerateConfigModal] = useState<GenerateConfigModalState>({
    visible: false,
    isRegenerate: false,
    extraPrompt: '',
    referenceImages: [],
    loading: false,
  })

  // 新增素材图对话框状态
  const [addMaterialModal, setAddMaterialModal] = useState<AddMaterialModalState>({
    visible: false,
    prompt: '',
    description: '',
    referenceImages: [],
    loading: false,
  })

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('optimize_script')
  const stepResult = session.step_results?.generate_material_images?.result_data
  const materials: MaterialImage[] = stepResult?.material_images || []

  // 检查是否有正在进行的素材图生成任务
  const hasPendingMaterials = materials.length > 0 && materials.some((m) => m.task_status === 'pending')
  // 检查是否处于后台生成中状态（空数组但标记为 _generating）
  const isBackgroundGenerating = stepResult?._generating === true && materials.length === 0
  const isGenerating = hasPendingMaterials || isStartingGenerate || isBackgroundGenerating

  // 检查步骤是否已完成
  const isCompleted = session.completed_steps?.includes('generate_material_images')

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_segment_scripts', 'generate_segment_frames', 'generate_videos'].includes(step)
  ).length || 0

  // 轮询任务状态：当有 pending 状态的素材图或后台生成中时启用轮询
  usePolling(
    async () => {
      await refreshSession()
    },
    {
      interval: 3000, // 每3秒轮询一次
      enabled: hasPendingMaterials || isBackgroundGenerating, // 有 pending 任务或后台生成中时启用轮询
    }
  )

  const handleGenerate = () => {
    // 打开生成配置对话框
    setGenerateConfigModal({
      visible: true,
      isRegenerate: false,
      extraPrompt: '',
      referenceImages: [],
      loading: false,
    })
  }

  const executeGenerate = async () => {
    setGenerateConfigModal(prev => ({ ...prev, loading: true }))
    setIsStartingGenerate(true)
    try {
      const response = await stepApi.generateMaterials(
        session.session_id,
        generateConfigModal.extraPrompt || undefined,
        generateConfigModal.referenceImages.length > 0 ? generateConfigModal.referenceImages : undefined
      )
      if (response.success) {
        message.loading('素材图生成任务已启动，正在生成中...', 2)
        setGenerateConfigModal({ visible: false, isRegenerate: false, extraPrompt: '', referenceImages: [], loading: false })
        // 立即刷新以获取pending状态，触发轮询
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setIsStartingGenerate(false)
      setGenerateConfigModal(prev => ({ ...prev, loading: false }))
    }
  }

  const handleRegenerate = () => {
    // 如果有后续步骤已完成，显示确认对话框
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新生成素材图？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {session.completed_steps?.includes('generate_segment_scripts') && <li>步骤4：生成分片脚本</li>}
              {session.completed_steps?.includes('generate_segment_frames') && <li>步骤5：生成首尾帧</li>}
              {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
            </ul>
            <p>此操作不可撤销，是否继续？</p>
          </div>
        ),
        onOk: () => {
          openRegenerateConfig()
        },
      })
    } else {
      openRegenerateConfig()
    }
  }

  const openRegenerateConfig = () => {
    // 打开重新生成配置对话框
    setGenerateConfigModal({
      visible: true,
      isRegenerate: true,
      extraPrompt: '',
      referenceImages: [],
      loading: false,
    })
  }

  const executeRegenerate = async () => {
    setGenerateConfigModal(prev => ({ ...prev, loading: true }))
    setIsStartingGenerate(true)
    try {
      const response = await stepApi.regenerateMaterials(
        session.session_id,
        generateConfigModal.extraPrompt || undefined,
        generateConfigModal.referenceImages.length > 0 ? generateConfigModal.referenceImages : undefined
      )
      if (response.success) {
        message.loading('素材图重新生成任务已启动，正在生成中...', 2)
        setGenerateConfigModal({ visible: false, isRegenerate: false, extraPrompt: '', referenceImages: [], loading: false })
        // 立即刷新以获取pending状态，触发轮询
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setIsStartingGenerate(false)
      setGenerateConfigModal(prev => ({ ...prev, loading: false }))
    }
  }

  const handleDelete = async (index: number) => {
    setActionLoading(index)
    try {
      const response = await materialApi.delete(session.session_id, index)
      if (response.success) {
        message.success(response.message)
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

  // 关闭生成配置对话框
  const handleCloseGenerateConfig = () => {
    setGenerateConfigModal({
      visible: false,
      isRegenerate: false,
      extraPrompt: '',
      referenceImages: [],
      loading: false,
    })
  }

  // 上传生成配置参考图
  const handleUploadGenerateReference = async (file: File) => {
    try {
      const result = await uploadApi.uploadImage(file)
      setGenerateConfigModal(prev => ({
        ...prev,
        referenceImages: [...prev.referenceImages, result.file_path],
      }))
      message.success('参考图上传成功')
    } catch (error) {
      message.error('上传失败：' + (error as Error).message)
    }
    return false
  }

  // 删除生成配置参考图
  const handleRemoveGenerateReference = (imagePath: string) => {
    setGenerateConfigModal(prev => ({
      ...prev,
      referenceImages: prev.referenceImages.filter(p => p !== imagePath),
    }))
  }

  // 打开编辑对话框
  const handleOpenEdit = (index: number, material: MaterialImage) => {
    setEditModal({
      visible: true,
      index,
      originalPath: material.image_path,
      description: material.description || '',
      referenceImages: [],  // 不再默认添加当前素材图作为参考图
      prompt: material.prompt || '',  // 初始化为当前提示词
      loading: false,
    })
  }

  // 关闭编辑对话框
  const handleCloseEdit = () => {
    setEditModal({
      visible: false,
      index: -1,
      originalPath: '',
      description: '',
      referenceImages: [],
      prompt: '',
      loading: false,
    })
  }

  // 从参考图列表中移除
  const handleRemoveReference = (imagePath: string) => {
    setEditModal(prev => ({
      ...prev,
      referenceImages: prev.referenceImages.filter(p => p !== imagePath),
    }))
  }

  // 添加原图到参考图列表
  const handleAddOriginal = () => {
    if (editModal.originalPath && !editModal.referenceImages.includes(editModal.originalPath)) {
      setEditModal(prev => ({
        ...prev,
        referenceImages: [...prev.referenceImages, prev.originalPath],
      }))
    }
  }

  // 上传新参考图
  const handleUploadReference = async (file: File) => {
    try {
      const result = await uploadApi.uploadImage(file)
      setEditModal(prev => ({
        ...prev,
        referenceImages: [...prev.referenceImages, result.file_path],
      }))
      message.success('参考图上传成功')
    } catch (error) {
      message.error('上传失败：' + (error as Error).message)
    }
    return false
  }

  // 提交编辑
  const handleSubmitEdit = async () => {
    if (!editModal.prompt.trim()) {
      message.warning('请输入提示词')
      return
    }

    setEditModal(prev => ({ ...prev, loading: true }))

    try {
      const response = await materialApi.edit(
        session.session_id,
        editModal.index,
        editModal.prompt.trim(),
        editModal.description.trim() || undefined,  // 传递素材描述
        editModal.referenceImages.length > 0 ? editModal.referenceImages : undefined,
        editModal.originalPath
      )

      if (response.success) {
        message.success(response.message || '素材图编辑成功')
        handleCloseEdit()
        await refreshSession()
      } else {
        message.error(response.message || '编辑失败')
      }
    } catch (error) {
      message.error('编辑失败：' + (error as Error).message)
    } finally {
      setEditModal(prev => ({ ...prev, loading: false }))
    }
  }

  // 仅保存素材描述（不重新生成图片）
  const handleSaveDescription = async () => {
    if (!editModal.description.trim()) {
      message.warning('请输入素材描述')
      return
    }

    setEditModal(prev => ({ ...prev, loading: true }))

    try {
      const response = await materialApi.updateDescription(
        session.session_id,
        editModal.index,
        editModal.description.trim()
      )

      if (response.success) {
        message.success(response.message || '素材描述已保存')
        handleCloseEdit()
        await refreshSession()
      } else {
        message.error(response.message || '保存失败')
      }
    } catch (error) {
      message.error('保存失败：' + (error as Error).message)
    } finally {
      setEditModal(prev => ({ ...prev, loading: false }))
    }
  }

  // ==================== 新增素材图相关函数 ====================

  // 打开新增素材图对话框
  const handleOpenAddMaterial = () => {
    setAddMaterialModal({
      visible: true,
      prompt: '',
      description: '',
      referenceImages: [],
      loading: false,
    })
  }

  // 关闭新增素材图对话框
  const handleCloseAddMaterial = () => {
    setAddMaterialModal({
      visible: false,
      prompt: '',
      description: '',
      referenceImages: [],
      loading: false,
    })
  }

  // 上传新增素材图的参考图
  const handleUploadAddMaterialReference = async (file: File) => {
    try {
      const result = await uploadApi.uploadImage(file)
      setAddMaterialModal(prev => ({
        ...prev,
        referenceImages: [...prev.referenceImages, result.file_path],
      }))
      message.success('参考图上传成功')
    } catch (error) {
      message.error('上传失败：' + (error as Error).message)
    }
    return false
  }

  // 删除新增素材图的参考图
  const handleRemoveAddMaterialReference = (imagePath: string) => {
    setAddMaterialModal(prev => ({
      ...prev,
      referenceImages: prev.referenceImages.filter(p => p !== imagePath),
    }))
  }

  // 提交新增素材图
  const handleSubmitAddMaterial = async () => {
    if (!addMaterialModal.prompt.trim()) {
      message.warning('请输入生成提示词')
      return
    }

    setAddMaterialModal(prev => ({ ...prev, loading: true }))

    try {
      const response = await materialApi.add(
        session.session_id,
        addMaterialModal.prompt.trim(),
        addMaterialModal.description.trim() || undefined,
        addMaterialModal.referenceImages.length > 0 ? addMaterialModal.referenceImages : undefined
      )

      if (response.success) {
        message.success(response.message || '素材图新增成功')
        handleCloseAddMaterial()
        await refreshSession()
      } else {
        message.error(response.message || '新增失败')
      }
    } catch (error) {
      message.error('新增失败：' + (error as Error).message)
    } finally {
      setAddMaterialModal(prev => ({ ...prev, loading: false }))
    }
  }

  if (!canExecute) {
    return (
      <Card title="生成素材图" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤2：优化脚本</Text>
      </Card>
    )
  }

  // 渲染素材图状态标签
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

  // 根据不同状态渲染主内容
  const renderMainContent = () => {
    // 当后台正在生成素材图时显示加载状态
    if (isBackgroundGenerating) {
      return (
        <Card
          title={
            <span>
              <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
              素材图生成中...
            </span>
          }
          style={{ marginTop: 16 }}
        >
          <div style={{ textAlign: 'center', padding: '40px 0' }}>
            <Spin size="large" />
            <div style={{ marginTop: 16 }}>
              <Text type="secondary">正在生成素材图，请稍候...</Text>
            </div>
            <div style={{ marginTop: 8 }}>
              <Text type="secondary">LLM 将根据脚本内容自动决定生成的素材图数量</Text>
            </div>
          </div>
        </Card>
      )
    }

    // 当有素材图数据时显示（包括生成中和已完成状态）
    if (materials.length > 0) {
      const completedCount = materials.filter(m => m.task_status === 'completed').length
      const failedCount = materials.filter(m => m.task_status === 'failed').length

      const isAllCompleted = completedCount === materials.length
      const title = isAllCompleted ? (
        <span>
          <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
          素材图生成完成 ({completedCount}/{materials.length})
        </span>
      ) : (
        <span>
          <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
          素材图生成中 ({completedCount}/{materials.length})
          {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
        </span>
      )

      return (
        <Card
          title={title}
          extra={
            <Space>
              <Button
                icon={<PlusOutlined />}
                onClick={handleOpenAddMaterial}
                disabled={isGenerating}
              >
                增加素材图
              </Button>
              <Button
                type="primary"
                icon={<ReloadOutlined />}
                onClick={handleRegenerate}
                loading={isGenerating}
                disabled={isGenerating}
              >
                {isGenerating ? '生成中...' : '清除并重新生成素材图'}
              </Button>
            </Space>
          }
          style={{ marginTop: 16 }}
        >
          {isCompleted && completedSubsequentSteps > 0 && (
            <div style={{ marginBottom: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
              <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
              <span style={{ color: '#ad6800' }}>
                后续已完成 {completedSubsequentSteps} 个步骤，重新生成将重置这些步骤
              </span>
            </div>
          )}
          <Row gutter={[16, 16]}>
            {materials.map((material, index) => (
              <Col xs={24} sm={12} md={8} key={index}>
                <Card
                  size="small"
                  cover={
                    material.image_path && material.task_status === 'completed' ? (
                      <Image
                        src={getImageSrc(material.image_path)}
                        alt={material.description || `素材图 ${index + 1}`}
                        style={{ objectFit: 'cover', height: 200 }}
                        fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                      />
                    ) : material.task_status === 'failed' ? (
                      <div
                        style={{
                          height: 200,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          background: '#fff2f0',
                          flexDirection: 'column',
                          gap: 8,
                        }}
                      >
                        <CloseCircleOutlined style={{ fontSize: 32, color: '#ff4d4f' }} />
                        <Text type="danger">生成失败</Text>
                      </div>
                    ) : (
                      <div
                        style={{
                          height: 200,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          background: '#f5f5f5',
                          flexDirection: 'column',
                          gap: 8,
                        }}
                      >
                        <Spin tip="生成中..." />
                        <Text type="secondary">请稍候...</Text>
                      </div>
                    )
                  }
                  actions={[
                    <Tooltip key="edit" title="编辑素材图">
                      <Button
                        type="text"
                        icon={<EditOutlined />}
                        onClick={() => handleOpenEdit(index, material)}
                        disabled={material.task_status !== 'completed'}
                      />
                    </Tooltip>,
                    <Popconfirm
                      key="delete"
                      title="确定删除此素材图？"
                      onConfirm={() => handleDelete(index)}
                      okText="确定"
                      cancelText="取消"
                    >
                      <Button
                        type="text"
                        danger
                        icon={<DeleteOutlined />}
                        loading={actionLoading === index}
                      />
                    </Popconfirm>,
                  ]}
                >
                  <Card.Meta
                    title={
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <span>素材图 {index + 1}</span>
                        {renderStatusTag(material.task_status)}
                      </div>
                    }
                    description={
                      <Tooltip title={material.description || '无描述'}>
                        <div
                          style={{
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            lineHeight: '1.5em',
                            height: '4.5em',
                          }}
                        >
                          {material.description || '无描述'}
                        </div>
                      </Tooltip>
                    }
                  />
                </Card>
              </Col>
            ))}
          </Row>
        </Card>
      )
    }

    // 初始状态：显示生成按钮
    return (
      <Card title="生成素材图" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text>
            将生成"设定稿"风格的素材图（2-5张），包括角色设定图、物品设定图、场景设定图。
          </Text>
        </div>
        <Spin spinning={isGenerating}>
          <Button
            type="primary"
            icon={<PictureOutlined />}
            onClick={handleGenerate}
            loading={isGenerating}
            size="large"
            disabled={isGenerating}
          >
            {isGenerating ? '生成中...' : '开始生成素材图'}
          </Button>
        </Spin>
      </Card>
    )
  }

  // 参考图列表渲染组件
  const renderReferenceImages = (
    images: string[],
    onRemove: (path: string) => void,
    emptyText: string
  ) => (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
      {images.length > 0 ? (
        images.map((imagePath, idx) => (
          <div
            key={idx}
            style={{
              position: 'relative',
              border: '1px solid #d9d9d9',
              borderRadius: 4,
              padding: 4,
            }}
          >
            <Image
              src={getImageSrc(imagePath)}
              alt={`参考图 ${idx + 1}`}
              style={{ width: 80, height: 80, objectFit: 'cover' }}
              preview={false}
            />
            <Button
              type="text"
              danger
              size="small"
              icon={<DeleteOutlined />}
              style={{
                position: 'absolute',
                top: -8,
                right: -8,
                background: '#fff',
                borderRadius: '50%',
                boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
                padding: 0,
                width: 20,
                height: 20,
                minWidth: 20,
              }}
              onClick={() => onRemove(imagePath)}
            />
          </div>
        ))
      ) : (
        <Text type="secondary">{emptyText}</Text>
      )}
    </div>
  )

  // 所有 Modal 统一渲染
  const modals = (
    <>
      {/* 生成配置对话框 */}
      <Modal
        title={generateConfigModal.isRegenerate ? '重新生成素材图配置' : '生成素材图配置'}
        open={generateConfigModal.visible}
        onCancel={handleCloseGenerateConfig}
        footer={[
          <Button key="cancel" onClick={handleCloseGenerateConfig}>
            取消
          </Button>,
          <Button
            key="submit"
            type="primary"
            loading={generateConfigModal.loading}
            onClick={generateConfigModal.isRegenerate ? executeRegenerate : executeGenerate}
            icon={<PictureOutlined />}
          >
            {generateConfigModal.isRegenerate ? '开始重新生成' : '开始生成'}
          </Button>,
        ]}
        width={720}
      >
        <div style={{ marginBottom: 24 }}>
          <Text type="secondary">
            可以上传参考图并添加自定义提示词，增强对素材图生成的控制能力。
          </Text>
        </div>

        {/* 参考图管理 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Text strong>参考图 ({generateConfigModal.referenceImages.length})</Text>
            <Upload
              accept="image/*"
              showUploadList={false}
              beforeUpload={handleUploadGenerateReference}
              multiple
            >
              <Button size="small" icon={<UploadOutlined />}>
                上传参考图
              </Button>
            </Upload>
          </div>
          {renderReferenceImages(
            generateConfigModal.referenceImages,
            handleRemoveGenerateReference,
            '暂无参考图。您可以上传参考图，也可以不使用参考图（纯文生图模式）。'
          )}
        </div>

        {/* 自定义提示词 */}
        <div>
          <Text strong>自定义提示词（可选）</Text>
          <TextArea
            value={generateConfigModal.extraPrompt}
            onChange={(e) => setGenerateConfigModal(prev => ({ ...prev, extraPrompt: e.target.value }))}
            placeholder="添加额外的控制要求，例如：更鲜艳的颜色、卡通风格、写实风格、增加细节..."
            rows={3}
            style={{ marginTop: 8 }}
          />
        </div>
      </Modal>

      {/* 编辑素材图对话框 */}
      <Modal
        title={`编辑素材图 ${editModal.index + 1}`}
        open={editModal.visible}
        onCancel={handleCloseEdit}
        footer={[
          <Button key="cancel" onClick={handleCloseEdit}>
            关闭
          </Button>,
          <Button
            key="regenerate"
            type="primary"
            loading={editModal.loading}
            onClick={handleSubmitEdit}
            icon={<ReloadOutlined />}
            disabled={!editModal.prompt.trim()}
          >
            重新生成图片
          </Button>,
        ]}
        width={720}
      >

        {/* 原素材图预览 */}
        <div style={{ marginBottom: 16 }}>
          <Text strong>原素材图</Text>
          <div style={{ marginTop: 8 }}>
            {editModal.originalPath ? (
              <Image
                src={getImageSrc(editModal.originalPath)}
                alt="原素材图"
                style={{ maxWidth: 150, maxHeight: 150, objectFit: 'contain' }}
              />
            ) : (
              <Text type="secondary">无原素材图</Text>
            )}
          </div>
        </div>

        {/* ===== 第一部分：仅更新素材描述 ===== */}
        <div style={{
          marginBottom: 24,
          padding: 16,
          background: '#f6ffed',
          borderRadius: 8,
          border: '1px solid #b7eb8f'
        }}>
          <div style={{ marginBottom: 12 }}>
            <Text strong style={{ fontSize: 14 }}>更新素材描述</Text>
            <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
              （仅保存描述，不重新生成图片）
            </Text>
          </div>
          <Input
            value={editModal.description}
            onChange={(e) => setEditModal(prev => ({ ...prev, description: e.target.value }))}
            placeholder="描述素材图的内容，例如：主角小明的角色设定图、魔法森林的场景设定..."
          />
          <div style={{ marginTop: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              这是素材的内容描述，用于第五步生成首尾帧时参考
            </Text>
            <Button
              type="primary"
              size="small"
              onClick={handleSaveDescription}
              loading={editModal.loading}
              disabled={!editModal.description.trim()}
            >
              保存描述
            </Button>
          </div>
        </div>

        {/* ===== 分隔线 ===== */}
        <div style={{
          borderTop: '1px dashed #d9d9d9',
          margin: '24px 0',
          position: 'relative',
          textAlign: 'center'
        }}>
          <span style={{
            background: '#fff',
            padding: '0 12px',
            color: '#999',
            fontSize: 12,
            position: 'relative',
            top: -10
          }}>
            如需重新生成图片，请填写以下内容
          </span>
        </div>

        {/* ===== 第二部分：重新生成图片 ===== */}
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ fontSize: 14 }}>重新生成素材图</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            （使用图生图技术重新生成）
          </Text>
        </div>

        {/* 参考图管理 */}
        <div style={{ marginBottom: 16 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Text strong>参考图 ({editModal.referenceImages.length})</Text>
            <Space>
              {editModal.originalPath && !editModal.referenceImages.includes(editModal.originalPath) && (
                <Button size="small" icon={<PlusOutlined />} onClick={handleAddOriginal}>
                  添加原图
                </Button>
              )}
              <Upload
                accept="image/*"
                showUploadList={false}
                beforeUpload={handleUploadReference}
              >
                <Button size="small" icon={<UploadOutlined />}>
                  上传参考图
                </Button>
              </Upload>
            </Space>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {editModal.referenceImages.length > 0 ? (
              editModal.referenceImages.map((imagePath, idx) => (
                <div
                  key={idx}
                  style={{
                    position: 'relative',
                    border: '1px solid #d9d9d9',
                    borderRadius: 4,
                    padding: 4,
                  }}
                >
                  <Image
                    src={getImageSrc(imagePath)}
                    alt={`参考图 ${idx + 1}`}
                    style={{ width: 60, height: 60, objectFit: 'cover' }}
                    preview={false}
                  />
                  <Button
                    type="text"
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    style={{
                      position: 'absolute',
                      top: -8,
                      right: -8,
                      background: '#fff',
                      borderRadius: '50%',
                      boxShadow: '0 1px 4px rgba(0,0,0,0.2)',
                      padding: 0,
                      width: 18,
                      height: 18,
                      minWidth: 18,
                    }}
                    onClick={() => handleRemoveReference(imagePath)}
                  />
                  {imagePath === editModal.originalPath && (
                    <Tag
                      color="blue"
                      style={{
                        position: 'absolute',
                        bottom: 2,
                        left: 2,
                        fontSize: 9,
                        padding: '0 3px',
                      }}
                    >
                      原图
                    </Tag>
                  )}
                </div>
              ))
            ) : (
              <Text type="secondary" style={{ fontSize: 12 }}>
                暂无参考图。无参考图时将使用原素材图作为保底。
              </Text>
            )}
          </div>
        </div>

        {/* 生成提示词 */}
        <div style={{ marginBottom: 16 }}>
          <Text strong>生成提示词 <Text type="danger">*</Text></Text>
          <TextArea
            value={editModal.prompt}
            onChange={(e) => setEditModal(prev => ({ ...prev, prompt: e.target.value }))}
            placeholder="输入生成指令，例如：调整角色的服装颜色为红色、增加更多细节..."
            rows={3}
            style={{ marginTop: 8 }}
          />
        </div>
      </Modal>

      {/* 新增素材图对话框 */}
      <Modal
        title="新增素材图"
        open={addMaterialModal.visible}
        onCancel={handleCloseAddMaterial}
        footer={[
          <Button key="cancel" onClick={handleCloseAddMaterial}>
            取消
          </Button>,
          <Button
            key="submit"
            type="primary"
            loading={addMaterialModal.loading}
            onClick={handleSubmitAddMaterial}
            icon={<PlusOutlined />}
          >
            开始生成
          </Button>,
        ]}
        width={720}
      >
        <div style={{ marginBottom: 24 }}>
          <Text type="secondary">
            输入提示词描述想要生成的素材图，可以上传参考图进行图生图生成（使用 Gemini 3 Pro 模型）。
            如果不上传参考图，将使用纯文生图模式。
          </Text>
        </div>

        {/* 生成提示词 */}
        <div style={{ marginBottom: 24 }}>
          <Text strong>生成提示词 <Text type="danger">*</Text></Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            （用于图生图/文生图的指令）
          </Text>
          <TextArea
            value={addMaterialModal.prompt}
            onChange={(e) => setAddMaterialModal(prev => ({ ...prev, prompt: e.target.value }))}
            placeholder="描述想要生成的素材图，例如：一个穿着蓝色连衣裙的年轻女孩，长发，微笑..."
            rows={3}
            style={{ marginTop: 8 }}
          />
        </div>

        {/* 素材描述（用于后续步骤） */}
        <div style={{ marginBottom: 24 }}>
          <Text strong>素材描述</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            （用于第五步生成首尾帧时参考）
          </Text>
          <Input
            value={addMaterialModal.description}
            onChange={(e) => setAddMaterialModal(prev => ({ ...prev, description: e.target.value }))}
            placeholder="描述素材图的内容，例如：主角小明的角色设定图、魔法森林的场景设定..."
            style={{ marginTop: 8 }}
          />
          <Text type="secondary" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
            注意：这是素材的内容描述，不是生成指令。好的描述能让后续生成的首尾帧更准确。
          </Text>
        </div>

        {/* 参考图管理 */}
        <div style={{ marginBottom: 24 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
            <Text strong>参考图（可选，用于图生图）({addMaterialModal.referenceImages.length})</Text>
            <Upload
              accept="image/*"
              showUploadList={false}
              beforeUpload={handleUploadAddMaterialReference}
              multiple
            >
              <Button size="small" icon={<UploadOutlined />}>
                上传参考图
              </Button>
            </Upload>
          </div>
          {renderReferenceImages(
            addMaterialModal.referenceImages,
            handleRemoveAddMaterialReference,
            '暂无参考图。上传参考图后将使用图生图模式，否则使用纯文生图模式。均使用 Gemini 3 Pro 模型。'
          )}
        </div>
      </Modal>
    </>
  )

  return (
    <>
      {renderMainContent()}
      {modals}
    </>
  )
}
