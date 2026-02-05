/**
 * 懒加载视频组件
 * 只有当视频进入可视区域时才加载
 */
import React from 'react'
import { Spin } from 'antd'
import { useLazyLoad } from '@/hooks/useLazyLoad'

interface LazyVideoProps {
  src: string
  poster?: string
  style?: React.CSSProperties
  controls?: boolean
  className?: string
  /** 占位符高度，默认 300 */
  placeholderHeight?: number
}

export const LazyVideo: React.FC<LazyVideoProps> = ({
  src,
  poster,
  style,
  controls = true,
  className,
  placeholderHeight = 200,
}) => {
  const { ref, hasBeenInView } = useLazyLoad({
    rootMargin: '160px', // 提前 200px 开始加载
    triggerOnce: true,
  })

  return (
    <div ref={ref} style={{ minHeight: placeholderHeight }}>
      {hasBeenInView ? (
        <video
          src={src}
          poster={poster}
          controls={controls}
          className={className}
          style={{ width: '100%', maxHeight: placeholderHeight, ...style }}
        >
          您的浏览器不支持视频播放
        </video>
      ) : (
        <div
          style={{
            height: placeholderHeight,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#f5f5f5',
            borderRadius: 4,
          }}
        >
          <Spin tip="加载中..." />
        </div>
      )}
    </div>
  )
}
