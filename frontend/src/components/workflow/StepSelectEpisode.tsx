/**
 * 步骤1（索引0）：从剧本选集
 * 选择剧本会话 + 分集，并设置视频参数
 */
import React, { useEffect, useState } from 'react'
import {
  Card,
  Form,
  Select,
  Button,
  Space,
  message,
  Modal,
  Row,
  Col,
  Spin,
  Empty,
  InputNumber,
  Typography,
  Descriptions,
  Tag,
} from 'antd'
import { SendOutlined, EditOutlined, ExclamationCircleOutlined } from '@ant-design/icons'
import type { SessionDetail, ScriptSessionDetail, Episode } from '@/types'
import { stepApi, scriptSessionApi, scriptStepApi } from '@/api/client'
import { useSessionStore } from '@/stores/sessionStore'

const { Text } = Typography
const { Option } = Select

// 后续步骤（重新选集时会被清空）
const SUBSEQUENT_STEPS: { step: string; label: string }[] = [
  { step: 'storyboard_outline', label: '步骤2：生成分镜大纲' },
  { step: 'segment_management', label: '步骤3：分镜管理' },
  { step: 'generate_videos', label: '步骤4：生成视频' },
]

interface VideoParamsFormValues {
  resolution: string
  aspect_ratio: string
  film_style: string
  max_segment_duration?: number
}

interface StepSelectEpisodeProps {
  session: SessionDetail
}

