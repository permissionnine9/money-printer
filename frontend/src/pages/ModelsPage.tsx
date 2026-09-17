/**
 * 模型管理页面：添加多个生图模型与 chat 模型（key/baseUrl/modelId 关联）
 */
import React, { useEffect, useState } from 'react'
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Switch,
  Space,
  Tag,
  message,
  Popconfirm,
  Typography,
  Segmented,
} from 'antd'
import {
  PlusOutlined,
  EditOutlined,
  DeleteOutlined,
  StarOutlined,
  StarFilled,
  ReloadOutlined,
} from '@ant-design/icons'
import type { ImageModelConfig } from '@/types'
import { modelApi } from '@/api/client'

const { Text } = Typography

interface ModalState {
  visible: boolean
  editing: ImageModelConfig | null
  loading: boolean
}

const ModelsPage: React.FC = () => {
  const [models, setModels] = useState<ImageModelConfig[]>([])
  const [loading, setLoading] = useState(false)
  const [filterType, setFilterType] = useState<'all' | 'image' | 'chat'>('all')
  const [modal, setModal] = useState<ModalState>({ visible: false, editing: null, loading: false })
  const [form] = Form.useForm()

  const loadModels = async () => {
    setLoading(true)
    try {
      const result = await modelApi.list(filterType === 'all' ? undefined : filterType)
      setModels(result.models || [])
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadModels()
  }, [])

  const openCreate = () => {
    form.resetFields()
    form.setFieldsValue({ model_type: filterType === 'chat' ? 'chat' : 'image', is_default: false })
    setModal({ visible: true, editing: null, loading: false })
  }

  const openEdit = (model: ImageModelConfig) => {
    form.setFieldsValue({
      name: model.name,
      api_key: model.api_key,
      base_url: model.base_url,
      model_id: model.model_id,
      is_default: model.is_default,
      model_type: model.model_type || 'image',
    })
    setModal({ visible: true, editing: model, loading: false })
  }

  const handleSave = async () => {
    try {
      const values = await form.validateFields()
      setModal((prev) => ({ ...prev, loading: true }))
      const payload = {
        name: values.name,
        api_key: values.api_key || '',
        base_url: values.base_url || '',
        model_id: values.model_id || '',
        is_default: values.is_default || false,
        model_type: values.model_type || 'image',
      }
      const response = modal.editing
        ? await modelApi.update(modal.editing.id, payload)
        : await modelApi.create(payload)

      if (response.success) {
        message.success(response.message)
        setModal({ visible: false, editing: null, loading: false })
        await loadModels()
      } else {
        message.error(response.message)
        setModal((prev) => ({ ...prev, loading: false }))
      }
    } catch (error) {
      if ((error as any)?.errorFields) return // 表单校验错误
      message.error((error as Error).message)
      setModal((prev) => ({ ...prev, loading: false }))
    }
  }

  const handleSetDefault = async (model: ImageModelConfig) => {
    try {
      const response = await modelApi.setDefault(model.id)
      if (response.success) {
        message.success(response.message)
        await loadModels()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const handleDelete = async (model: ImageModelConfig) => {
    try {
      const response = await modelApi.remove(model.id)
      if (response.success) {
        message.success(response.message)
        await loadModels()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    }
  }

  const columns = [
    {
      title: '名称',
      dataIndex: 'name',
      key: 'name',
      render: (name: string, record: ImageModelConfig) => (
        <Space>
          <span>{name}</span>
          <Tag color={record.model_type === 'chat' ? 'geekblue' : 'cyan'}>
            {record.model_type === 'chat' ? 'Chat' : '生图'}
          </Tag>
          {record.is_default && <Tag color="green">默认</Tag>}
        </Space>
      ),
    },
    {
      title: 'Base URL',
      dataIndex: 'base_url',
      key: 'base_url',
      render: (url: string) => (
        <Text copyable={!!url} style={{ fontSize: 12 }}>{url || <Text type="secondary">（使用系统默认）</Text>}</Text>
      ),
    },
    {
      title: '模型ID',
      dataIndex: 'model_id',
      key: 'model_id',
      render: (id: string) => (
        <Text copyable={!!id} style={{ fontSize: 12 }}>{id || <Text type="secondary">（未指定）</Text>}</Text>
      ),
    },
    {
      title: 'API Key',
      dataIndex: 'api_key',
      key: 'api_key',
      render: (key: string) => (
        <Text style={{ fontSize: 12 }}>
          {key ? `${key.slice(0, 6)}****${key.slice(-4)}` : <Text type="secondary">（使用系统默认）</Text>}
        </Text>
      ),
    },
    {
      title: '操作',
      key: 'actions',
      render: (_: unknown, record: ImageModelConfig) => (
        <Space>
          {!record.is_default && (
            <Button
              size="small"
              icon={<StarOutlined />}
              onClick={() => handleSetDefault(record)}
            >
              设为默认
            </Button>
          )}
          <Button size="small" icon={<EditOutlined />} onClick={() => openEdit(record)}>
            编辑
          </Button>
          <Popconfirm title="确定删除此模型配置？" onConfirm={() => handleDelete(record)} okText="删除" cancelText="取消">
            <Button size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto' }}>
      <Card
        title="模型管理（生图 / Chat）"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={loadModels} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} onClick={openCreate}>
              添加模型
            </Button>
          </Space>
        }
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            管理多个模型配置（API Key / Base URL / 模型ID），支持「生图模型」与「Chat 模型」两类，各自独立默认。
            默认生图模型用于素材图与首尾帧生成；默认 Chat 模型用于脚本优化、思维导图、分片等 LLM 环节。
          </Text>
        </div>
        <div style={{ marginBottom: 16 }}>
          <Segmented
            value={filterType}
            onChange={(v) => {
              const t = v as 'all' | 'image' | 'chat'
              setFilterType(t)
              setTimeout(() => {
                modelApi.list(t === 'all' ? undefined : t)
                  .then((r) => setModels(r.models || []))
                  .catch(() => {})
              }, 0)
            }}
            options={[
              { value: 'all', label: '全部' },
              { value: 'image', label: '生图模型' },
              { value: 'chat', label: 'Chat 模型' },
            ]}
          />
        </div>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={models}
          loading={loading}
          pagination={false}
          locale={{ emptyText: '暂无模型配置，点击右上角「添加模型」创建' }}
        />
      </Card>

      <Modal
        title={modal.editing ? `编辑模型：${modal.editing.name}` : '添加模型'}
        open={modal.visible}
        onCancel={() => setModal({ visible: false, editing: null, loading: false })}
        footer={[
          <Button key="cancel" onClick={() => setModal({ visible: false, editing: null, loading: false })}>
            取消
          </Button>,
          <Button key="save" type="primary" loading={modal.loading} onClick={handleSave}>
            {modal.editing ? '保存修改' : '创建'}
          </Button>,
        ]}
      >
        <Form form={form} layout="vertical" initialValues={{ is_default: false, model_type: 'image' }}>
          <Form.Item name="model_type" label="模型类型">
            <Segmented
              options={[
                { value: 'image', label: '生图模型' },
                { value: 'chat', label: 'Chat 模型' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="name"
            label="模型名称"
            rules={[{ required: true, message: '请输入模型名称' }]}
          >
            <Input placeholder="例如：盛算云 Gemini、公司内部生图服务" />
          </Form.Item>
          <Form.Item
            name="api_key"
            label="API Key"
            extra="留空则使用系统默认 Key"
          >
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item
            name="base_url"
            label="Base URL"
            extra="OpenAI 兼容格式的 API 地址，留空则使用系统默认地址"
          >
            <Input placeholder="https://router.shengsuanyun.com/api/v1" />
          </Form.Item>
          <Form.Item
            name="model_id"
            label="模型 ID"
            extra="生图如 google/gemini-3-pro-image-preview；Chat 如 bytedance/doubao-seed-1.8"
          >
            <Input placeholder="google/gemini-3-pro-image-preview" />
          </Form.Item>
          <Form.Item
            name="is_default"
            label="设为该类型默认模型"
            valuePropName="checked"
            extra="默认生图模型用于素材图/首尾帧生成；默认 Chat 模型用于脚本优化、思维导图、分片等 LLM 环节"
          >
            <Switch checkedChildren={<StarFilled />} unCheckedChildren={<StarOutlined />} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}

export default ModelsPage
