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
    const svg = svgRef.current
    if (!markdown || !svg) return

    const render = async () => {
      try {
        const { root } = transformer.transform(markdown)
        // 编辑模式会卸载 svg，切回预览时 svgRef 是新元素，旧实例已失效需重建
        if (markmapRef.current && markmapRef.current.svg !== svg) {
          markmapRef.current.destroy()
          markmapRef.current = null
        }
        // create 不传 root：避免其内部 setData().then(fit) 在组件卸载后仍执行 fit
        // （svg 脱离 DOM 时 getBoundingClientRect 为 0，与未布局的 state.rect 相除得 NaN transform）
        if (!markmapRef.current) {
          markmapRef.current = Markmap.create(
            svg,
            { ...deriveOptions({ colorFreezeLevel: 2 }), maxWidth: 280 }
          )
        }
        // 布局是异步的（setData 内部 await renderData），必须等完成再 fit，否则 fit 到旧布局
        await markmapRef.current.setData(root)
        const rect = svg.getBoundingClientRect()
        if (svg.isConnected && rect.width > 0 && rect.height > 0) {
          markmapRef.current.fit()
        }
      } catch (e) {
        console.error('思维导图渲染失败:', e)
      }
    }

    // 步骤切换用 display:none 隐藏非激活步骤，隐藏时 svg 尺寸为 0，
    // markmap fit() 会算出 NaN transform；等尺寸就绪（步骤被切换进来）再渲染
    if (svg.clientWidth > 0 && svg.clientHeight > 0) {
      render()
      return
    }
    const ro = new ResizeObserver((entries) => {
      if (entries.some((e) => e.contentRect.width > 0 && e.contentRect.height > 0)) {
        ro.disconnect()
        render()
      }
    })
    ro.observe(svg)
    return () => ro.disconnect()
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
