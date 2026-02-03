/**
 * 轮询 Hook
 */
import { useEffect, useRef } from 'react'

interface UsePollingOptions {
  interval?: number // 轮询间隔（毫秒）
  enabled?: boolean // 是否启用轮询
}

export const usePolling = (
  callback: () => void | Promise<void>,
  { interval = 2000, enabled = true }: UsePollingOptions = {}
) => {
  const savedCallback = useRef(callback)

  // 更新回调引用
  useEffect(() => {
    savedCallback.current = callback
  }, [callback])

  // 轮询逻辑
  useEffect(() => {
    if (!enabled) return

    const tick = async () => {
      await savedCallback.current()
    }

    // 立即执行一次
    tick()

    // 设置定时器
    const id = setInterval(tick, interval)

    return () => clearInterval(id)
  }, [interval, enabled])
}
