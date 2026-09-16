/**
 * 生成预览弹窗内容组件
 */
import React from 'react'
import { Typography } from 'antd'
import type { ReuseInfo } from './types'

const { Text } = Typography

interface GeneratePreviewModalProps {
  reuseInfo: ReuseInfo
}

export const GeneratePreviewModal: React.FC<GeneratePreviewModalProps> = ({ reuseInfo }) => {
  return (
    <div>
      <div style={{ marginBottom: 16 }}>
        <Text strong>统计信息：</Text>
        <ul style={{ marginTop: 8 }}>
          <li>
            <Text>总分片数：{reuseInfo.totalSegments} 个</Text>
          </li>
          <li>
            <Text>需要生成：{reuseInfo.generateCount} 张图片</Text>
          </li>
          <li>
            <Text style={{ color: '#52c41a' }}>
              将复用：{reuseInfo.reuseCount} 张图片
            </Text>
          </li>
          <li>
            <Text>总帧数：{reuseInfo.totalSegments * 2} 张（{reuseInfo.generateCount} 生成 + {reuseInfo.reuseCount} 复用）</Text>
          </li>
        </ul>
      </div>

      {reuseInfo.reuseDetails.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Text strong>复用详情：</Text>
          <ul style={{ marginTop: 8, maxHeight: '200px', overflowY: 'auto', backgroundColor: '#efefef', padding: '2px 4px' }}>
            {reuseInfo.reuseDetails.map((detail, idx) => (
              <li key={idx}>
                <Text type="secondary">
                  分片 <span style={{ color: "red" }}>{detail.segmentIndex + 1}</span> 的首帧 → 复用自分片 <span style={{ color: "red" }}>{detail.sourceSegment + 1}</span> 的尾帧
                </Text>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div style={{ marginTop: 16, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
        <Text type="secondary">
          💡 提示：相邻分片如果需要100%画面连续（如同一场景的连续动作），将自动复用帧以节省生成成本。
        </Text>
      </div>
    </div>
  )
}
