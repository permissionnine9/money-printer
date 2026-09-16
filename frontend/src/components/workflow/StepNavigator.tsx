/**
 * 步骤导航组件
 */
import React from 'react'
import { Steps } from 'antd'
import type { SessionDetail } from '@/types'
import styles from './StepNavigator.module.css'

const STEPS = [
  { title: '提交脚本', description: '输入原始脚本和参数' },
  { title: '优化脚本', description: 'LLM 优化脚本' },
  { title: '生成素材图', description: '生成角色/场景设定稿' },
  { title: '生成分片', description: '切割分镜头脚本' },
  { title: '生成首尾帧', description: '为每个分片生成首尾帧' },
  { title: '生成视频', description: '生成最终视频片段' },
]

interface StepNavigatorProps {
  session: SessionDetail | null
  currentStep: number
  onStepChange: (step: number) => void
}

export const StepNavigator: React.FC<StepNavigatorProps> = ({
  currentStep,
  onStepChange,
}) => {
  // 使用 currentStep（用户当前浏览的步骤）而不是 session.current_step（会话完成的步骤）
  const current = currentStep

  return (
    <div className={styles.container}>
      <Steps
        current={current}
        onChange={onStepChange}
        items={STEPS}
        className={styles.steps}
      />
    </div>
  )
}
