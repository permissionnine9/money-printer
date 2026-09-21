/**
 * Agent 并发数量配置页面
 * 后台 agent run 的同时执行上限（超出 FIFO 排队）；保存后持久化并立即生效：
 * 扩容立即补 worker，缩容由多余 worker 完成当前任务后退出（执行中的任务不中断）
 */
import React, { useCallback, useEffect, useState } from 'react'
import { Card, Button, InputNumber, Space, Typography, message } from 'antd'
import { SaveOutlined, ReloadOutlined } from '@ant-design/icons'
import { settingsApi } from '@/api/client'

const { Text, Paragraph } = Typography

const AgentConcurrencyPage: React.FC = () => {
  const [maxConcurrent, setMaxConcurrent] = useState<number>(5)
  const [activeWorkers, setActiveWorkers] = useState<number>(0)
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const info = await settingsApi.getAgentConcurrency()
      setMaxConcurrent(info.max_concurrent)
      setActiveWorkers(info.active_workers)
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const handleSave = async () => {
    setSaving(true)
    try {
      await settingsApi.updateAgentConcurrency(maxConcurrent)
      message.success('已保存并立即生效')
      await load()
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Agent 并发数量" loading={loading} style={{ maxWidth: 560 }}>
      <Paragraph type="secondary">
        后台 Agent 任务的同时执行上限，超出部分进入队列排队（FIFO）。调整保存后立即生效：
        调大立即补足 worker；调小不影响执行中的任务，多余 worker 完成当前任务后自动退出。
      </Paragraph>
      <Space size="middle" style={{ marginBottom: 16 }}>
        <InputNumber
          min={1}
          max={20}
          value={maxConcurrent}
          onChange={(v) => setMaxConcurrent(v ?? 5)}
          style={{ width: 120 }}
        />
        <Button type="primary" icon={<SaveOutlined />} loading={saving} onClick={handleSave}>
          保存
        </Button>
        <Button icon={<ReloadOutlined />} onClick={load}>
          刷新
        </Button>
      </Space>
      <div>
        <Text type="secondary">当前存活 worker：{activeWorkers} 个</Text>
      </div>
    </Card>
  )
}

export default AgentConcurrencyPage
