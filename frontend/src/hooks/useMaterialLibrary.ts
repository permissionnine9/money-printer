/**
 * 弹窗打开即加载的分组素材列表（MaterialPickerModal / LookbookLibraryModal 共用）：
 * groups/loading/error 状态 + open 时重置加载 + fetchSeq 竞态守卫（丢弃迟到的旧响应）
 */
import { useCallback, useEffect, useRef, useState } from 'react'

export const useMaterialLibrary = <T>(
  fetcher: (sessionId: string) => Promise<T[]>,
  sessionId: string,
  open: boolean,
) => {
  const [groups, setGroups] = useState<T[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const fetchSeq = useRef(0)

  const reload = useCallback(() => {
    const seq = ++fetchSeq.current
    setLoading(true)
    setError('')
    fetcher(sessionId)
      .then((list) => {
        if (seq === fetchSeq.current) setGroups(list || [])
      })
      .catch((e) => {
        if (seq === fetchSeq.current) setError((e as Error).message)
      })
      .finally(() => {
        if (seq === fetchSeq.current) setLoading(false)
      })
  }, [fetcher, sessionId])

  useEffect(() => {
    if (!open) return
    reload()
    // fetcher 为组件内箭头函数（每次渲染新引用），依赖只取语义项
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, open])

  return { groups, loading, error, reload }
}
