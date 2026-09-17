/**
 * 步骤3：生成思维导图（基于优化后的脚本展示剧本结构，支持人工修改）
 */
import React, { useEffect, useRef, useState } from 'react'
import { Card, Button, message, Spin, Typography, Modal, Input, Space, Tag, Segmented, Tooltip } from 'antd'
import {
  ThunderboltOutlined,
  CheckCircleOutlined,
  RedoOutlined,
  ExclamationCircleOutlined,
  EditOutlined,
  SaveOutlined,
  EyeOutlined,
  EditFilled,
} from '@ant-design/icons'
import { Transformer } from 'markmap-lib'
import { Markmap, deriveOptions } from 'markmap-view'
import type { SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography
const { TextArea } = Input

// markmap 转换器（markdown -> 导图树）
const transformer = new Transformer()

interface Step3MindmapProps {
  session: SessionDetail
}

export const Step3Mindmap: React.FC<Step3MindmapProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [promptModalVisible, setPromptModalVisible] = useState(false)
  const [extraPrompt, setExtraPrompt] = useState('')
  const [isRegenerate, setIsRegenerate] = useState(false)
  const [viewMode, setViewMode] = useState<'preview' | 'edit'>('preview')
  const [editingMarkdown, setEditingMarkdown] = useState('')
  const { refreshSession } = useSessionStore()

  // markmap 渲染
  const svgRef = useRef<SVGSVGElement>(null)
  const markmapRef = useRef<Markmap | null>(null)

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('optimize_script')
  const isCompleted = session.completed_steps?.includes('generate_mindmap')
  const stepResult = session.step_results?.generate_mindmap?.result_data
  const mindmap: string = stepResult?.mindmap || ''

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_material_images', 'generate_segment_scripts',
     'generate_segment_frames', 'generate_videos'].includes(step)
  ).length || 0

  // markmap 渲染 effect
  useEffect(() => {
    if (viewMode !== 'preview' || !mindmap || !svgRef.current) return

    try {
      const { root } = transformer.transform(mindmap)
      // 编辑模式会卸载 svg，切回预览时 svgRef 是新元素，旧实例已失效需重建
      if (markmapRef.current && markmapRef.current.svg !== svgRef.current) {
        markmapRef.current.destroy()
        markmapRef.current = null
      }
      if (!markmapRef.current) {
        markmapRef.current = Markmap.create(
          svgRef.current,
          { ...deriveOptions({ colorFreezeLevel: 2 }), maxWidth: 280 },
          root
        )
      } else {
        markmapRef.current.setData(root)
        markmapRef.current.fit()
      }
    } catch (e) {
      console.error('思维导图渲染失败:', e)
    }
  }, [mindmap, viewMode])

  // 打开提示词输入弹窗
  const showPromptModal = (regenerate: boolean) => {
    setIsRegenerate(regenerate)
    setExtraPrompt('')
    setPromptModalVisible(true)
  }

  // 执行生成
  const executeGenerate = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.generateMindmap(session.session_id, prompt || undefined)
      if (response.success) {
        message.success(response.message)
        setViewMode('preview')
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

  // 执行重新生成（清空后续步骤）
  const executeRegenerate = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.regenerateMindmap(session.session_id, prompt || undefined)
      if (response.success) {
        message.success(response.message)
        setViewMode('preview')
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

  // 弹窗确认（重新生成需检查后续步骤）
  const handlePromptModalOk = () => {
    if (isRegenerate) {
      if (completedSubsequentSteps > 0) {
        Modal.confirm({
          title: '确认重新生成思维导图？',
          icon: <ExclamationCircleOutlined />,
          content: (
            <div>
              <p>重新生成将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
              <ul>
                {session.completed_steps?.includes('generate_material_images') && <li>步骤4：生成素材图</li>}
                {session.completed_steps?.includes('generate_segment_scripts') && <li>步骤5：生成分片脚本</li>}
                {session.completed_steps?.includes('generate_segment_frames') && <li>步骤6：生成首尾帧</li>}
                {session.completed_steps?.includes('generate_videos') && <li>步骤7：生成视频</li>}
              </ul>
              <p>此操作不可撤销，是否继续？</p>
            </div>
          ),
          onOk: () => executeRegenerate(extraPrompt),
        })
      } else {
        executeRegenerate(extraPrompt)
      }
    } else {
      executeGenerate(extraPrompt)
    }
  }

  // 进入编辑模式
  const startEdit = () => {
    setEditingMarkdown(mindmap)
    setViewMode('edit')
  }

  // 保存人工修改
  const saveEdit = async () => {
    if (!editingMarkdown.trim()) {
      message.warning('思维导图内容不能为空')
      return
    }
    setSaving(true)
    try {
      const response = await stepApi.updateMindmap(session.session_id, editingMarkdown)
      if (response.success) {
        message.success(response.message)
        setViewMode('preview')
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (!canExecute) {
    return (
      <Card title="生成思维导图" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤2：优化脚本</Text>
      </Card>
    )
  }

  // 提示词输入弹窗
  const promptModal = (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          {isRegenerate ? '重新生成思维导图' : '生成思维导图'} - 自定义提示词
        </span>
      }
      open={promptModalVisible}
      onOk={handlePromptModalOk}
      onCancel={() => setPromptModalVisible(false)}
      okText={isRegenerate ? '开始重新生成' : '开始生成'}
      cancelText="取消"
      width={600}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          输入自定义提示词控制思维导图的结构（可选，留空使用默认策略）。思维导图将展示剧本的故事梗概、角色、场景、道具与情节结构，后续素材图将基于它生成。
        </Text>
      </div>
      <TextArea
        value={extraPrompt}
        onChange={(e) => setExtraPrompt(e.target.value)}
        placeholder="例如：&#10;- 突出角色之间的关系&#10;- 按三幕式划分情节结构&#10;- 每个场景包含光线与氛围描述"
        rows={6}
      />
    </Modal>
  )

  if (isCompleted && mindmap) {
    return (
      <>
        <Card
          title={
            <span>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
              剧本思维导图
              {stepResult?.edited && (
                <Tooltip title="已人工修改">
                  <Tag color="blue" style={{ marginLeft: 12 }}>已人工修改</Tag>
                </Tooltip>
              )}
            </span>
          }
          style={{ marginTop: 16 }}
          extra={
            <Space>
              <Segmented
                value={viewMode}
                onChange={(v) => {
                  const mode = v as 'preview' | 'edit'
                  if (mode === 'edit') startEdit()
                  setViewMode(mode)
                }}
                options={[
                  { value: 'preview', icon: <EyeOutlined />, label: '导图预览' },
                  { value: 'edit', icon: <EditFilled />, label: '编辑' },
                ]}
              />
              <Button
                type="primary"
                icon={<RedoOutlined />}
                onClick={() => showPromptModal(true)}
                loading={loading}
              >
                重新生成
              </Button>
            </Space>
          }
        >
          {viewMode === 'preview' ? (
            <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, height: 520, position: 'relative' }}>
              <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
            </div>
          ) : (
            <div>
              <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <Text type="secondary">
                  直接编辑 markdown 层级文本（# 标题层级 / - 列表项），保存后导图与后续素材图生成都将使用新内容
                </Text>
                <Space>
                  <Button onClick={() => setViewMode('preview')}>取消</Button>
                  <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={saveEdit}>
                    保存修改
                  </Button>
                </Space>
              </div>
              <TextArea
                value={editingMarkdown}
                onChange={(e) => setEditingMarkdown(e.target.value)}
                rows={20}
                style={{ fontFamily: 'monospace' }}
              />
            </div>
          )}
          {completedSubsequentSteps > 0 && (
            <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
              <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
              <span style={{ color: '#ad6800' }}>
                后续已完成 {completedSubsequentSteps} 个步骤，重新生成将重置这些步骤；仅保存修改不会重置
              </span>
            </div>
          )}
        </Card>
        {promptModal}
      </>
    )
  }

  return (
    <>
      <Card title="生成思维导图" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text>
            LLM 将基于优化后的脚本生成剧本结构思维导图（故事梗概 / 角色设定 / 场景设定 / 道具设定 / 情节结构），
            可在生成后人工修改；后续素材图将基于思维导图生成。
          </Text>
        </div>
        <Spin spinning={loading}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={() => showPromptModal(false)}
            loading={loading}
            size="large"
          >
            开始生成思维导图
          </Button>
        </Spin>
      </Card>
      {promptModal}
    </>
  )
}

export default Step3Mindmap
