import {
  Alert,
  Button,
  Card,
  Col,
  Collapse,
  Divider,
  Form,
  InputNumber,
  List,
  Popconfirm,
  Progress,
  Radio,
  Row,
  Select,
  Space,
  Switch,
  Tag,
  Typography,
  Upload,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import {
  ApiError,
  createJob,
  deleteUpload,
  getConfigSchema,
  listPresets,
  listUploads,
  listVideos,
  savePreset,
  uploadVideo,
  uploadVideoUrl,
} from '../api/client'
import type { DetectMode, PresetItem, UploadItem, VideoItem } from '../api/types'

/** 递归剔除空值（undefined / null / 空串），避免把未填字段当成覆盖项。 */
function prune<T>(value: T): T {
  if (Array.isArray(value)) return value
  if (value && typeof value === 'object') {
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      const cleaned = prune(item)
      if (cleaned !== undefined && cleaned !== null && cleaned !== '') out[key] = cleaned
    }
    return out as T
  }
  return value
}

/** 深合并（preset 增量覆盖默认配置），数组整体替换。 */
function deepMerge<T>(base: T, overlay: unknown): T {
  if (overlay === null || overlay === undefined) return base
  if (
    typeof base !== 'object' || base === null || Array.isArray(base) ||
    typeof overlay !== 'object' || Array.isArray(overlay)
  ) {
    return overlay as T
  }
  const out: Record<string, unknown> = { ...(base as Record<string, unknown>) }
  for (const [key, value] of Object.entries(overlay as Record<string, unknown>)) {
    out[key] = key in out ? deepMerge(out[key], value) : value
  }
  return out as T
}

function videoLabel(name: string, sizeMb: number, duration: number | null) {
  return `${name}（${sizeMb} MB${duration ? `, ${duration}s` : ''}）`
}

interface NumField {
  name: string
  label: string
  tooltip?: string
  min?: number
  max?: number
  step?: number
}

// 跨帧关联与轨迹后处理的全部数值参数（与 configs.yaml 的 tracker 节一一对应）
const TRACKER_GROUPS: { title: string; fields: NumField[] }[] = [
  {
    title: '匹配阈值',
    fields: [
      { name: 'high_thresh', label: '高分框阈值', min: 0, max: 1, step: 0.05, tooltip: '进第一轮匹配、允许起轨的最低置信度' },
      { name: 'low_thresh', label: '低分框阈值', min: 0, max: 1, step: 0.05, tooltip: '低于此值直接丢弃；两者之间留作第二轮救回' },
      { name: 'new_track_thresh', label: '新建轨迹阈值', min: 0, max: 1, step: 0.05, tooltip: '新建轨迹的最低置信度（防误检起轨）' },
      { name: 'match_thresh', label: '第一轮匹配阈值', min: 0, max: 1, step: 0.05, tooltip: '第一轮匹配：速度已建立的轨迹' },
      { name: 'second_match_thresh', label: '第二轮匹配阈值', min: 0, max: 1, step: 0.05, tooltip: '第二轮：用低分框救回快断的轨迹' },
      { name: 'boot_match_iou', label: '起步期放宽阈值', min: 0, max: 1, step: 0.05, tooltip: '起步期（速度未知）放宽，避免小目标起步即断链' },
      { name: 'match_dist_gate', label: '距离门控系数', min: 0, step: 0.5, tooltip: '兜住「位移大但确是同一目标」：分数 = max(IoU, 1-中心距/(gate×框尺寸))' },
    ],
  },
  {
    title: '轨迹生命周期',
    fields: [
      { name: 'track_buffer', label: '丢失保留帧数', min: 0, tooltip: '丢失后保留帧数；必须小于「最大关联间隔」，否则复活窗口为空' },
      { name: 'min_track_frames', label: '短轨迹过滤阈值', min: 0, tooltip: '存活帧数低于此值判为误检' },
    ],
  },
  {
    title: '断轨合并与空间去重',
    fields: [
      { name: 'merge_gap_frames', label: '最大关联间隔', min: 0, tooltip: '两段轨迹首尾相隔超过此帧数即认为无关；须大于「丢失保留帧数」' },
      { name: 'merge_dist_threshold', label: '关联距离上限', min: 0, tooltip: '单位像素；与「关联速度上限」取小' },
      { name: 'merge_speed_max', label: '关联速度上限', min: 0, tooltip: '单位像素/帧；挡住「一帧跨半屏」的误接' },
      { name: 'spatial_overlap', label: '空间去重 IoU', min: 0, max: 1, step: 0.05, tooltip: '同时刻框 IoU 超过此值的帧过半 → 判为同一只' },
    ],
  },
]

