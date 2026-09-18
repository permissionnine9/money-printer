/**
 * 分片镜头 skill 提示词管理页面
 * 提示词以 markdown 文件保存在 backend/prompts/ 目录，网页编辑后直接覆盖保存（无版本管理）
 */
import React, { useEffect, useMemo, useState } from 'react'
import {
  Card,
  Button,
  Input,
  Space,
  message,
  Typography,
  Spin,
  Empty,
  Tag,
} from 'antd'
import { SaveOutlined, ReloadOutlined, FileTextOutlined, CaretRightOutlined } from '@ant-design/icons'
import type { PromptTemplate } from '@/types'
import { promptApi } from '@/api/client'

const { Text } = Typography
const { TextArea } = Input

// 模板分类：按顺序分组展示，未识别的 category 归「其他」
const CATEGORY_ORDER = ['script', 'video', 'other']
const CATEGORY_META: Record<string, { label: string }> = {
  script: { label: '剧本创作' },
  video: { label: '视频生成' },
  other: { label: '其他' },
}

const PromptsPage: React.FC = () => {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [selected, setSelected] = useState<PromptTemplate | null>(null)
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})

  // 按分类分组，组内按 step 升序（缺省排最后，其余保持原有顺序）
  const groups = useMemo(() => {
    const map = new Map<string, PromptTemplate[]>()
    for (const p of prompts) {
      const key = p.category && CATEGORY_META[p.category] ? p.category : 'other'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(p)
    }
    return CATEGORY_ORDER.filter((key) => map.has(key)).map((key) => ({
      key,
      ...CATEGORY_META[key],
      items: map.get(key)!.sort((a, b) => (a.step ?? Infinity) - (b.step ?? Infinity)),
    }))
  }, [prompts])

  const loadPrompts = async (selectName?: string) => {
    setLoading(true)
    try {
      const result = await promptApi.list()
      const list = result.prompts || []
      setPrompts(list)
      // 默认选中第一个（按分组展示顺序，或指定项）
      const first = [...list].sort((a, b) => (a.step ?? Infinity) - (b.step ?? Infinity))[0]
      const target = selectName ? list.find((p) => p.name === selectName) : first
      if (target) {
        await selectPrompt(target)
      } else {
        setSelected(null)
        setContent('')
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const selectPrompt = async (prompt: PromptTemplate) => {
    setSelected(prompt)
    setDirty(false)
    try {
      const result = await promptApi.get(prompt.name)
      setContent(result.prompt?.content || '')
    } catch (error) {
      message.error((error as Error).message)
      setContent('')
    }
  }

  useEffect(() => {
    loadPrompts()
  }, [])

  const handleSave = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const response = await promptApi.save(selected.name, content)
      if (response.success) {
        message.success(response.message + '（backend/prompts/' + selected.name + '.md）')
        setDirty(false)
        await loadPrompts(selected.name)
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      <Card
        title="分片镜头 Skill 提示词管理"
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => loadPrompts(selected?.name)}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<SaveOutlined />}
              onClick={handleSave}
              loading={saving}
              disabled={!selected || !dirty}
            >
              保存
            </Button>
          </Space>
        }
      >
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            提示词模板以 markdown 文件保存在后端 <Text code>backend/prompts/</Text> 目录，保存后立即生效（无版本管理）。
            模板中的 <Text code>{'{{变量}}'}</Text> 为占位符，运行时自动替换。
          </Text>
        </div>

        <Spin spinning={loading}>
          {prompts.length === 0 && !loading ? (
            <Empty description="暂无提示词模板" />
          ) : (
            <div style={{ display: 'flex', gap: 16, minHeight: 560 }}>
              {/* 左侧模板列表（按分类分组，可折叠） */}
              <div style={{ width: 280, flexShrink: 0 }}>
                <Text strong style={{ display: 'block', marginBottom: 8 }}>模板列表</Text>
                {groups.map((g) => {
                  const isCollapsed = collapsed[g.key]
                  return (
                    <div key={g.key} style={{ marginBottom: 4 }}>
                      <div
                        style={{
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '6px 8px',
                          borderRadius: 6,
                          userSelect: 'none',
                        }}
                        onClick={() => setCollapsed((prev) => ({ ...prev, [g.key]: !prev[g.key] }))}
                      >
                        <CaretRightOutlined
                          style={{ fontSize: 12, color: '#8c8c8c', transition: 'transform 0.2s' }}
                          rotate={isCollapsed ? 0 : 90}
                        />
                        <Text strong style={{ fontSize: 13 }}>{g.label}</Text>
                        <Text type="secondary" style={{ fontSize: 12 }}>{g.items.length}</Text>
                      </div>
                      {!isCollapsed && g.items.map((p) => (
                        <div
                          key={p.name}
                          style={{
                            cursor: 'pointer',
                            padding: '10px 12px',
                            paddingLeft: 26,
                            background: selected?.name === p.name ? '#e6f4ff' : undefined,
                            borderRadius: 6,
                            display: 'flex',
                            gap: 10,
                            alignItems: 'flex-start',
                          }}
                          onClick={() => selectPrompt(p)}
                        >
                          <FileTextOutlined style={{ fontSize: 18, color: '#1677ff', marginTop: 2 }} />
                          <div style={{ minWidth: 0 }}>
                            <div>{p.name}</div>
                            <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
                              {p.description || '暂无描述'}
                            </Text>
                          </div>
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>

              {/* 右侧编辑器 */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {selected ? (
                  <>
                    <div style={{ marginBottom: 8, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Space>
                        <Text strong>{selected.name}.md</Text>
                        {dirty && <Tag color="orange">未保存</Tag>}
                      </Space>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        {content.length} 字符
                      </Text>
                    </div>
                    <TextArea
                      value={content}
                      onChange={(e) => {
                        setContent(e.target.value)
                        setDirty(true)
                      }}
                      rows={24}
                      style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}
                    />
                  </>
                ) : (
                  <Empty description="选择左侧模板进行编辑" style={{ marginTop: 120 }} />
                )}
              </div>
            </div>
          )}
        </Spin>
      </Card>
    </div>
  )
}

export default PromptsPage
