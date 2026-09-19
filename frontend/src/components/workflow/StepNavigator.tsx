/**
 * 步骤导航组件
 */
import React from 'react'
import { Steps } from 'antd'
import type { SessionDetail } from '@/types'
import styles from './StepNavigator.module.css'

// 视频工作流 4 步（与 STEP_NAMES 一致）
const STEPS = [
  { title: '从剧本选集', content: '选择剧本分集与视频参数' },
  { title: '分镜大纲', content: '生成本集分镜导图与分镜列表' },
  { title: '分镜管理', content: '分镜形式配置与提示词生成' },
  { title: '视频', content: '远程 ComfyUI 生成最终视频' },
]

interface StepNavigatorProps {
  session: SessionDetail | null
  currentStep: number
  onStepChange: (step: number) => void
}

export const StepNavigator: React.FC<StepNavigatorProps> = ({
  session,
  currentStep,
  onStepChange,
}) => {
  // 使用 currentStep（用户当前浏览的步骤）而不是 session.current_step（会话完成的步骤）
  const current = currentStep

  // 第 3 步进度：已完成配置的分镜数 / 总数（如「分镜管理 5/10」）
  const segments = session?.step_results?.storyboard_outline?.result_data?.segments || []
  const items = STEPS.map((step, i) =>
    i === 2 && segments.length > 0
      ? { ...step, title: `${step.title} ${segments.filter((s: any) => s.configured).length}/${segments.length}` }
      : step
  )

  return (
    <div className={styles.container}>
      <Steps
        current={current}
        onChange={onStepChange}
        items={items}
        className={styles.steps}
      />
    </div>
  )
}
