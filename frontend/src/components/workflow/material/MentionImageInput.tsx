/**
 * @ 图片引用输入：TextArea 中输入 @ 触发素材候选下拉，选中后插入 @名称 文本
 * 并记录到 mentions（chips 列表为真相源，文本中的 @名称 仅为装饰，不做反向解析）。
 */
import React, { useMemo, useRef, useState } from 'react'
import { Empty, Image, Input, Tag } from 'antd'
import { PictureOutlined } from '@ant-design/icons'
import type { PoolMaterial } from '@/types'
import { imageSrc } from '@/utils/imageSrc'

const { TextArea } = Input

export interface MentionImageInputProps {
  value: string
  onChange: (v: string) => void
  /** 已 @ 引用的素材（真相源，提交时以该数组为准） */
  mentions: PoolMaterial[]
  onMentionsChange: (m: PoolMaterial[]) => void
  /** 候选素材池 */
  pool: PoolMaterial[]
  placeholder?: string
  rows?: number
}

export const MentionImageInput: React.FC<MentionImageInputProps> = ({
  value,
  onChange,
  mentions,
  onMentionsChange,
  pool,
  placeholder,
  rows = 3,
}) => {
  const [mentionOpen, setMentionOpen] = useState(false)
  const [mentionQuery, setMentionQuery] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)

  const candidates = useMemo(() => {
    const q = mentionQuery.trim().toLowerCase()
    return pool.filter((m) => {
      if (mentions.some((x) => x.image_id === m.image_id)) return false
      if (!q) return true
      const label = m.title || m.description || m.image_id
      return label.toLowerCase().includes(q)
    })
  }, [pool, mentionQuery, mentions])

  // 检测光标前是否正在输入 @ 触发词（@ 或 @xx）
  const handleDetectMention = (text: string, selectionStart: number) => {
    const before = text.slice(0, selectionStart)
    const match = before.match(/(^|\s)@([^\s@]*)$/)
    if (match) {
      setMentionQuery(match[2])
      setMentionOpen(true)
    } else {
      setMentionOpen(false)
    }
  }

  const insertMention = (m: PoolMaterial) => {
    const label = m.title || m.description || m.image_id
    const el = textareaRef.current
    let next = value
    let caret = 0
    if (el) {
      const { selectionStart = 0, selectionEnd = 0 } = el
      const before = value.slice(0, selectionStart)
      const after = value.slice(selectionEnd)
      const match = before.match(/@([^\s@]*)$/)
      if (match) {
        // 替换光标前的 @触发词 为完整 @名称
        next = before.slice(0, before.length - match[0].length) + `@${label} ` + after
        caret = before.length - match[0].length + label.length + 2
      } else {
        // 光标不在触发词处（如已失焦）：末尾追加
        next = value + (value && !value.endsWith(' ') ? ' ' : '') + `@${label} `
        caret = next.length
      }
    } else {
      next = value + (value && !value.endsWith(' ') ? ' ' : '') + `@${label} `
      caret = next.length
    }
    onChange(next)
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(caret, caret)
    })
    onMentionsChange([...mentions, m])
    setMentionOpen(false)
    setMentionQuery('')
  }

  const removeMention = (m: PoolMaterial) => {
    onMentionsChange(mentions.filter((x) => x.image_id !== m.image_id))
  }

  return (
    <div>
      <div style={{ position: 'relative' }}>
        <TextArea
          ref={textareaRef as never}
          value={value}
          rows={rows}
          placeholder={placeholder || '描述想生成的素材图，输入 @ 可引用素材池图片作为参考'}
          onChange={(e) => {
            onChange(e.target.value)
            handleDetectMention(e.target.value, e.target.selectionStart)
          }}
          onBlur={() => {
            // 延迟关闭，避免点击候选项时先失焦
            setTimeout(() => setMentionOpen(false), 150)
          }}
        />
        {mentionOpen && (
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: 0,
              right: 0,
              zIndex: 10,
              marginTop: 4,
              maxHeight: 220,
              overflowY: 'auto',
              background: '#fff',
              border: '1px solid #d9d9d9',
              borderRadius: 6,
              boxShadow: '0 4px 12px rgba(0,0,0,0.12)',
            }}
          >
            {candidates.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={pool.length === 0 ? '素材池为空' : '无匹配素材'}
                style={{ padding: '8px 0' }}
              />
            ) : (
              candidates.map((m) => (
                <div
                  key={m.image_id}
                  onClick={() => insertMention(m)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 10px',
                    cursor: 'pointer',
                  }}
                  onMouseEnter={(e) => (e.currentTarget.style.background = '#f5f5f5')}
                  onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                  <Image
                    src={imageSrc(m.image_path)}
                    alt={m.title || m.description}
                    width={32}
                    height={32}
                    style={{ objectFit: 'cover', borderRadius: 4 }}
                    preview={false}
                    fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                  />
                  <span style={{ fontSize: 13 }}>
                    {m.title || <PictureOutlined />} {m.title ? '' : (m.description || m.image_id)}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>
      {mentions.length > 0 && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
          {mentions.map((m) => (
            <Tag
              key={m.image_id}
              closable
              onClose={(e) => {
                e.preventDefault()
                removeMention(m)
              }}
              icon={<PictureOutlined />}
              color="blue"
              style={{ maxWidth: '100%' }}
            >
              {m.title || m.description || m.image_id}
            </Tag>
          ))}
        </div>
      )}
    </div>
  )
}

export default MentionImageInput