export const StepSelectEpisode: React.FC<StepSelectEpisodeProps> = ({ session }) => {
  const [form] = Form.useForm()
  const [scriptSessions, setScriptSessions] = useState<ScriptSessionDetail[]>([])
  const [loadingSessions, setLoadingSessions] = useState(true)
  const [selectedScriptSessionId, setSelectedScriptSessionId] = useState<string | undefined>()
  const [episodes, setEpisodes] = useState<Episode[]>([])
  const [loadingEpisodes, setLoadingEpisodes] = useState(false)
  const [selectedEpisodeId, setSelectedEpisodeId] = useState<string | undefined>()
  const [loading, setLoading] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const { refreshSession } = useSessionStore()

  // 检查是否已完成此步骤
  const isCompleted = session.completed_steps?.includes('select_episode')
  const stepResult = session.step_results?.select_episode?.result_data as
    | {
        script_session_id?: string
        episode_id?: string
        episode_title?: string
        video_params?: { resolution?: string; aspect_ratio?: string; film_style?: string; max_segment_duration?: number }
      }
    | undefined

  // 获取已完成的后续步骤数量
  const completedSubsequentSteps =
    session.completed_steps?.filter((step) => SUBSEQUENT_STEPS.some((s) => s.step === step)).length || 0

  // 加载可用的剧本会话（已完成分集设计）
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const result = await scriptSessionApi.list()
        if (cancelled) return
        setScriptSessions(
          (result.sessions || []).filter((s) => s.completed_steps?.includes('episode_design'))
        )
      } catch (error) {
        message.error((error as Error).message)
      } finally {
        if (!cancelled) setLoadingSessions(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  // 选中剧本会话后加载分集列表
  useEffect(() => {
    if (!selectedScriptSessionId) {
      setEpisodes([])
      return
    }
    let cancelled = false
    setLoadingEpisodes(true)
    scriptStepApi
      .listEpisodes(selectedScriptSessionId)
      .then((eps) => {
        if (!cancelled) setEpisodes(eps || [])
      })
      .catch((error) => {
        message.error((error as Error).message)
      })
      .finally(() => {
        if (!cancelled) setLoadingEpisodes(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedScriptSessionId])

  const handleSubmit = async (values: VideoParamsFormValues) => {
    if (!selectedScriptSessionId || !selectedEpisodeId) {
      message.warning('请先选择剧本会话和分集')
      return
    }
    setLoading(true)
    try {
      const response = await stepApi.selectEpisode(session.session_id, {
        script_session_id: selectedScriptSessionId,
        episode_id: selectedEpisodeId,
        resolution: values.resolution,
        aspect_ratio: values.aspect_ratio,
        film_style: values.film_style,
        max_segment_duration: values.max_segment_duration || 15,
      })
      if (response.success) {
        message.success(response.message)
        setIsEditing(false)
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

  const enterEditMode = () => {
    setIsEditing(true)
    // 预填当前选择
    setSelectedScriptSessionId(stepResult?.script_session_id)
    setSelectedEpisodeId(stepResult?.episode_id)
    form.setFieldsValue({
      resolution: stepResult?.video_params?.resolution || '480p',
      aspect_ratio: stepResult?.video_params?.aspect_ratio || '16:9',
      film_style: stepResult?.video_params?.film_style || '现实主义·照片级真人实拍与纪录片级质感',
      max_segment_duration: stepResult?.video_params?.max_segment_duration || 15,
    })
  }

  const startEditing = () => {
    // 如果有后续步骤已完成，先确认（重新选集将清空后续步骤）
    if (completedSubsequentSteps > 0) {
      Modal.confirm({
        title: '确认重新选集？',
        icon: <ExclamationCircleOutlined />,
        content: (
          <div>
            <p>重新选集将清空后续 {completedSubsequentSteps} 个已完成的步骤数据：</p>
            <ul>
              {SUBSEQUENT_STEPS.filter((s) => session.completed_steps?.includes(s.step)).map((s) => (
                <li key={s.step}>{s.label}</li>
              ))}
            </ul>
            <p>此操作不可撤销，是否继续？</p>
          </div>
        ),
        onOk: () => {
          enterEditMode()
        },
      })
    } else {
      enterEditMode()
    }
  }

  // 已完成状态且不在编辑模式 - 显示当前选择摘要
  if (isCompleted && stepResult && !isEditing) {
    return (
      <Card
        title="已完成选集"
        style={{ marginTop: 16 }}
        extra={
          <Button type="primary" icon={<EditOutlined />} onClick={startEditing}>
            重新选集
          </Button>
        }
      >
        <Descriptions column={1} bordered size="small">
          <Descriptions.Item label="剧本会话">
            {stepResult.script_session_id?.slice(0, 8) || '-'}
          </Descriptions.Item>
          <Descriptions.Item label="分集">
            {stepResult.episode_id ? `${stepResult.episode_id} · ` : ''}
            {stepResult.episode_title || '未命名分集'}
          </Descriptions.Item>
          <Descriptions.Item label="视频参数">
            <Space wrap>
              <span>分辨率: {stepResult.video_params?.resolution || '1080p'}</span>
              <span>宽高比: {stepResult.video_params?.aspect_ratio || '16:9'}</span>
              <span>影视风格: {stepResult.video_params?.film_style || '现实主义·照片级真人实拍与纪录片级质感'}</span>
              <span>分片最大时长: {stepResult.video_params?.max_segment_duration || 15}秒</span>
            </Space>
          </Descriptions.Item>
        </Descriptions>
        {completedSubsequentSteps > 0 && (
          <div style={{ marginTop: 16, padding: 12, background: '#fff7e6', borderRadius: 4 }}>
            <ExclamationCircleOutlined style={{ color: '#fa8c16', marginRight: 8 }} />
            <span style={{ color: '#ad6800' }}>
              后续已完成 {completedSubsequentSteps} 个步骤，重新选集将重置这些步骤
            </span>
          </div>
        )}
      </Card>
    )
  }

  // 选择表单（新会话 / 重新选集）
  return (
    <Card title={isEditing ? '重新选集' : '从剧本选集'} style={{ marginTop: 16 }}>
      {/* ① 选择剧本会话 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>① 剧本会话</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            （仅显示已完成分集设计的剧本会话）
          </Text>
        </div>
        <Spin spinning={loadingSessions}>
          {!loadingSessions && scriptSessions.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description="暂无可用剧本会话，先到创作剧本完成分集设计"
            />
          ) : (
            <Select
              placeholder="选择一个剧本会话"
              value={selectedScriptSessionId}
              onChange={(v) => {
                setSelectedScriptSessionId(v)
                setSelectedEpisodeId(undefined)
              }}
              onClear={() => {
                setSelectedScriptSessionId(undefined)
                setSelectedEpisodeId(undefined)
              }}
              allowClear
              style={{ width: 480, maxWidth: '100%' }}
            >
              {scriptSessions.map((s) => (
                <Option key={s.session_id} value={s.session_id}>
                  {s.title || s.session_id.slice(0, 8)} · {new Date(s.updated_at || s.created_at).toLocaleString()}
                </Option>
              ))}
            </Select>
          )}
        </Spin>
      </div>

      {/* ② 选择分集 */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 8 }}>
          <Text strong>② 分集</Text>
          <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
            （点击卡片选择要制作的分集）
          </Text>
        </div>
        {!selectedScriptSessionId ? (
          <Text type="secondary">请先选择剧本会话</Text>
        ) : loadingEpisodes ? (
          <Spin />
        ) : episodes.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="该剧本会话暂无分集" />
        ) : (
          <Row gutter={[12, 12]}>
            {episodes.map((ep) => {
              const selected = ep.episode_id === selectedEpisodeId
              return (
                <Col xs={24} sm={12} md={8} key={ep.episode_id}>
                  <Card
                    size="small"
                    hoverable
                    onClick={() => setSelectedEpisodeId(ep.episode_id)}
                    style={selected ? { borderColor: '#1677ff', background: '#e6f4ff' } : undefined}
                  >
                    <Card.Meta
                      title={
                        <Space>
                          <span>{ep.episode_id}</span>
                          {selected && <Tag color="blue">已选</Tag>}
                        </Space>
                      }
                      description={
                        <div>
                          <div style={{ fontWeight: 600 }}>{ep.title || '未命名分集'}</div>
                          <div
                            style={{
                              color: '#888',
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                            }}
                          >
                            {ep.logline || '暂无一句话梗概'}
                          </div>
                        </div>
                      }
                    />
                  </Card>
                </Col>
              )
            })}
          </Row>
        )}
      </div>

      {/* ③ 视频参数 */}
      <Form
        form={form}
        layout="vertical"
        onFinish={handleSubmit}
        initialValues={{ resolution: '480p', aspect_ratio: '16:9', film_style: '现实主义·照片级真人实拍与纪录片级质感', max_segment_duration: 15 }}
      >
        <div style={{ marginBottom: 8 }}>
          <Text strong>③ 视频参数</Text>
        </div>
        <Space wrap style={{ marginBottom: 16 }}>
          <Form.Item name="resolution" label="分辨率" style={{ marginBottom: 0 }}>
            <Select style={{ width: 120 }}>
              <Option value="480p">480p</Option>
              <Option value="720p">720p</Option>
              <Option value="1080p">1080p</Option>
              <Option value="4K">4K</Option>
            </Select>
          </Form.Item>

          <Form.Item name="aspect_ratio" label="宽高比" style={{ marginBottom: 0 }}>
            <Select style={{ width: 120 }}>
              <Option value="16:9">16:9</Option>
              <Option value="4:3">4:3</Option>
              <Option value="1:1">1:1</Option>
              <Option value="9:16">9:16</Option>
              <Option value="21:9">21:9</Option>
            </Select>
          </Form.Item>

          <Form.Item name="film_style" label="影视风格" style={{ marginBottom: 0 }}>
            <Select style={{ width: 300 }}>
              <Option value="现实主义·照片级真人实拍与纪录片级质感">现实主义·照片级真人实拍与纪录片级质感</Option>
              <Option value="二次元动漫·日式赛璐璐手绘与高饱和鲜艳色彩">二次元动漫·日式赛璐璐手绘与高饱和鲜艳色彩</Option>
              <Option value="3D动画·皮克斯式卡通渲染与电影级柔和光照">3D动画·皮克斯式卡通渲染与电影级柔和光照</Option>
              <Option value="赛博朋克·霓虹光影与潮湿未来都市质感">赛博朋克·霓虹光影与潮湿未来都市质感</Option>
              <Option value="国风水墨·写意留白与东方水墨氤氲意境">国风水墨·写意留白与东方水墨氤氲意境</Option>
              <Option value="复古胶片·35mm胶片颗粒与暖调怀旧色彩">复古胶片·35mm胶片颗粒与暖调怀旧色彩</Option>
            </Select>
          </Form.Item>

          <Form.Item
            name="max_segment_duration"
            label="分片镜头最大时长"
            style={{ marginBottom: 0 }}
            rules={[{ required: true, message: '请输入分片时长' }]}
          >
            <InputNumber min={5} max={30} style={{ width: 140 }} addonAfter="秒" placeholder="15" />
          </Form.Item>
        </Space>

        <Form.Item>
          <Space>
            <Button
              type="primary"
              htmlType="submit"
              icon={<SendOutlined />}
              loading={loading}
              size="large"
              disabled={!selectedScriptSessionId || !selectedEpisodeId}
            >
              {isEditing ? '确认重新选集' : '确认选集'}
            </Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}