export default function NewJob() {
  const [form] = Form.useForm()
  const navigate = useNavigate()
  const [videos, setVideos] = useState<VideoItem[]>([])
  const [uploads, setUploads] = useState<UploadItem[]>([])
  const [presets, setPresets] = useState<PresetItem[]>([])
  const [defaults, setDefaults] = useState<Record<string, any> | null>(null)
  const [errors, setErrors] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState<number | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const selectedPreset = Form.useWatch('preset', form)
  const mode = Form.useWatch('mode', form) as DetectMode | undefined

  const refreshUploads = () =>
    listUploads()
      .then((res) => setUploads(res.items))
      .catch(() => message.error('加载上传历史失败'))

  /** 用「默认配置 + 预设增量」回填表单，保证提交值与预设一致、不会把预设冲掉。 */
  const applyEffective = useCallback(
    (preset?: PresetItem) => {
      if (!defaults) return
      const cfg = preset ? deepMerge(defaults, preset.params) : defaults
      form.setFieldsValue({
        mode: cfg.mode,
        frame_stride: cfg.frame_stride,
        max_frames: cfg.max_frames,
        sahi: {
          conf: cfg.sahi?.conf,
          slice_size: cfg.sahi?.slice_size,
          overlap_ratio: cfg.sahi?.overlap_ratio,
          batch: cfg.sahi?.batch,
        },
        direct: { imgsz: cfg.direct?.imgsz, batch: cfg.direct?.batch },
        mask: { enabled: cfg.mask?.enabled },
        tracker: { ...(cfg.tracker ?? {}) },
      })
    },
    [defaults, form],
  )

  useEffect(() => {
    listVideos()
      .then((res) => setVideos(res.items))
      .catch(() => message.error('加载视频列表失败'))
    refreshUploads()
    listPresets()
      .then((res) => setPresets(res.items))
      .catch(() => undefined)
    getConfigSchema()
      .then(({ defaults: loaded }) => setDefaults(loaded as Record<string, any>))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!defaults) return
    applyEffective(presets.find((item) => item.name === selectedPreset))
  }, [defaults, presets, selectedPreset, applyEffective])

  const onUpload = async (file: File) => {
    setUploading(0)
    try {
      const item = await uploadVideo(file, (percent) => setUploading(percent))
      await refreshUploads()
      form.setFieldValue('source', item.path)
      setPreviewUrl(uploadVideoUrl(item.name))
      message.success(`已上传 ${item.name}`)
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '上传失败')
    } finally {
      setUploading(null)
    }
    return false
  }

  const onSelectSource = (path: string) => {
    const matched = uploads.find((item) => item.path === path)
    setPreviewUrl(matched ? uploadVideoUrl(matched.name) : null)
  }

  const onDeleteUpload = async (name: string) => {
    try {
      await deleteUpload(name)
      message.success('已删除')
      if (form.getFieldValue('source')?.endsWith(name)) {
        form.setFieldValue('source', undefined)
        setPreviewUrl(null)
      }
      await refreshUploads()
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '删除失败')
    }
  }

  const onReset = () => {
    form.resetFields()            // 回到 initialValues（mode=sahi / preset=default）
    applyEffective(presets.find((item) => item.name === 'default'))  // 其余字段回填默认配置
  }

  /** 把当前表单里的推理参数存成「默认」预设，下次打开自动带出。 */
  const onSaveConfig = async () => {
    const values = form.getFieldsValue(true) as Record<string, any>
    const params = { ...values }
    delete params.source                 // 视频选择与预设名不算推理配置
    delete params.preset
    setSaving(true)
    setErrors([])
    try {
      await savePreset('default', prune(params))
      const res = await listPresets()
      setPresets(res.items)
      message.success('推理配置已保存（默认）')
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.errors.length ? err.errors : [err.message])
      } else {
        setErrors(['保存失败'])
      }
    } finally {
      setSaving(false)
    }
  }

  const onFinish = async (values: Record<string, any>) => {
    setSubmitting(true)
    setErrors([])
    const { source, mode: detectMode, preset, ...params } = values
    try {
      const res = await createJob({
        source,
        mode: detectMode as DetectMode,
        preset: preset ?? null,
        params: prune(params),
      })
      message.success('任务已提交')
      navigate(`/jobs/${res.job_id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.errors.length ? err.errors : [err.message])
      } else {
        setErrors(['提交失败'])
      }
    } finally {
      setSubmitting(false)
    }
  }

  const sourceOptions = [
    ...(uploads.length
      ? [{
          label: '我的上传（本地保存）',
          options: uploads.map((item) => ({
            value: item.path,
            label: videoLabel(item.name, item.size_mb, item.duration_s),
          })),
        }]
      : []),
    ...(videos.length
      ? [{
          label: '服务器视频库',
          options: videos.map((item) => ({
            value: item.path,
            label: videoLabel(item.name, item.size_mb, item.duration_s),
          })),
        }]
      : []),
  ]

  const numItem = (field: NumField, prefix: string) => (
    <Col span={6} key={field.name}>
      <Form.Item name={[prefix, field.name]} label={field.label} tooltip={field.tooltip}>
        <InputNumber min={field.min} max={field.max} step={field.step ?? 1}
                     style={{ width: '100%' }} />
      </Form.Item>
    </Col>
  )

  const advancedContent = (
    <>
      <Typography.Text type="secondary">草地遮罩</Typography.Text>
      <Row gutter={16} style={{ marginTop: 8 }}>
        <Col span={8}>
          <Form.Item name={['mask', 'enabled']} label="启用草地遮罩" valuePropName="checked"
                     tooltip="关闭则整帧推理；其余遮罩参数（阈值/拟合）在 configs.yaml 的 mask 节">
            <Switch />
          </Form.Item>
        </Col>
      </Row>

      <Divider style={{ margin: '8px 0 16px' }} />

      <Typography.Text type="secondary">
        {mode === 'direct' ? '整帧直推（direct）参数' : '切片检测（sahi）参数'}
      </Typography.Text>
      {mode === 'direct' ? (
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={6}>
            <Form.Item name={['direct', 'imgsz']} label="推理尺寸">
              <InputNumber min={320} step={32} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name={['direct', 'batch']} label="帧批 batch"
                       tooltip="显存敏感：8GB 建议 1–2">
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
      ) : (
        <Row gutter={16} style={{ marginTop: 8 }}>
          <Col span={6}>
            <Form.Item name={['sahi', 'conf']} label="置信度阈值">
              <InputNumber min={0} max={1} step={0.05} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name={['sahi', 'slice_size']} label="切片大小">
              <InputNumber min={64} step={64} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name={['sahi', 'overlap_ratio']} label="切片重叠">
              <InputNumber min={0} max={0.9} step={0.05} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={6}>
            <Form.Item name={['sahi', 'batch']} label="切片 batch"
                       tooltip="显存敏感：8GB 建议 1–4">
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>
      )}

      <Divider style={{ margin: '8px 0 16px' }} />

      <Typography.Text type="secondary">跨帧关联与轨迹后处理</Typography.Text>
      {TRACKER_GROUPS.map((group) => (
        <div key={group.title}>
          <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 12, display: 'block' }}>
            {group.title}
          </Typography.Text>
          <Row gutter={16} style={{ marginTop: 8 }}>
            {group.fields.map((field) => numItem(field, 'tracker'))}
          </Row>
        </div>
      ))}

      <Typography.Text type="secondary" style={{ fontSize: 12, marginTop: 12, display: 'block' }}>
        稳定确认
      </Typography.Text>
      <Row gutter={16} style={{ marginTop: 8 }}>
        <Col span={6}>
          <Form.Item name={['tracker', 'confirm_enabled']} label="稳定确认门控"
                     valuePropName="checked"
                     tooltip="开启后需在窗口内命中足够帧才计入，抑制闪光误检">
            <Switch />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item name={['tracker', 'confirm_window']} label="确认窗口帧数"
                     tooltip="0 = 不启用窗口门控">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
        <Col span={6}>
          <Form.Item name={['tracker', 'confirm_min_hits']} label="窗口内最少命中"
                     tooltip="0 = 不启用窗口门控">
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Col>
      </Row>
    </>
  )

  return (
    <Card title="新建检测任务" style={{ maxWidth: 900 }}>
      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="参数校验未通过"
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.map((text) => <li key={text}>{text}</li>)}
            </ul>
          }
        />
      )}

      <Form form={form} layout="vertical" onFinish={onFinish}
            initialValues={{ mode: 'sahi', preset: 'default' }}>
        <Form.Item label="上传视频">
          <Upload.Dragger
            name="file"
            accept="video/*"
            multiple={false}
            showUploadList={false}
            beforeUpload={(file) => onUpload(file as unknown as File)}
          >
            <p className="ant-upload-text">点击或拖拽视频到此处上传</p>
            <p className="ant-upload-hint">
              支持 mp4 / avi / mov / mkv 等；上传后保存在服务器 data/uploads/，刷新不丢
            </p>
          </Upload.Dragger>
          {uploading !== null && (
            <Progress percent={uploading} size="small" style={{ marginTop: 8 }} />
          )}
        </Form.Item>

        <Form.Item name="source" label="待检测视频"
                   rules={[{ required: true, message: '请上传或选择视频' }]}>
          <Select
            showSearch
            placeholder="从「我的上传」或「服务器视频库」中选择"
            optionFilterProp="label"
            options={sourceOptions}
            onChange={onSelectSource}
          />
        </Form.Item>

        {previewUrl && (
          <video
            controls
            preload="metadata"
            src={previewUrl}
            style={{ width: '100%', maxHeight: 320, background: '#000', borderRadius: 4 }}
          />
        )}

        {uploads.length > 0 && (
          <>
            <Divider orientation="left" plain style={{ marginTop: 24 }}>
              上传历史（{uploads.length}）
            </Divider>
            <List
              size="small"
              dataSource={uploads}
              renderItem={(item) => (
                <List.Item
                  actions={[
                    <Button type="link" size="small"
                            onClick={() => {
                              form.setFieldValue('source', item.path)
                              setPreviewUrl(uploadVideoUrl(item.name))
                            }}>
                      用作输入
                    </Button>,
                    <Popconfirm title="删除该上传文件？" onConfirm={() => onDeleteUpload(item.name)}>
                      <Button type="link" size="small" danger>删除</Button>
                    </Popconfirm>,
                  ]}
                >
                  <List.Item.Meta
                    title={item.name}
                    description={`${item.size_mb} MB${item.duration_s ? ` · ${item.duration_s}s` : ''}`}
                  />
                </List.Item>
              )}
            />
          </>
        )}

        <Divider orientation="left" plain style={{ marginTop: 24 }}>检测参数</Divider>

        <Row gutter={16}>
          <Col span={8}>
            <Form.Item name="mode" label="检测模式"
                       tooltip="sahi=切片检测，4K 小目标召回更高；direct=整帧直推，更快">
              <Radio.Group>
                <Radio.Button value="sahi">sahi 切片</Radio.Button>
                <Radio.Button value="direct">direct 直推</Radio.Button>
              </Radio.Group>
            </Form.Item>
          </Col>
          <Col span={8}>
            <Form.Item name="preset" label="参数预设" tooltip="只有「默认」一套；调好参数后点下方「保存推理配置」即可覆盖它">
              <Select
                options={presets.map((preset) => ({ value: preset.name, label: preset.label }))}
              />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="frame_stride" label="抽帧间隔">
              <InputNumber min={1} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
          <Col span={4}>
            <Form.Item name="max_frames" label="最大帧数"
                       tooltip="0 = 不限制">
              <InputNumber min={0} style={{ width: '100%' }} />
            </Form.Item>
          </Col>
        </Row>

        {selectedPreset && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 16 }}
            message={
              <Space>
                预设 <Tag>{presets.find((item) => item.name === selectedPreset)?.label ?? selectedPreset}</Tag>
                为当前部署配置；修改参数后可点下方「保存推理配置」写回该预设
              </Space>
            }
          />
        )}

        <Collapse
          activeKey={advancedOpen ? ['params'] : []}
          onChange={(keys) => setAdvancedOpen(keys.length > 0)}
          items={[{
            key: 'params',
            label: (
              <Space>
                <span>参数调节</span>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  （草地遮罩 / 检测器 / 跨帧关联与轨迹后处理）
                </Typography.Text>
              </Space>
            ),
            children: advancedContent,
          }]}
        />

        <Form.Item style={{ marginTop: 16 }}>
          <Space>
            <Button type="primary" htmlType="submit" loading={submitting}>提交任务</Button>
            <Button onClick={onSaveConfig} loading={saving}>保存推理配置</Button>
            <Button onClick={onReset}>重置</Button>
          </Space>
        </Form.Item>
      </Form>
    </Card>
  )
}