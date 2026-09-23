/**
 * 步骤 4（索引3）：生成视频（远程 ComfyUI 整段生成，远程不可用时 mock）
 *
 * 采用异步轮询模式：
 * 1. 提交生成任务后立即返回
 * 2. 前端轮询获取最新状态
 * 3. 完成后展示最终视频 + timeline_data
 *
 * 分镜数据来源：storyboard_outline.segments（content=已生成提示词或分镜大纲）。
 * 勾选分镜子集拼接 timeline 生成：仅「已完成配置」（configured）的分镜可勾选，
 * 且只能连续选择（分镜编号严格相邻，不可跳选）——勾选仅可紧贴选区两端扩展、
 * 取消仅可从两端收缩；缺省选中最长连续段。至少 1 个分镜 configured 即可进入
 * 本步骤（不再要求全部配置完）。
 * 轨道始终可勾选：生成过之后可重新勾选 → 重新导入 → 再次生成（旧结果自动备份，
 * 可「恢复备份」回滚）。
 */
import React, { useState, useMemo, useEffect } from 'react'
import {
  Card,
  Button,
  message,
  Spin,
  Typography,
  Row,
  Col,
  Tag,
  Space,
  Popconfirm,
  Modal,
  Descriptions,
  Collapse,
  Checkbox,
  Image,
  Empty,
  Alert,
  Input,
  Select,
} from 'antd'
import {
  VideoCameraOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
  LoadingOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  StopOutlined,
  ExclamationCircleOutlined,
  DownloadOutlined,
  CloudUploadOutlined,
} from '@ant-design/icons'
import type { SessionDetail, ComfyUIImport } from '@/types'
import { stepApi, settingsApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'
import { usePolling } from '@/hooks/usePolling'
import { LazyVideo } from '@/components/common/LazyVideo'
import { imageSrc } from '@/utils/imageSrc'

const { Text } = Typography

// 辅助函数：处理媒体路径，支持本地路径和完整URL
const getMediaSrc = (path: string | undefined): string => {
  if (!path) return ''
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `/${path}`
}

// 把有序分镜索引切成连续段（编号严格相邻；configured 中间有洞时存在多段，跨洞不允许）
const splitContiguousRuns = (indexes: number[]): number[][] => {
  const runs: number[][] = []
  let run: number[] = []
  indexes.forEach((idx) => {
    if (run.length && idx === run[run.length - 1] + 1) {
      run.push(idx)
    } else {
      if (run.length) runs.push(run)
      run = [idx]
    }
  })
  if (run.length) runs.push(run)
  return runs
}

// 取最长连续段（并列取最前）：默认选区与断裂收窄共用
const longestRun = (indexes: number[]): number[] =>
  splitContiguousRuns(indexes).sort((a, b) => b.length - a.length)[0] ?? []

interface Step6VideosProps {
  session: SessionDetail
}

export const Step6Videos: React.FC<Step6VideosProps> = ({ session }) => {
  const [loading, setLoading] = useState(false)
  const [importLoading, setImportLoading] = useState(false)
  // 全局提示词（timeline_data.globalPrompt，导入时注入整条时间轴）；回显最近一次导入的值
  const [globalPrompt, setGlobalPrompt] = useState('')
  const { refreshSession } = useSessionStore()

  const outlineSegments: any[] = useMemo(
    () => session.step_results?.storyboard_outline?.result_data?.segments || [],
    [session]
  )
  const configuredSegments = useMemo(
    () => outlineSegments.filter((s) => s.configured),
    [outlineSegments]
  )
  // 门禁：分镜大纲已完成 + ≥1 个分镜已「完成当前分镜配置」
  const canExecute = useMemo(
    () =>
      (session.completed_steps?.includes('storyboard_outline') ?? false) &&
      configuredSegments.length > 0,
    [session, configuredSegments.length]
  )

  const stepResult = session.step_results?.generate_videos?.result_data
  const videos = stepResult?.generated_videos || []
  // ComfyUI 整段生成的最终视频与时间轴配置
  const finalVideo = stepResult?.final_video
  const timelineData = stepResult?.timeline_data

  // 分镜数据源：从分镜大纲映射（携带详情供弹窗展示）
  const segments: any[] = useMemo(() => {
    const params = session.step_results?.select_episode?.result_data?.video_params || {}
    return outlineSegments.map((seg: any, i: number) => ({
      index: seg.index ?? i,
      title: seg.title || '',
      configured: !!seg.configured,
      mode: seg.mode,
      overlap: seg.overlap,
      duration: seg.duration || params.max_segment_duration || 15,
      content: seg.prompt || seg.outline || '',
      prompt: seg.prompt || '',
      outline: seg.outline || '',
      reference_images: seg.reference_images || [],
    }))
  }, [session, outlineSegments])

  // 可勾选参与生成的分镜（configured 子集）
  const selectableIndexes = useMemo(
    () => configuredSegments.map((s) => s.index),
    [configuredSegments]
  )
  // 勾选状态：null=默认选中最长连续段（并列取最前）；手动改选后固定
  const [selectedIndexes, setSelectedIndexes] = useState<number[] | null>(null)
  const effectiveSelected = useMemo(() => {
    const base = selectedIndexes ?? longestRun(selectableIndexes)
    const kept = base.filter((i) => selectableIndexes.includes(i)).sort((a, b) => a - b)
    // 可选集合变化（如回第 3 步取消某分镜配置）可能使勾选断裂：收窄到最长连续子段，
    // 避免展示误导性区间文案或导入时才被后端拒绝
    return longestRun(kept)
  }, [selectedIndexes, selectableIndexes])
  // 连续范围选择（拒绝式）：勾选仅可紧贴选区两端扩展；取消仅可从两端收缩，违规弹回提示
  const toggleSegment = (index: number, checked: boolean) => {
    if (effectiveSelected.length === 0) {
      if (checked) setSelectedIndexes([index])
      return
    }
    const min = effectiveSelected[0]
    const max = effectiveSelected[effectiveSelected.length - 1]
    if (checked) {
      if (index === min - 1 || index === max + 1) {
        setSelectedIndexes([...effectiveSelected, index].sort((a, b) => a - b))
      } else {
        message.warning('只能选择连续的分镜：请紧贴当前选区两端勾选')
      }
    } else {
      if (index === min || index === max) {
        setSelectedIndexes(effectiveSelected.filter((i) => i !== index))
      } else {
        message.warning('不能跳过分镜取消：请从选区两端取消，或点击「清空重选」')
      }
    }
  }
  // 「导入到 ComfyUI」暂存摘要（后端 step_results.comfyui_import；两段式阶段一结果）
  const importedInfo = session.step_results?.comfyui_import?.result_data as
    | ComfyUIImport
    | undefined
  // 首次拿到导入暂存时回填全局提示词输入框（用户未手动编辑过）
  const [globalPromptTouched, setGlobalPromptTouched] = useState(false)
  React.useEffect(() => {
    if (!globalPromptTouched && importedInfo?.global_prompt) {
      setGlobalPrompt(importedInfo.global_prompt)
    }
  }, [importedInfo?.global_prompt, globalPromptTouched])
  // 工作流模板下拉（「导入到 ComfyUI」注入哪套模板）；未手动选择时回显上次导入所用或默认
  const [workflowOptions, setWorkflowOptions] = useState<{ name: string; is_default: boolean }[]>([])
  const [selectedWorkflow, setSelectedWorkflow] = useState<string | null>(null)
  const [workflowTouched, setWorkflowTouched] = useState(false)
  useEffect(() => {
    settingsApi.getComfyUIWorkflows()
      .then((r) => setWorkflowOptions(r.workflows))
      .catch(() => {/* 列表加载失败：下拉留空，导入仍走后端默认模板 */})
  }, [])
  useEffect(() => {
    if (workflowTouched) return
    if (importedInfo?.workflow_name) {
      setSelectedWorkflow(importedInfo.workflow_name)
    } else {
      const def = workflowOptions.find((w) => w.is_default)
      if (def) setSelectedWorkflow(def.name)
    }
  }, [importedInfo?.workflow_name, workflowOptions, workflowTouched])
  // 导入暂存与当前勾选一致时才允许「开始生成」
  const selectionMatchesImport = useMemo(
    () =>
      !!importedInfo &&
      importedInfo.segment_indexes.length === effectiveSelected.length &&
      importedInfo.segment_indexes.every((i) => effectiveSelected.includes(i)),
    [importedInfo, effectiveSelected]
  )
  // 分镜详情弹窗（火车块点击打开）
  const [detailIndex, setDetailIndex] = useState<number | null>(null)
  const detailSegment = useMemo(
    () => segments.find((s) => s.index === detailIndex) || null,
    [segments, detailIndex]
  )

  // 检查是否有正在进行的视频生成任务
  const hasPendingVideos = videos.length > 0 && videos.some((v: any) => v.task_status === 'pending')
  // 检查是否处于后台生成中状态
  const isBackgroundGenerating = stepResult?._generating === true
  // 综合判断是否正在生成
  const isGenerating = hasPendingVideos || isBackgroundGenerating || loading

  // 提交驱动的内存轮询：点「开始生成视频」提交成功后启动；5 秒/次、最多 200 次，
  // 到终态（有视频返回/失败/取消）自动停止；刷新页面即丢失、不再恢复轮询
  const [pollActive, setPollActive] = useState(false)
  usePolling(
    async () => {
      await refreshSession()
    },
    {
      interval: 5000, // 每5秒轮询一次
      maxPolls: 200, // 最多轮询200次
      enabled: pollActive,
      onMaxPolls: () =>
        message.warning('已轮询 200 次仍未完成，已停止自动刷新，请稍后手动刷新查看结果'),
    }
  )
  // 有视频返回（生成到达终态，成功/失败/取消均落盘 _generating=false）后取消轮询
  React.useEffect(() => {
    if (pollActive && stepResult && stepResult._generating !== true && !hasPendingVideos) {
      setPollActive(false)
    }
  }, [pollActive, stepResult, hasPendingVideos])

  // 计算视频生成预览信息（基于勾选分镜子集；总时长已扣除选区内相邻分镜的 overlap 重叠）
  const calculateVideoPreviewInfo = () => {
    const selected = segments.filter((s) => effectiveSelected.includes(s.index))
    let totalDuration = 0
    const segmentDetails: Array<{ index: number; content: string; duration: number }> = []

    selected.forEach((segment: any, k: number) => {
      const duration = segment.duration || 5.0
      // 选区内非首个分镜：扣除其与上一分镜的重叠（overlap 由第 3 步分镜管理配置，随分镜带入拼接）
      totalDuration += duration - (k > 0 ? segment.overlap || 0 : 0)
      segmentDetails.push({
        index: segment.index,
        content: segment.content,
        duration: duration,
      })
    })

    return { totalSegments: selected.length, totalDuration, segmentDetails }
  }

  const videoPreviewInfo = calculateVideoPreviewInfo()

  // 两段式阶段一：导入到 ComfyUI（上传素材 + timeline 注入工作流暂存，不执行）
  const handleImport = async () => {
    setImportLoading(true)
    try {
      const response = await stepApi.importComfyUI(
        // 输入框值未被用户编辑过（只是回显上次导入的 auto 值）时不回传，让后端每次重新自动生成
        session.session_id, effectiveSelected, globalPromptTouched ? (globalPrompt.trim() || undefined) : undefined,
        selectedWorkflow || undefined,
      )
      if (response.success) {
        message.success(response.message || '已导入到 ComfyUI，可点击「开始生成视频」执行')
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setImportLoading(false)
    }
  }

  const handleGenerate = async () => {
    // 显示预览对话框
    Modal.confirm({
      title: '视频生成预览',
      width: 700,
      icon: <VideoCameraOutlined />,
      content: (
        <div>
          <div style={{ marginBottom: 16 }}>
            <Text strong>统计信息：</Text>
            <ul style={{ marginTop: 8 }}>
              <li>
                <Text>总视频数量：{videoPreviewInfo.totalSegments} 个</Text>
              </li>
              <li>
                <Text>预计总时长：约 {videoPreviewInfo.totalDuration.toFixed(1)} 秒</Text>
              </li>
              <li>
                <Text type="secondary">平均时长：约 {(videoPreviewInfo.totalDuration / (videoPreviewInfo.totalSegments || 1)).toFixed(1)} 秒/个</Text>
              </li>
            </ul>
          </div>

          {videoPreviewInfo.segmentDetails.length > 0 && (
            <div style={{ marginTop: 16, maxHeight: 300, overflowY: 'auto' }}>
              <Text strong>视频列表：</Text>
              <div style={{ marginTop: 8 }}>
                {videoPreviewInfo.segmentDetails.map((detail, idx) => (
                  <div
                    key={idx}
                    style={{
                      padding: 8,
                      marginBottom: 8,
                      background: '#fafafa',
                      borderRadius: 4,
                      border: '1px solid #f0f0f0',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <Text strong>视频 {detail.index + 1}</Text>
                      <Tag color="blue">{detail.duration} 秒</Tag>
                    </div>
                    <Text type="secondary" style={{ fontSize: 12, display: 'block', marginTop: 4 }}>
                      {detail.content.substring(0, 50)}{detail.content.length > 50 ? '...' : ''}
                    </Text>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={{ marginTop: 16, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text type="secondary">
              🔗 视频将通过远程 ComfyUI 服务整段生成：各分片首帧与音频素材会上传到 ComfyUI，
              按 timeline_data 多段时间轴合成最终长视频（相邻段按 overlap 衔接）。远程服务不可用时将生成本地 mock 演示视频。
            </Text>
          </div>

          <div style={{ marginTop: 12, padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              💡 生成过程可随时停止，已生成的视频将被保留。您可以稍后继续生成剩余视频。
            </Text>
          </div>
        </div>
      ),
      onOk: async () => {
        setLoading(true)
        try {
          // 两段式阶段二：执行已导入的工作流（导入时参数已注入 ComfyUI 素材规划工作台）
          const response = await stepApi.startComfyUIVideo(session.session_id)
          if (response.success) {
            message.loading('视频生成任务已启动，正在生成中...', 2)
            // 立即刷新以获取pending状态，并启动内存轮询（刷新页面即停止）
            await refreshSession()
            setPollActive(true)
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
      okText: '确认生成',
      cancelText: '取消',
    })
  }

  const handleCancel = async () => {
    setLoading(true)
    try {
      const response = await stepApi.cancelVideos(session.session_id)
      if (response.success) {
        message.success('取消请求已发送，正在停止生成任务...')
        // 立即刷新以获取最新状态
        await refreshSession()
      } else {
        message.error(response.message)
      }
    } catch (error) {
      message.error((error as Error).message)
    } finally {
      setLoading(false)
    }
  }

  const handleRestoreBackup = () => {
    // 二次确认对话框
    Modal.confirm({
      title: '确认恢复备份的视频？',
      icon: <ExclamationCircleOutlined style={{ color: '#1890ff' }} />,
      width: 500,
      content: (
        <div>
          <div style={{ marginBottom: 12 }}>
            <Text>将恢复到上次生成之前的状态，当前结果会被回滚。</Text>
          </div>

          <div style={{ padding: 12, background: '#e6f7ff', borderRadius: 4 }}>
            <Text strong style={{ color: '#0050b3' }}>恢复后：</Text>
            <ul style={{ marginTop: 8, marginBottom: 0, paddingLeft: 20 }}>
              <li>
                <Text type="secondary">所有视频立即恢复到之前的版本</Text>
              </li>
              <li>
                <Text type="secondary">可以重新勾选分镜再次生成</Text>
              </li>
            </ul>
          </div>
        </div>
      ),
      okText: '确认恢复',
      okType: 'primary',
      cancelText: '取消',
      onOk: async () => {
        setLoading(true)
        try {
          const response = await stepApi.restoreVideosBackup(session.session_id)
          if (response.success) {
            message.success(response.message || '备份已恢复')
            // 立即刷新以获取恢复后的状态
            await refreshSession()
          } else {
            message.error(response.message)
          }
        } catch (error) {
          message.error((error as Error).message)
        } finally {
          setLoading(false)
        }
      },
    })
  }

  // 根据 task_status 判断视频状态（优先使用 task_status）
  const getVideoStatus = (video: any): 'completed' | 'pending' | 'failed' | 'cancelled' => {
    // 优先使用 task_status
    if (video.task_status) {
      return video.task_status as 'completed' | 'pending' | 'failed' | 'cancelled'
    }
    // 兼容旧数据：根据 video_path 判断
    if (!video.video_path) return 'pending'
    if (video.video_path.startsWith('生成失败')) return 'failed'
    return 'completed'
  }

  // 渲染状态标签
  const renderStatusTag = (status: string) => {
    switch (status) {
      case 'pending':
        return <Tag icon={<LoadingOutlined />} color="processing">生成中</Tag>
      case 'completed':
        return <Tag icon={<CheckCircleOutlined />} color="success">已完成</Tag>
      case 'failed':
        return <Tag icon={<CloseCircleOutlined />} color="error">失败</Tag>
      case 'cancelled':
        return <Tag icon={<StopOutlined />} color="warning">已取消</Tag>
      default:
        return <Tag icon={<ClockCircleOutlined />} color="default">等待中</Tag>
    }
  }

  // 分镜视频状态映射（segment_index → 该分镜本次生成的状态；无记录=未参与本次生成）
  const videoBySegmentIndex = useMemo(() => {
    const m = new Map<number, any>()
    videos.forEach((v: any) => m.set(v.segment_index, v))
    return m
  }, [videos])

  // 分镜详情弹窗（两个分支共用：火车块点击打开）
  const detailModalNode = (
    <Modal
      title={`分镜 ${(detailSegment?.index ?? 0) + 1}${detailSegment?.title ? `《${detailSegment.title}》` : ''}`}
      open={detailIndex !== null}
      footer={null}
      onCancel={() => setDetailIndex(null)}
      width={720}
      destroyOnHidden
    >
      {detailSegment && (
        <div style={{ maxHeight: 520, overflowY: 'auto' }}>
          <Descriptions bordered size="small" column={2} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="分镜形式">{detailSegment.mode || '—'}</Descriptions.Item>
            <Descriptions.Item label="与上一分镜 overlap">
              {detailSegment.overlap != null ? `${detailSegment.overlap} 秒` : '—'}
            </Descriptions.Item>
            <Descriptions.Item label="时长">{detailSegment.duration ? `${detailSegment.duration} 秒` : '—'}</Descriptions.Item>
            <Descriptions.Item label="配置状态">
              {detailSegment.configured ? (
                <Tag color="success">已完成配置</Tag>
              ) : (
                <Tag>未完成配置</Tag>
              )}
            </Descriptions.Item>
          </Descriptions>

          {/* 本分镜的生成结果（已参与生成的分镜；整段视频共用同一 video_path） */}
          {(() => {
            const video = videoBySegmentIndex.get(detailSegment.index)
            if (!video) return null
            const status = getVideoStatus(video)
            return (
              <Card size="small" style={{ marginBottom: 16 }} title={
                <Space size={8}>
                  <span>本分镜生成结果</span>
                  {renderStatusTag(status)}
                  {video.duration ? <Tag>{video.duration} 秒</Tag> : null}
                </Space>
              }>
                {video.video_path && !video.video_path.startsWith('生成失败') && status === 'completed' ? (
                  <LazyVideo
                    src={getMediaSrc(video.video_path)}
                    poster={video.first_frame_path ? getMediaSrc(video.first_frame_path) : undefined}
                    placeholderHeight={200}
                  />
                ) : status === 'pending' ? (
                  <div style={{ height: 160, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', background: '#f5f5f5' }}>
                    <Spin />
                    <Text style={{ marginTop: 12 }}>视频生成中...</Text>
                  </div>
                ) : (
                  <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', background: status === 'cancelled' ? '#fffbe6' : '#fff2f0' }}>
                    <Text type={status === 'cancelled' ? 'warning' : 'danger'}>
                      {status === 'cancelled' ? '已取消' : '生成失败'}
                    </Text>
                  </div>
                )}
              </Card>
            )
          })()}

          <Card size="small" title="分镜脚本（提示词优先，无则显示大纲）" style={{ marginBottom: 16 }}>
            <Text style={{ whiteSpace: 'pre-wrap' }}>
              {detailSegment.prompt || detailSegment.outline || detailSegment.content || '（无）'}
            </Text>
          </Card>

          <Card size="small" title={`参考素材图（${detailSegment.reference_images?.length || 0} 张）`}>
            {detailSegment.reference_images?.length ? (
              <Row gutter={[12, 12]}>
                {detailSegment.reference_images.map((r: any) => (
                  <Col key={r.image_id} xs={12} sm={8}>
                    <Image
                      src={imageSrc(r.image_path)}
                      alt={r.description}
                      width="100%"
                      height={120}
                      style={{ objectFit: 'cover', borderRadius: 6 }}
                      fallback="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                    />
                    <Text type="secondary" style={{ fontSize: 12, display: 'block' }} ellipsis>
                      {r.description || r.image_id}
                    </Text>
                  </Col>
                ))}
              </Row>
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无参考素材图" />
            )}
          </Card>
        </div>
      )}
    </Modal>
  )

  // 火车轨道：横向排列的分镜块，相邻块视觉重叠（呼应 overlap 衔接），点击块查看详情。
  // 始终可勾选（连续规则）；生成过之后块上标签展示上次生成状态，可重新勾选再次生成。
  const renderTrain = () => (
    <div style={{ marginBottom: 16, padding: '12px 12px 4px', background: '#fafafa', borderRadius: 4, overflowX: 'auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8, gap: 8 }}>
        <Space>
          <Text strong style={{width:"70px",display:"inline-block"}}>选择分镜：</Text>
          <Text type="secondary" style={{ fontSize: 12 }}>
            {`${
              effectiveSelected.length
                ? `已选分镜 ${effectiveSelected[0] + 1}~${effectiveSelected[effectiveSelected.length - 1] + 1}（${effectiveSelected.length}/${selectableIndexes.length} 个可生成分镜）`
                : '未选择分镜'
            }（共 ${segments.length} 个分镜）；仅可连续选择（不可跳选）${
              videoBySegmentIndex.size > 0 ? '，块上标签为上次生成状态，可重新勾选再次生成' : ''
            }；块间重叠示意 overlap 衔接，点击分镜块查看参数/脚本/参考图`}
          </Text>
        </Space>
        <Space style={{ flexShrink: 0 }}>
          <Select
            size="small"
            style={{ minWidth: 210 }}
            value={selectedWorkflow ?? undefined}
            onChange={(v) => {
              setWorkflowTouched(true)
              setSelectedWorkflow(v)
            }}
            placeholder="工作流模板"
            options={workflowOptions.map((w) => ({
              value: w.name,
              label: w.is_default ? `${w.name}（默认）` : w.name,
            }))}
          />
          <Button
            size="small"
            disabled={isGenerating || effectiveSelected.length === 0}
            onClick={() => setSelectedIndexes([])}
          >
            清空重选
          </Button>
          <Button
            size="small"
            type="primary"
            ghost={!importedInfo}
            icon={<CloudUploadOutlined />}
            onClick={handleImport}
            loading={importLoading}
            disabled={isGenerating || effectiveSelected.length === 0}
          >
            导入到 ComfyUI
          </Button>
        </Space>
      </div>
      <div style={{ display: 'flex', alignItems: 'stretch', padding: '8px 4px 12px', minWidth: 0 }}>
        {segments.map((seg: any, i: number) => {
          const selectable = selectableIndexes.includes(seg.index)
          const checked = effectiveSelected.includes(seg.index)
          const video = videoBySegmentIndex.get(seg.index)
          const inThisRun = !!video
          // 未配置完成：空白虚线占位块，不可交互
          if (!selectable) {
            return (
              <div
                key={seg.index}
                style={{
                  width: 150,
                  flexShrink: 0,
                  marginLeft: i === 0 ? 0 : -24,
                  zIndex: i,
                  border: '1px dashed #d9d9d9',
                  borderRadius: 6,
                  padding: '10px 12px',
                  background: 'repeating-linear-gradient(45deg, #fafafa, #fafafa 6px, #f0f0f0 6px, #f0f0f0 12px)',
                  minHeight: 92,
                  opacity: 0.8,
                }}
              >
                <Text type="secondary" style={{ fontSize: 12 }}>
                  分镜 {seg.index + 1}
                </Text>
                <div style={{ marginTop: 8, color: '#bfbfbf', fontSize: 12 }}>未完成配置（占位）</div>
              </div>
            )
          }
          return (
            <div
              key={seg.index}
              onClick={() => setDetailIndex(seg.index)}
              style={{
                width: 150,
                flexShrink: 0,
                marginLeft: i === 0 ? 0 : -24,
                zIndex: i,
                border: `2px solid ${checked ? '#1677ff' : '#91caff'}`,
                background: checked ? '#e6f4ff' : inThisRun ? '#f6ffed' : '#fff',
                borderRadius: 6,
                padding: '10px 12px',
                minHeight: 92,
                cursor: 'pointer',
                boxShadow: checked ? '0 2px 6px rgba(22,119,255,0.25)' : 'none',
                transition: 'all 0.2s',
              }}
              title="点击查看分镜详情"
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                <Checkbox
                  checked={checked}
                  disabled={isGenerating}
                  onClick={(e) => e.stopPropagation()}
                  onChange={(e) => toggleSegment(seg.index, e.target.checked)}
                />
                <Text strong style={{ fontSize: 12 }}>
                  分镜 {seg.index + 1}
                </Text>
              </div>
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  fontWeight: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {seg.title || seg.content?.substring(0, 12) || '（无标题）'}
              </div>
              <div style={{ marginTop: 4, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                <Tag style={{ fontSize: 11 }} color={checked || inThisRun ? 'blue' : 'default'}>
                  {seg.duration || 15}s
                </Tag>
                {seg.overlap > 0 && (
                  <Tag style={{ fontSize: 11 }} color="purple">
                    ↔{seg.overlap}s
                  </Tag>
                )}
              </div>
                {inThisRun && renderStatusTag(getVideoStatus(video))}
            </div>
          )
        })}
      </div>
    </div>
  )

  if (!canExecute) {
    return (
      <Card title="生成视频" style={{ marginTop: 16 }}>
        <div style={{ marginBottom: 16 }}>
          <Text type="secondary">
            请先完成第 2 步：分镜大纲，并在第 3 步对至少 1 个分镜点击「完成当前分镜配置」
          </Text>
        </div>
      </Card>
    )
  }

  // 生成状态统计（标题与 extra 按钮；无生成记录时为默认标题）
  const completedCount = videos.filter((v: any) => getVideoStatus(v) === 'completed').length
  const failedCount = videos.filter((v: any) => getVideoStatus(v) === 'failed').length
  const cancelledCount = videos.filter((v: any) => getVideoStatus(v) === 'cancelled').length
  const pendingCount = videos.filter((v: any) => getVideoStatus(v) === 'pending').length
  const totalCount = videos.length

  // 判断是否全部完成（没有 pending 也没有正在后台生成）
  const isAllCompleted = completedCount === totalCount && !isBackgroundGenerating
  // 判断是否已被取消（有取消的视频且没有正在生成的）
  const isCancelled = cancelledCount > 0 && pendingCount === 0 && !isBackgroundGenerating

  const title = totalCount === 0 ? '生成视频' : isAllCompleted ? (
    <span>
      <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
      视频生成完成 ({completedCount}/{totalCount})
    </span>
  ) : isCancelled ? (
    <span>
      <StopOutlined style={{ color: '#faad14', marginRight: 8 }} />
      视频生成已停止 ({completedCount}/{totalCount} 已完成)
      {cancelledCount > 0 && <Tag color="warning" style={{ marginLeft: 8 }}>{cancelledCount}个已取消</Tag>}
      {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
    </span>
  ) : (
    <span>
      <LoadingOutlined style={{ color: '#1890ff', marginRight: 8 }} />
      视频生成中 ({completedCount}/{totalCount})
      {failedCount > 0 && <Tag color="error" style={{ marginLeft: 8 }}>{failedCount}个失败</Tag>}
    </span>
  )

  // 检查是否有备份数据
  const hasBackup = stepResult?._backed_up_count > 0 || videos.some((v: any) => v._old_video_path)

  // 单一视图：轨道始终可勾选（生成过后可重新勾选 → 重新导入 → 再次生成）
  return (
    <Card
      title={title}
      extra={
        <Space>
          {isGenerating && !stepResult?._cancelled && (
            <Popconfirm
              title="确认停止生成视频？"
              description="已生成的视频会被保留，未生成的视频将停止。"
              onConfirm={handleCancel}
              okText="确认停止"
              cancelText="取消"
            >
              <Button danger icon={<StopOutlined />} loading={loading}>
                停止生成
              </Button>
            </Popconfirm>
          )}
          {hasBackup && !isGenerating && (
            <Button icon={<ReloadOutlined />} onClick={handleRestoreBackup} loading={loading} disabled={loading}>
              恢复备份
            </Button>
          )}
        </Space>
      }
      style={{ marginTop: 16 }}
    >
      <div style={{ marginBottom: 16 }}>
        <Text>
          基于分镜提示词与参考素材，通过远程 ComfyUI 整段生成视频。勾选要参与生成的分镜（须为已完成配置的分镜，且必须连续、不可跳选）；
          段间重叠直接沿用轨道上各分镜的 overlap（第 3 步分镜管理配置，提示词衔接与视频拼接共用同一数值）。
          生成过之后可重新勾选分镜，重新「导入到 ComfyUI」后再次生成（旧结果自动备份，可「恢复备份」回滚）。
        </Text>
      </div>

      {/* 分镜轨道：始终可勾选；生成后块上标签为上次生成状态 */}
      {segments.length > 0 && renderTrain()}

      {/* 全局提示词（timeline_data.globalPrompt，随「导入到 ComfyUI」注入整条时间轴） */}
      {segments.length > 0 && (
        <div style={{ marginBottom: 16 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>
            全局提示词：
          </Text>
          <Input.TextArea
            value={globalPrompt}
            onChange={(e) => {
              setGlobalPrompt(e.target.value)
              setGlobalPromptTouched(true)
            }}
            rows={2}
            placeholder="附加到整条时间轴的全局提示词（如：电影感色调、画面风格、整体氛围），随「导入到 ComfyUI」一起注入"
            disabled={isGenerating}
          />
          {globalPrompt !== (importedInfo?.global_prompt || '') && importedInfo && (
            <Text type="warning" style={{ fontSize: 12, marginTop: 4, display: 'block' }}>
              全局提示词已修改，与最近一次导入不一致，请重新点击「导入到 ComfyUI」
            </Text>
          )}
        </div>
      )}

      {/* 导入到 ComfyUI 摘要（两段式阶段一结果；勾选变化后提示重新导入） */}
      {importedInfo && (
        <Alert
          type={selectionMatchesImport ? 'success' : 'warning'}
          showIcon
          style={{ marginBottom: 16 }}
          title={
            selectionMatchesImport
              ? `已导入到 ComfyUI${importedInfo.mock ? '（mock 模式）' : ''}：${importedInfo.segment_count} 段 / ${importedInfo.image_count} 张参考图 / ${importedInfo.audio_count} 个音频 / 约 ${importedInfo.total_duration} 秒`
              : '当前勾选与最近一次导入的分镜不一致，请重新点击「导入到 ComfyUI」'
          }
          description={
            selectionMatchesImport ? (
              <div>
                导入时间 {importedInfo.imported_at}
                {importedInfo.workflow_name && <>，工作流模板 {importedInfo.workflow_name}</>}
                ，参数已注入远程工作流的「MiniMax H3 素材规划工作台」节点，点击「开始生成视频」执行
                {importedInfo.ui_workflow_name && importedInfo.comfyui_url && (
                  <div>
                    <a
                      href={`${importedInfo.comfyui_url}/#/workflows/${importedInfo.ui_workflow_name}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      在 ComfyUI 中打开工作流
                    </a>
                    （已挂好素材/提示词，可检查微调；微调结果不会回流本系统）
                  </div>
                )}
              </div>
            ) : undefined
          }
        />
      )}

      {/* 预览统计信息 */}
      {segments.length > 0 && (
        <div style={{ marginBottom: 16, padding: 12, background: '#f0f5ff', borderRadius: 4 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>生成任务预览：</Text>
          <Row gutter={16}>
            <Col span={6}>
              <Text type="secondary">视频数量：</Text>
              <Text strong>{videoPreviewInfo.totalSegments} 个</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">预计总时长：</Text>
              <Text strong style={{ color: '#1890ff' }}>约 {videoPreviewInfo.totalDuration.toFixed(1)} 秒</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">平均时长：</Text>
              <Text strong>约 {(videoPreviewInfo.totalDuration / (videoPreviewInfo.totalSegments || 1)).toFixed(1)} 秒</Text>
            </Col>
            <Col span={6}>
              <Text type="secondary">预计耗时：</Text>
              <Text strong style={{ color: '#fa8c16' }}>约 {Math.ceil(videoPreviewInfo.totalSegments * 1.5)} 分钟</Text>
            </Col>
          </Row>
          <div style={{ marginTop: 8 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              ⏱️ 视频生成需要较长时间，每个片段约需 1-2 分钟。生成过程可随时停止，已完成的视频将被保留。
            </Text>
          </div>
        </div>
      )}

      {/* 导入成功后出现「开始生成视频」按钮（两段式阶段二：执行已导入的 ComfyUI 工作流） */}
      <Spin spinning={isGenerating}>
        {importedInfo && selectionMatchesImport && globalPrompt === (importedInfo.global_prompt || '') ? (
          <Button
            type="primary"
            icon={<VideoCameraOutlined />}
            onClick={handleGenerate}
            loading={isGenerating}
            disabled={isGenerating}
            size="large"
          >
            {isGenerating ? '生成中...' : '开始生成视频'}
          </Button>
        ) : (
          <Text type="secondary">
            请先点击分镜轨道右侧的「导入到 ComfyUI」，导入成功后此处出现「开始生成视频」按钮
          </Text>
        )}
      </Spin>


      {/* ===== 最终视频（远程 ComfyUI 整段生成） ===== */}
      {finalVideo?.video_path && !finalVideo.video_path.startsWith('生成失败') && (
        <Card
          size="small"
          style={{ marginBottom: 16, background: '#f6ffed' }}
          title={
            <span>
              <CheckCircleOutlined style={{ color: '#52c41a', marginRight: 8 }} />
              最终视频（远程 ComfyUI 整段生成）
              {finalVideo.mock && (
                <Tag color="orange" style={{ marginLeft: 12 }}>
                  Mock 演示视频（远程服务暂不可用）
                </Tag>
              )}
            </span>
          }
          extra={
            <Button
              size="small"
              icon={<DownloadOutlined />}
              href={getMediaSrc(finalVideo.video_path)}
              target="_blank"
            >
              下载视频
            </Button>
          }
        >
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={14}>
              <LazyVideo
                src={getMediaSrc(finalVideo.video_path)}
                placeholderHeight={320}
              />
            </Col>
            <Col xs={24} lg={10}>
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="分段数量">{finalVideo.segment_count} 段</Descriptions.Item>
                <Descriptions.Item label="段间重叠（合计）">
                  {finalVideo.overlap_seconds} 秒
                </Descriptions.Item>
                <Descriptions.Item label="参考图">{timelineData?.images?.length || 0} 张</Descriptions.Item>
                <Descriptions.Item label="参考音频">{timelineData?.audios?.length || 0} 个</Descriptions.Item>
                <Descriptions.Item label="任务ID">
                  <Text copyable style={{ fontSize: 12 }}>{finalVideo.prompt_id || '-'}</Text>
                </Descriptions.Item>
              </Descriptions>
            </Col>
          </Row>
          {timelineData && (
            <Collapse
              style={{ marginTop: 16 }}
              items={[
                {
                  key: 'timeline',
                  label: 'timeline_data（提交给 ComfyUI 的时间轴配置）',
                  children: (
                    <pre
                      style={{
                        maxHeight: 300,
                        overflow: 'auto',
                        fontSize: 12,
                        background: '#fafafa',
                        padding: 12,
                        borderRadius: 4,
                      }}
                    >
                      {JSON.stringify(timelineData, null, 2)}
                    </pre>
                  ),
                },
              ]}
            />
          )}
        </Card>
      )}
      {detailModalNode}
    </Card>
  )
}