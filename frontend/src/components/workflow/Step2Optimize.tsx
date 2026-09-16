/**
 * 步骤2：优化脚本
 */
import React, { useState } from 'react'
import { Card, Button, message, Spin, Typography, Modal, Input } from 'antd'
import { ThunderboltOutlined, CheckCircleOutlined, RedoOutlined, ExclamationCircleOutlined, EditOutlined } from '@ant-design/icons'
import type { SessionDetail } from '@/types'
import { stepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography
const { TextArea } = Input

interface Step2OptimizeProps {
  session: SessionDetail
}

export const Step2Optimize: React.FC<Step2OptimizeProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [promptModalVisible, setPromptModalVisible] = useState(false)
  const [extraPrompt, setExtraPrompt] = useState('')
  const [isReoptimize, setIsReoptimize] = useState(false)
  const { refreshSession } = useSessionStore()

  // 获取步骤1的结果以显示分片时长
  const step1Result = session.step_results?.submit_script_and_params?.result_data
  const maxSegmentDuration = step1Result?.video_params?.max_segment_duration || 8

  // 检查前置步骤是否完成
  const canExecute = session.completed_steps?.includes('submit_script_and_params')
  const isCompleted = session.completed_steps?.includes('optimize_script')
  const stepResult = session.step_results?.optimize_script?.result_data

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps = session.completed_steps?.filter(step =>
    ['generate_material_images', 'generate_segment_scripts',
     'generate_segment_frames', 'generate_videos'].includes(step)
  ).length || 0

  // 打开提示词输入弹窗
  const showPromptModal = (reoptimize: boolean) => {
    setIsReoptimize(reoptimize)
    setExtraPrompt('')
    setPromptModalVisible(true)
  }

  // 执行优化（带可选的自定义提示词）
  const executeOptimize = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.optimizeScript(session.session_id, prompt || undefined)
      if (response.success) {
        message.success(response.message)
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

  // 执行重新优化（带可选的自定义提示词）
  const executeReoptimize = async (prompt?: string) => {
    setLoading(true)
    setPromptModalVisible(false)
    try {
      const response = await stepApi.reoptimizeScript(session.session_id, prompt || undefined)
      if (response.success) {
        message.success(response.message)
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

  // 处理弹窗确认
  const handlePromptModalOk = () => {
    if (isReoptimize) {
      // 如果是重新优化，需要检查后续步骤
      if (completedSubsequentSteps > 0) {
        Modal.confirm({
          title: '确认重新优化？',
          icon: <ExclamationCircleOutlined />,
          content: (
            <div>
              <p>重新优化将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
              <ul>
                {session.completed_steps?.includes('generate_material_images') && <li>步骤3：生成素材图</li>}
                {session.completed_steps?.includes('generate_segment_scripts') && <li>步骤4：生成分片脚本</li>}
                {session.completed_steps?.includes('generate_segment_frames') && <li>步骤5：生成首尾帧</li>}
                {session.completed_steps?.includes('generate_videos') && <li>步骤6：生成视频</li>}
              </ul>
              <p>此操作不可撤销，是否继续？</p>
            </div>
          ),
          onOk: () => executeReoptimize(extraPrompt),
        })
      } else {
        executeReoptimize(extraPrompt)
      }
    } else {
      executeOptimize(extraPrompt)
    }
  }

  const handleOptimize = () => {
    showPromptModal(false)
  }

  const handleReoptimize = () => {
    showPromptModal(true)
  }

  if (!canExecute) {
    return (
      <Card title="优化脚本" style={{ marginTop: 16 }}>
        <Text type="secondary">请先完成步骤1：提交脚本</Text>
      </Card>
    )
  }

  // 提示词输入弹窗
  const promptModal = (
    <Modal
      title={
        <span>
          <EditOutlined style={{ marginRight: 8 }} />
          {isReoptimize ? '重新优化脚本' : '优化脚本'} - 自定义提示词
        </span>
      }
      open={promptModalVisible}
      onOk={handlePromptModalOk}
      onCancel={() => setPromptModalVisible(false)}
      okText={isReoptimize ? '开始重新优化' : '开始优化'}
      cancelText="取消"
      width={600}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          输入自定义提示词来控制脚本优化的方向和风格（可选，留空则使用默认优化策略）
        </Text>
      </div>
      <TextArea
        value={extraPrompt}
        onChange={(e) => setExtraPrompt(e.target.value)}
        placeholder="例如：&#10;- 增加更多动作细节和视觉描述&#10;- 使用更电影化的叙事风格&#10;- 强调角色的情感表达&#10;- 增加环境氛围的渲染"
        rows={6}
        style={{ marginBottom: 16 }}
      />
      <div style={{ padding: 12, background: '#f5f5f5', borderRadius: 4 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          提示：自定义提示词将影响 LLM 对脚本的优化方向。您可以指定希望强调的内容、风格偏好、特殊要求等。
        </Text>
      </div>
    </Modal>
  )

  if (isCompleted && stepResult) {
    return (
      <>
        <Card
          title={
            <span>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
              脚本优化完成
            </span>
          }
          style={{ marginTop: 16 }}
          extra={
            <Button
              type="primary"
              icon={<RedoOutlined />}
              onClick={handleReoptimize}
              loading={loading}
            >
              重新优化
            </Button>
          }
        >
          <div style={{ marginBottom: 16 }}>
            <strong>优化后的脚本：</strong>
            <div
              style={{
                background: '#f6ffed',
                border: '1px solid #b7eb8f',
                padding: 12,
                borderRadius: 4,
                whiteSpace: 'pre-wrap',
                maxHeight: 400,
                overflow: 'auto',
                marginTop: 8,
              }}
            >
              {stepResult.optimized_script}
            </div>
          </div>
          {completedSubsequentSteps > 0 && (
            <div style={{ padding: 12, background: '#fff7e6', borderRadius: 4 }}>
              <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
              <span style={{ color: '#ad6800' }}>
                后续已完成 {completedSubsequentSteps} 个步骤，重新优化将重置这些步骤
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
      <Card title="优化脚本" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text>LLM 将优化您的脚本，丰富细节，设计{maxSegmentDuration}秒以内的转场分片。</Text>
        </div>
        <Spin spinning={loading}>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={handleOptimize}
            loading={loading}
            size="large"
          >
            开始优化脚本
          </Button>
        </Spin>
      </Card>
      {promptModal}
    </>
  )
}
