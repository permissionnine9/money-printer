/**
 * Step5Frames 组件的工具函数
 */

/**
 * 处理图片路径，支持本地路径和完整URL
 */
export const getImageSrc = (path: string | undefined): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `/${path}`
}
