import {
  Button,
  Card,
  Col,
  Collapse,
  Descriptions,
  Row,
  Skeleton,
  Space,
  Statistic,
  Switch,
  Tabs,
  Typography,
} from 'antd'
import { useEffect, useRef, useState } from 'react'

import { getResult, listFrames, resultUrl, videoUrl } from '../api/client'
import type { FrameItem, ResultJson } from '../api/types'
import PerFrameChart from './PerFrameChart'
import SnapshotGrid from './SnapshotGrid'
import TrackOverlay from './TrackOverlay'
import DurationStatistic from './DurationStatistic'

/** 结果可视化：检测结果卡片 + 标注视频（可叠加轨迹/下载）+ 快照网格 + 逐帧曲线 + 轨迹/参数 JSON。 */
export default function ResultView({ jobId }: { jobId: string }) {
  const [result, setResult] = useState<ResultJson | null>(null)
  const [frames, setFrames] = useState<FrameItem[]>([])
  const [failed, setFailed] = useState(false)
  const [overlay, setOverlay] = useState(false)
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    getResult(jobId)
      .then(setResult)
      .catch(() => setFailed(true))
    listFrames(jobId)
      .then((res) => setFrames(res.items))
      .catch(() => setFrames([]))
  }, [jobId])

  if (failed) {
    return <Typography.Text type="secondary">结果数据不可用（可能未开启 JSON 输出）。</Typography.Text>
  }
  if (!result) return <Skeleton active />

  const counting = result.counting ?? {}
  const hasVideo = Boolean(result.outputs?.video)
  const trackCount = result.tracks?.length ?? 0
  const hasPath = (result.tracks ?? []).some((track) => track.path && track.path.length > 1)

  return (
    <div>
      <Row gutter={16}>
        <Col span={6}>
          <Card><Statistic title="检测结果（去重后）" value={counting.unique_count ?? 0}
                           suffix="只" valueStyle={{ color: '#1677ff' }} /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="逐帧检测框累计" value={counting.raw_detections ?? 0} suffix="次" /></Card>
        </Col>
        <Col span={6}>
          <Card><Statistic title="处理帧数" value={result.video?.processed_frames ?? 0} /></Card>
        </Col>
        <Col span={6}>
          <Card><DurationStatistic title="耗时" seconds={result.elapsed_s} /></Card>
        </Col>
      </Row>

      <Card
        title="标注视频"
        style={{ marginTop: 16 }}
        extra={
          <Space>
            <Space size={4}>
              <Typography.Text type="secondary">叠加轨迹</Typography.Text>
              <Switch
                size="small"
                checked={overlay}
                disabled={!hasPath}
                onChange={setOverlay}
              />
            </Space>
            <Button href={videoUrl(jobId)} download disabled={!hasVideo}>下载视频</Button>
            <Button href={resultUrl(jobId)} download>下载结果 JSON</Button>
          </Space>
        }
      >
        {hasVideo ? (
          <>
            <div style={{ position: 'relative', lineHeight: 0 }}>
              <video
                ref={videoRef}
                controls
                preload="metadata"
                src={videoUrl(jobId)}
                style={{ width: '100%', maxHeight: 560, background: '#000', borderRadius: 4 }}
              />
              <TrackOverlay result={result} videoRef={videoRef} visible={overlay} />
            </div>
            <Descriptions size="small" column={4} style={{ marginTop: 12 }}>
              <Descriptions.Item label="分辨率">
                {result.video?.width}×{result.video?.height}
              </Descriptions.Item>
              <Descriptions.Item label="原帧率">{result.video?.fps} fps</Descriptions.Item>
              <Descriptions.Item label="输出帧率">{result.video?.out_fps} fps</Descriptions.Item>
              <Descriptions.Item label="抽帧步长">{result.video?.frame_stride}</Descriptions.Item>
              <Descriptions.Item label="总帧数">{result.video?.total_frames}</Descriptions.Item>
              <Descriptions.Item label="处理帧数">{result.video?.processed_frames}</Descriptions.Item>
              <Descriptions.Item label="轨迹数">{trackCount}</Descriptions.Item>
              <Descriptions.Item label="检测方式">{result.method ?? result.mode}</Descriptions.Item>
            </Descriptions>
            {overlay && (
              <Typography.Text type="secondary">
                轨迹为静态全量叠加（不随播放裁剪），起点以实心圆标记；颜色按轨迹 ID 区分。
              </Typography.Text>
            )}
          </>
        ) : (
          <Typography.Text type="secondary">未输出标注视频（本机编码器不可用）。</Typography.Text>
        )}
      </Card>

      <Tabs
        style={{ marginTop: 16 }}
        items={[
          {
            key: 'frames',
            label: `检出帧快照（${frames.length}）`,
            children: <SnapshotGrid frames={frames} />,
          },
          {
            key: 'curve',
            label: '逐帧虫数曲线',
            children: <PerFrameChart data={result.per_frame ?? []} />,
          },
          {
            key: 'tracks',
            label: `轨迹（${trackCount}）`,
            children: (
              <Collapse
                items={(result.tracks ?? []).map((track) => ({
                  key: String(track.id),
                  label: `ID ${track.id} · 帧 ${track.start_frame}–${track.end_frame} · `
                    + `${track.n_frames} 帧 · 置信度 ${track.confidence_avg}`,
                  children: (
                    <pre style={{ margin: 0, fontSize: 12 }}>
                      {JSON.stringify(track, null, 2)}
                    </pre>
                  ),
                }))}
              />
            ),
          },
          {
            key: 'params',
            label: '参数与 ROI',
            children: (
              <pre style={{ margin: 0, fontSize: 12 }}>
                {JSON.stringify({ config: result.config, roi: result.roi }, null, 2)}
              </pre>
            ),
          },
        ]}
      />
    </div>
  )
}