/**
 * SSE 客户端（fetch POST + ReadableStream 手动解析）
 *
 * POST 端点无法用 EventSource；GET 事件端点也用同实现（避免 EventSource 自动重连重复消费）。
 */

export interface SSEHandlers {
  /** 每条 data 事件（已 JSON.parse；[DONE] 哨兵不会传入） */
  onEvent: (event: any) => void
  /** 流结束（收到 [DONE]、服务端关闭或 abort） */
  onDone?: () => void
  /** 网络错误 / 非 2xx */
  onError?: (error: Error) => void
}

/**
 * 发起 SSE 请求并消费事件流。
 * 调用方持有 AbortController 实现取消；abort 不算错误。
 */
export async function fetchSSE(
  url: string,
  body: any | undefined,
  handlers: SSEHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const isPost = body !== undefined
  let doneReceived = false
  try {
    const resp = await fetch(url, {
      method: isPost ? 'POST' : 'GET',
      headers: isPost ? { 'Content-Type': 'application/json' } : undefined,
      body: isPost ? JSON.stringify(body) : undefined,
      signal,
    })
    if (!resp.ok || !resp.body) {
      let detail = `HTTP ${resp.status}`
      try {
        const parsed = JSON.parse(await resp.text())
        detail = parsed.detail || detail
      } catch {
        // ignore
      }
      throw new Error(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      // SSE 事件以空行分隔
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const data = part
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trim())
          .join('\n')
        if (!data) continue
        if (data === '[DONE]') {
          doneReceived = true
          continue
        }
        try {
          handlers.onEvent(JSON.parse(data))
        } catch {
          // 非 JSON 行忽略
        }
      }
    }
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      return // 主动取消不算错误
    }
    handlers.onError?.(err instanceof Error ? err : new Error(String(err)))
    return
  }
  handlers.onDone?.()
  void doneReceived
}
