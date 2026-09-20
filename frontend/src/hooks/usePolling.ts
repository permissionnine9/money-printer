/**
 * 轮询 Hook
 */
import { useEffect, useRef } from 'react'

interface UsePollingOptions {
  interval?: number // 轮询间隔（毫秒）
  enabled?: boolean // 是否启用轮询
  maxPolls?: number // 最大轮询次数（含启动时立即执行的一次；默认不限）
  onMaxPolls?: () => void // 达到最大次数自动停止后的回调
}

export const usePolling = (
  callback: () => void | Promise<void>,
  { interval = 2000, enabled = true, maxPolls = Infinity, onMaxPolls }: UsePollingOptions = {}
) => {
  const savedCallback = useRef(callback)
  const savedOnMaxPolls = useRef(onMaxPolls)

  // 更新回调引用
  useEffect(() => {
    savedCallback.current = callback
  }, [callback])

  useEffect(() => {
    savedOnMaxPolls.current = onMaxPolls
  }, [onMaxPolls])

  // 轮询逻辑
  useEffect(() => {
    if (!enabled) return

    let pollCount = 0
    let timerId: ReturnType<typeof setInterval> | undefined
    let stopped = false

    const stop = () => {
      if (stopped) return
      stopped = true
      if (timerId !== undefined) clearInterval(timerId)
      savedOnMaxPolls.current?.()
    }

    const tick = async () => {
      if (stopped) return
      pollCount += 1
      await savedCallback.current()
      if (pollCount >= maxPolls) stop()
    }

    // 立即执行一次
    tick()

    // 设置定时器
    timerId = setInterval(tick, interval)

    return () => {
      if (timerId !== undefined) clearInterval(timerId)
    }
  }, [interval, enabled, maxPolls])
}
