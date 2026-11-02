import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Progress,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from 'antd'
import { Link } from 'react-router-dom'

import { useSystem } from '../hooks/useSystem'

function mb(value: number) {
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

export default function SystemPage() {
  const { info, download, error, loading, refresh, downloadWeights } = useSystem()

  if (error && !info) {
    return (
      <Alert
        type="error"
        showIcon
        message="系统环境检测失败"
        description={error}
        action={<Button onClick={() => refresh(true)}>重试</Button>}
      />
    )
  }
  if (!info) {
    return (
      <Card>
        <Space><Spin /> <Typography.Text type="secondary">正在检测 CPU / GPU / 依赖环境…</Typography.Text></Space>
      </Card>
    )
  }

  const gpu = info.gpu
  const weights = info.weights
  const downloading = download?.status === 'running'
  const downloadFailed = download?.status === 'error'

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {error && <Alert type="warning" showIcon message={error} />}

      <Card
        title="硬件配置"
        extra={<Button onClick={() => refresh(true)} loading={loading}>重新检测</Button>}
      >
        <Row gutter={[16, 16]}>
          <Col xs={24} sm={12} md={6}>
            <Statistic title="逻辑核心" value={info.cpu.logical_cores ?? 0} suffix="核" />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic title="内存总量" value={info.memory.total_gb} suffix="GB" precision={1} />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic title="内存可用" value={info.memory.available_gb} suffix="GB" precision={1} />
          </Col>
          <Col xs={24} sm={12} md={6}>
            <Statistic title="CUDA" value={gpu.cuda_version ?? '无'} />
          </Col>
        </Row>

        <Descriptions column={1} size="small" style={{ marginTop: 16 }}>
          <Descriptions.Item label="处理器">{info.cpu.name}</Descriptions.Item>
          <Descriptions.Item label="操作系统">{info.software.platform}</Descriptions.Item>
          <Descriptions.Item label="显卡">
            {gpu.available ? (
              <Space direction="vertical" size={4}>
                {gpu.devices.map((device) => (
                  <Space key={device.index} wrap>
                    <Tag color="green">GPU {device.index}</Tag>
                    <span>{device.name}</span>
                    <Typography.Text type="secondary">
                      显存 {device.free_gb} / {device.total_gb} GB 可用 · 算力 {device.capability}
                    </Typography.Text>
                  </Space>
                ))}
              </Space>
            ) : (
              <Typography.Text type="danger">{gpu.error ?? '未检测到 GPU'}</Typography.Text>
            )}
          </Descriptions.Item>
          {gpu.driver && (
            <Descriptions.Item label="显卡驱动">NVIDIA {gpu.driver}</Descriptions.Item>
          )}
        </Descriptions>
      </Card>

      <Card title="软件环境">
        <Descriptions column={2} size="small">
          <Descriptions.Item label="Python">{info.software.python}</Descriptions.Item>
          <Descriptions.Item label="PyTorch">{info.software.versions.torch ?? '未安装'}</Descriptions.Item>
          <Descriptions.Item label="Ultralytics">
            {info.software.versions.ultralytics ?? '未安装'}
          </Descriptions.Item>
          <Descriptions.Item label="FastAPI">
            {info.software.versions.fastapi ?? '未安装'}
          </Descriptions.Item>
          <Descriptions.Item label="OpenCV">
            {info.software.versions['opencv-python'] ?? '未安装'}
          </Descriptions.Item>
          <Descriptions.Item label="ffmpeg">
            {info.software.ffmpeg
              ? <Typography.Text code>{info.software.ffmpeg}</Typography.Text>
              : <Tag color="orange">未找到（输出视频将保留 mp4v）</Tag>}
          </Descriptions.Item>
          <Descriptions.Item label="项目根目录" span={2}>
            <Typography.Text code copyable>{info.project_root}</Typography.Text>
          </Descriptions.Item>
          <Descriptions.Item label="前端产物" span={2}>
            {info.software.web_dist_exists
              ? <Tag color="green">已构建</Tag>
              : <Link to="/docs">未构建，请查看「使用文档」</Link>}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card
        title="检测权重"
        extra={
          <Space>
            <Button onClick={() => downloadWeights()} loading={downloading}
                    disabled={weights.valid || downloading}>
              {weights.valid ? '权重已就绪' : '重新下载'}
            </Button>
          </Space>
        }
      >
        {weights.valid ? (
          <Alert
            type="success"
            showIcon
            style={{ marginBottom: 12 }}
            message={`权重就绪（${weights.size_mb} MB）`}
            description={<Typography.Text code copyable>{weights.path}</Typography.Text>}
          />
        ) : (
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="检测权重未就绪"
            description={weights.reason || '文件缺失'}
          />
        )}

        {(downloading || downloadFailed || download?.status === 'done') && (
          <div style={{ marginBottom: 12 }}>
            <Progress
              percent={download?.percent ?? 0}
              status={downloadFailed ? 'exception' : download?.status === 'done' ? 'success' : 'active'}
            />
            <Typography.Text type="secondary">
              {downloadFailed
                ? download?.error
                : download?.status === 'done'
                  ? '下载完成，已通过 SHA256 校验'
                  : `正在下载 ${mb(download?.done_bytes ?? 0)} / ${mb(download?.total_bytes ?? 0)}`}
            </Typography.Text>
          </div>
        )}

        <Descriptions column={1} size="small">
          <Descriptions.Item label="configs.yaml 的 model_path">
            {weights.model_path || '（空，使用已登记权重）'}
          </Descriptions.Item>
          <Descriptions.Item label="默认权重">
            {weights.default_name}（SHA256 {weights.default_sha256.slice(0, 12)}…）
          </Descriptions.Item>
          {weights.config_error && (
            <Descriptions.Item label="配置错误">
              <Typography.Text type="danger">{weights.config_error}</Typography.Text>
            </Descriptions.Item>
          )}
        </Descriptions>

        <Typography.Paragraph type="secondary" style={{ marginTop: 12, marginBottom: 0 }}>
          权重下载自 RicePest-YOLO11x-P2 的 Release；下载后自动校验 SHA256。
          内网环境可设置环境变量 <Typography.Text code>PESTDET_WEIGHT_URL</Typography.Text> 指向镜像地址。
        </Typography.Paragraph>
      </Card>
    </Space>
  )
}
