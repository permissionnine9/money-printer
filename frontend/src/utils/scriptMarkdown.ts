/**
 * 完整剧本导出纯函数（Markdown 拼装 + 浏览器下载）
 */
import type { Episode, EntityRef, ScriptEntity } from '@/types'

// 线索/伏笔动作中文标签
export const ACTION_LABEL: Record<EntityRef['action'], string> = {
  plant: '埋设',
  develop: '发展',
  reveal: '揭示',
  payoff: '兑现',
}

// 剧本小节定义：字段 key → 中文标题（顺序即导出顺序，空字段跳过）
const SECTIONS: { key: keyof Episode; title: string }[] = [
  { key: 'logline', title: '梗概 Logline' },
  { key: 'story_progress', title: '节点进展' },
  { key: 'conflict_chain', title: '矛盾链' },
  { key: 'causality_chain', title: '因果衔接' },
  { key: 'ending_summary', title: '集尾局面' },
]

/** 大纲根节点 `# 剧名` 提取剧名（与后端 get_script_title 同逻辑），失败返回 fallback */
export const extractScriptTitle = (outline: string, fallback = '未命名剧本'): string => {
  for (const line of outline.split('\n')) {
    const t = line.trim()
    if (t.startsWith('# ')) return t.slice(2).trim()
  }
  return fallback
}

/** 大纲嵌入导出文档：跳过根标题行，其余标题行降 2 级（## → ####），避免与文档标题层级冲突 */
export const embedOutline = (outline: string): string =>
  outline
    .split('\n')
    .filter((line) => !line.trim().startsWith('# '))
    .map((line) => line.replace(/^(#{1,6})\s/, '$1## '))
    .join('\n')
    .trim()

/** 拼装完整剧本 markdown：剧名 + 故事大纲 + 逐集（二级标题 + 五小节 + 实体引用行），集间 --- 分隔 */
export const buildScriptMarkdown = (
  episodes: Episode[],
  entities: ScriptEntity[],
  outline: string
): string => {
  const nameById = new Map(entities.map((e) => [e.entity_id, e.name]))
  const entityLine = (id: string, suffix?: string) =>
    `- ${id} ${nameById.get(id) || ''}${suffix ? `（${suffix}）` : ''}`.trimEnd()

  const episodeBlocks = episodes.map((ep) => {
    const num = parseInt(ep.episode_id.replace(/\D/g, ''), 10)
    const parts = [`## 第 ${Number.isNaN(num) ? ep.episode_id : num} 集｜${ep.title || ''}`.trimEnd()]
    for (const s of SECTIONS) {
      const content = (ep[s.key] as string || '').trim()
      if (content) parts.push(`### ${s.title}\n${content}`)
    }
    if (ep.character_ids?.length)
      parts.push(`### 出场人物\n${ep.character_ids.map((id) => entityLine(id)).join('\n')}`)
    if (ep.scene_ids?.length)
      parts.push(`### 出场场景\n${ep.scene_ids.map((id) => entityLine(id)).join('\n')}`)
    for (const [label, refs] of [
      ['线索', ep.clue_refs],
      ['伏笔', ep.foreshadow_refs],
    ] as const) {
      if (refs?.length)
        parts.push(`### ${label}\n${refs.map((r) => entityLine(r.entity_id, ACTION_LABEL[r.action])).join('\n')}`)
    }
    return parts.join('\n\n')
  })

  const header = [`# ${extractScriptTitle(outline)} 完整剧本`]
  const outlineText = embedOutline(outline)
  if (outlineText) header.push(`## 故事大纲\n${outlineText}`)
  return [...header, ...episodeBlocks].join('\n\n---\n\n') + '\n'
}

/** 触发浏览器下载文本文件（Blob + createObjectURL + a.click，用后即 revoke；文件名去除非法字符） */
export const downloadTextFile = (
  filename: string,
  content: string,
  mime = 'text/markdown;charset=utf-8'
): void => {
  const url = URL.createObjectURL(new Blob([content], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename.replace(/[\\/:*?"<>|]/g, '')
  a.click()
  URL.revokeObjectURL(url)
}
