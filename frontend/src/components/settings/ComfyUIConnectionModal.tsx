/**
 * ComfyUI 连接设置弹窗：GPU 容器重启/重建后 SSH host/端口/密码会变化，
 * 在此手动录入并保存（写 hosts.json），后端自动重启 SSH 隧道并探测连通性。
 */
import React, { useEffect, useState } from 'react'
import { Modal, Form, Input, InputNumber, Button, Tag, message, Typography } from 'antd'
import { ApiOutlined } from '@ant-design/icons'
import { settingsApi, type ComfyUIConnection } from '@/api/client'

const { Text } = Typography

interface ComfyUIConnectionModalProps {
  open: boolean
  onClose: () => void
}

interface ConnectionFormValues {
  host: string
  port: number
  user: string
  password?: string
}

export const ComfyUIConnectionModal: React.FC<ComfyUIConnectionModalProps> = ({ open, onClose }) => {
  const [form] = Form.useForm<ConnectionFormValues>()
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState<ComfyUIConnection | null>(null)

  const loadConnection = async () => {
    setLoading(true)
    try {
      const result = await settingsApi.getComfyUIConnection()
      setStatus(result)
      form.setFieldsValue({ host: result.host, port: result.port ?? 22, user: result.user })
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) loadConnection()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const handleSave = async (values: ConnectionFormValues) => {
    setSaving(true)
    try {
      const result = await settingsApi.updateComfyUIConnection({
        host: values.host.trim(),
        port: values.port,
        user: values.user.trim() || 'root',
        password: values.password?.trim() || undefined,
      })
      if (result.connected) {
        message.success(result.message)
        setStatus((prev) => (prev ? { ...prev, connected: true } : prev))
        onClose()
      } else {
        message.warning(result.message)
        setStatus((prev) => (prev ? { ...prev, connected: false } : prev))
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title="ComfyUI 服务器连接"
      open={open}
      onCancel={onClose}
      footer={null}
      destroyOnClose
      width={560}
    >
      <div style={{ marginBottom: 16 }}>
        <Text type="secondary">
          GPU 容器每次重启后 SSH 地址/端口/密码都会变化，粘贴新的连接信息保存即可，
          保存后自动重连 SSH 隧道（最长约 35 秒）。
        </Text>
      </div>
      <div style={{ marginBottom: 16 }}>
        <Tag color={status?.connected ? 'green' : 'red'} icon={<ApiOutlined />}>
          {status === null ? '状态未知' : status.connected ? '已连接' : '未连接'}
        </Tag>
        {status?.host && <Text type="secondary" style={{ fontSize: 12 }}>{`${status.host}:${status.port ?? '-'}`}</Text>}
      </div>
      <Form form={form} layout="vertical" onFinish={handleSave}>
        <Form.Item
          name="host"
          label="SSH 主机名"
          rules={[{ required: true, message: '请输入主机名（如 xxx.gz15.chenyu.cn）' }]}
        >
          <Input placeholder="xxx.gz15.chenyu.cn" disabled={loading || saving} />
        </Form.Item>
        <Form.Item
          name="port"
          label="SSH 端口"
          rules={[{ required: true, message: '请输入端口' }]}
          style={{ display: 'inline-block', width: 160 }}
        >
          <InputNumber min={1} max={65535} style={{ width: '100%' }} disabled={loading || saving} />
        </Form.Item>
        <Form.Item
          name="user"
          label="用户名"
          initialValue="root"
          style={{ display: 'inline-block', width: 160, marginLeft: 16 }}
        >
          <Input disabled={loading || saving} />
        </Form.Item>
        <Form.Item
          name="password"
          label="SSH 密码"
          extra={status?.password_set ? '已保存过密码；不修改可留空' : undefined}
        >
          <Input.Password placeholder="粘贴新密码" disabled={loading || saving} />
        </Form.Item>
        <Button type="primary" htmlType="submit" loading={saving} disabled={loading} block>
          {saving ? '正在重连隧道…' : '保存并重连'}
        </Button>
      </Form>
    </Modal>
  )
}
