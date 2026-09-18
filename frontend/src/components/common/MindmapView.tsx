/**
 * markmap 思维导图渲染公共组件（视频大纲 / 剧本大纲共用）
 *
 * 从 Step3Mindmap 抽取：markdown → 导图树渲染、svg 重建逻辑。
 * 上层组件负责编辑模式切换与保存。
 */
import React, { useEffect, useRef } from 'react'
import { Transformer } from 'markmap-lib'
import { Markmap, deriveOptions } from 'markmap-view'

// markmap 转换器（markdown -> 导图树），模块级单例
const transformer = new Transformer()

export interface MindmapViewProps {
  /** markdown 层级文本 */
  markdown: string
  /** 容器高度（px） */
  height?: number
}

export const MindmapView: React.FC<MindmapViewProps> = ({ markdown, height = 520 }) => {
  const svgRef = useRef<SVGSVGElement>(null)
  const markmapRef = useRef<Markmap | null>(null)

  useEffect(() => {
    if (!markdown || !svgRef.current) return

    try {
      const { root } = transformer.transform(markdown)
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
  }, [markdown])

  // 卸载时销毁实例
  useEffect(() => {
    return () => {
      markmapRef.current?.destroy()
      markmapRef.current = null
    }
  }, [])

  return (
    <div style={{ border: '1px solid #f0f0f0', borderRadius: 8, height, position: 'relative' }}>
      <svg ref={svgRef} style={{ width: '100%', height: '100%' }} />
    </div>
  )
}
