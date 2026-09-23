/**
 * ComfyUI 连接设置弹窗：GPU 容器重启/重建后 SSH 连接命令/密码会变化，
 * 在此粘贴完整 SSH 命令与密码保存（写 hosts.json），后端自动重启 SSH 隧道并探测连通性。
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
  command: string
  remotePort?: number
  password?: string
}

/** 解析 SSH 连接命令（如 `ssh root@xxx.gz15.chenyu.cn -p 20505`）为 user/host/port */
function parseSshCommand(raw: string): { user: string; host: string; port: number } | null {
  let s = raw.trim().replace(/^ssh\s+/i, '')
  const portMatch = s.match(/(?:^|\s)-p\s+(\d+)(?=\s|$)/)
  const port = portMatch ? Number(portMatch[1]) : 22
  s = s.replace(/(?:^|\s)-p\s+\d+(?=\s|$)/, ' ').trim()
  const [target, ...extra] = s.split(/\s+/)
  if (!target || extra.length > 0) return null
  const at = target.lastIndexOf('@')
  const user = at >= 0 ? target.slice(0, at) : 'root'
  const host = at >= 0 ? target.slice(at + 1) : target
  if (!user || !host || port < 1 || port > 65535) return null
  return { user, host, port }
}

const STORAGE_KEY = 'comfyui_connection_form'

/** 读取上次保存的表单缓存；损坏/不存在返回 null */
function readCachedValues(): ConnectionFormValues | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (typeof parsed?.command !== 'string') return null
    return {
      command: parsed.command,
      ...(typeof parsed.remotePort === 'number' ? { remotePort: parsed.remotePort } : {}),
      password: typeof parsed.password === 'string' ? parsed.password : undefined,
    }
  } catch {
    return null
  }
}

/** 缓存表单值：command 总是更新；密码留空时保留旧缓存（避免清掉已存密码） */
function writeCachedValues(values: ConnectionFormValues): void {
  try {
    const prev = readCachedValues()
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        command: values.command.trim(),
        remotePort: values.remotePort ?? prev?.remotePort ?? 8188,
        password: values.password?.trim() || prev?.password || '',
      }),
    )
  } catch {
    // localStorage 不可用（如隐私模式）时静默忽略
  }
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
      if (result.host) {
        form.setFieldsValue({
          command: `ssh ${result.user}@${result.host} -p ${result.port ?? 22}`,
          remotePort: result.remote_port ?? 8188,
        })
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      // 本地缓存（用户最近一次输入）优先于后端回填，且后端不可用时也能填充
      const cached = readCachedValues()
      if (cached) form.setFieldsValue(cached)
      setLoading(false)
    }
  }

  useEffect(() => {
    if (open) loadConnection()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const handleSave = async (values: ConnectionFormValues) => {
    const parsed = parseSshCommand(values.command)
    if (!parsed) {
      message.error('无法解析 SSH 连接命令，请检查格式')
      return
    }
    writeCachedValues(values)
    setSaving(true)
    try {
      const result = await settingsApi.updateComfyUIConnection({
        host: parsed.host,
        port: parsed.port,
        user: parsed.user,
        password: values.password?.trim() || undefined,
        remote_port: values.remotePort || 8188,
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
          name="command"
          label="SSH 连接命令"
          rules={[
            { required: true, message: '请粘贴 SSH 连接命令' },
            {
              validator: (_, value: string) =>
                !value || parseSshCommand(value)
                  ? Promise.resolve()
                  : Promise.reject(new Error('格式无法解析，示例：ssh root@xxx.gz15.chenyu.cn -p 20505')),
            },
          ]}
        >
          <Input placeholder="ssh root@xxx.gz15.chenyu.cn -p 20505" disabled={loading || saving} />
        </Form.Item>
        <Form.Item
          name="remotePort"
          label="ComfyUI 端口（远程）"
          initialValue={8188}
          rules={[{ required: true, message: '请输入远程 ComfyUI 端口' }]}
        >
          <InputNumber min={1} max={65535} style={{ width: '100%' }} disabled={loading || saving} />
        </Form.Item>
        <Form.Item
          name="password"
          label="密码"
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
