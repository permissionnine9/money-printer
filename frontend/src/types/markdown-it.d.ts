// markdown-it 无官方类型声明，这里做最小声明
declare module 'markdown-it' {
  interface MarkdownIt {
    render(src: string): string
  }
  interface MarkdownItOptions {
    html?: boolean
    linkify?: boolean
    typographer?: boolean
    breaks?: boolean
  }
  const MarkdownIt: new (options?: MarkdownItOptions) => MarkdownIt
  export default MarkdownIt
}
