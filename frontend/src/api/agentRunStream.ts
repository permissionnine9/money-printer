/**
 * 全局 Agent run 事件流（单连接多路复用）
 *
 * 浏览器对同 host 的 HTTP/1.1 并发连接仅 6 个：任务坞对每个进行中 run 保持一条
 * SSE 观流连接，批量任务（分镜提示词/素材图等）会占满连接池，其余接口在浏览器
 * 侧排队 pending——改为全部 run 复用本模块的单条连接，事件按 run_id 分发。
 * 断线重连带 per-run seq 游标增量续传（delta 为追加式，全量重放会重复累积）。
 */
import { fetchSSE } from '@/api/sse'

type Handler = (event: any) => void

const RECONNECT_INTERVAL = 2000

class AgentRunStream {
  /** runId → 订阅者（首个订阅建立连接，全部退订断开连接） */
  private handlers = new Map<string, Set<Handler>>()
  /** runId → 已消费 seq（重连续传游标；done 后清除） */
  private cursors = new Map<string, number>()
  private controller: AbortController | null = null
  private running = false
  /** 连接代际：重连递增，旧 connect 循环据此退出（防两条并发连接） */
  private epoch = 0

  subscribe(runId: string, handler: Handler): () => void {
    const isNewRun = !this.handlers.has(runId)
    let set = this.handlers.get(runId)
    if (!set) {
      set = new Set()
      this.handlers.set(runId, set)
    }
    set.add(handler)
    if (!this.running) {
      void this.connect()
    } else if (isNewRun) {
      // 新 run 订阅前的缓冲帧已被丢弃：重连取回（已挂载 run 带游标只拿增量，
      // 新 run 全量回放），与 per-run 观流连接时的全量回放语义一致
      this.reconnect()
    }
    return () => {
      const s = this.handlers.get(runId)
      if (s) {
        s.delete(handler)
        if (!s.size) {
          this.handlers.delete(runId)
          this.cursors.delete(runId)
        }
      }
      // handlers 可能已被 done 清理（组件迟到的卸载），无论哪种路径都不应遗留空连接
      if (!this.handlers.size) this.disconnect()
    }
  }

  private disconnect(): void {
    this.running = false
    this.epoch += 1
    this.controller?.abort()
    this.controller = null
  }

  /** 断开当前连接并立即重建（带最新游标） */
  private reconnect(): void {
    this.disconnect()
    void this.connect()
  }

  private async connect(): Promise<void> {
    this.running = true
    const epoch = ++this.epoch
    while (this.running && epoch === this.epoch) {
      const controller = (this.controller = new AbortController())
      await fetchSSE(
        this.url(),
        undefined,
        { onEvent: (ev) => this.dispatch(ev) },
        controller.signal,
      )
      if (!this.running || epoch !== this.epoch) break
      await new Promise((r) => setTimeout(r, RECONNECT_INTERVAL))
    }
  }

  /** 重连 URL：仅带仍有订阅者的 run 游标 */
  private url(): string {
    const cursors = [...this.handlers.keys()]
      .map((runId) => `${runId}:${this.cursors.get(runId) ?? 0}`)
      .join(',')
    return `/api/v1/agent-runs/events${cursors ? `?cursors=${cursors}` : ''}`
  }

  private dispatch(ev: any): void {
    const runId = ev?.run_id
    if (!runId) return
    if (typeof ev.seq === 'number' && ev.seq > (this.cursors.get(runId) ?? 0)) {
      this.cursors.set(runId, ev.seq)
    }
    const set = this.handlers.get(runId)
    if (set) set.forEach((h) => h(ev))
    if (ev.type === 'done') {
      // 终态后不再跟踪该 run（重连不续传；服务端对其回放的事件无订阅者、直接丢弃）
      this.handlers.delete(runId)
      this.cursors.delete(runId)
    }
  }
}

export const agentRunStream = new AgentRunStream()
