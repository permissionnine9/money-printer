/**
 * 图片路径展示 helper：http(s) URL 原样返回，本地相对路径补 `/` 前缀
 * （后端 image_path 同时承载远程 URL 与 static/ 相对路径）
 */
export const imageSrc = (path: string | undefined): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `/${path}`
}
