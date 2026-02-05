/**
 * 懒加载 Hook
 * 使用 IntersectionObserver 实现视口检测
 */
import { useRef, useState, useEffect, useCallback } from 'react'

interface UseLazyLoadOptions {
  /** 触发加载的阈值，0-1 之间，表示目标元素进入视口的比例 */
  threshold?: number
  /** 根元素的边距，用于提前触发加载 */
  rootMargin?: string
  /** 是否只触发一次（加载后停止观察） */
  triggerOnce?: boolean
}

interface UseLazyLoadReturn {
  /** ref 回调，绑定到需要懒加载的元素 */
  ref: (node: HTMLElement | null) => void
  /** 元素是否进入可视区域 */
  isInView: boolean
  /** 元素是否曾经进入过可视区域 */
  hasBeenInView: boolean
}

/**
 * 懒加载 Hook
 * @param options 配置选项
 * @returns { ref, isInView, hasBeenInView }
 */
export function useLazyLoad(options: UseLazyLoadOptions = {}): UseLazyLoadReturn {
  const { threshold = 0, rootMargin = '100px', triggerOnce = true } = options

  const [isInView, setIsInView] = useState(false)
  const [hasBeenInView, setHasBeenInView] = useState(false)
  const observerRef = useRef<IntersectionObserver | null>(null)
  const nodeRef = useRef<HTMLElement | null>(null)

  // 清理 observer
  const disconnect = useCallback(() => {
    if (observerRef.current) {
      observerRef.current.disconnect()
      observerRef.current = null
    }
  }, [])

  // ref 回调
  const ref = useCallback(
    (node: HTMLElement | null) => {
      // 如果节点相同，不做处理
      if (nodeRef.current === node) return

      // 清理旧的 observer
      disconnect()

      // 保存新节点
      nodeRef.current = node

      // 如果没有节点，直接返回
      if (!node) return

      // 如果已经触发过且只需触发一次，不再观察
      if (triggerOnce && hasBeenInView) return

      // 创建新的 observer
      observerRef.current = new IntersectionObserver(
        (entries) => {
          const entry = entries[0]
          if (entry) {
            const inView = entry.isIntersecting
            setIsInView(inView)

            if (inView) {
              setHasBeenInView(true)
              // 如果只触发一次，进入视口后停止观察
              if (triggerOnce) {
                disconnect()
              }
            }
          }
        },
        {
          threshold,
          rootMargin,
        }
      )

      observerRef.current.observe(node)
    },
    [threshold, rootMargin, triggerOnce, hasBeenInView, disconnect]
  )

  // 组件卸载时清理
  useEffect(() => {
    return () => {
      disconnect()
    }
  }, [disconnect])

  return { ref, isInView, hasBeenInView }
}
