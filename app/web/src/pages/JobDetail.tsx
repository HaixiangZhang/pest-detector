import {
  Alert,
  Button,
  Card,
  Descriptions,
  Popconfirm,
  Skeleton,
  Space,
  Typography,
  message,
} from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'

import { ApiError, cancelJob, getJob, subscribeJobEvents } from '../api/client'
import type { Job, JobEvent } from '../api/types'
import JobStatusTag from '../components/JobStatusTag'
import LogViewer from '../components/LogViewer'
import ProgressPanel from '../components/ProgressPanel'
import ResultView from '../components/ResultView'

export default function JobDetail() {
  const { id = '' } = useParams()
  const [job, setJob] = useState<Job | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [missing, setMissing] = useState(false)

  const reload = useCallback(() => {
    getJob(id).then(setJob).catch(() => setMissing(true))
  }, [id])

  useEffect(() => {
    if (!id) return
    reload()
    const source = subscribeJobEvents(id, (event: JobEvent) => {
      if (event.type === 'status' && event.status) {
        setJob((prev) => (prev ? { ...prev, status: event.status! } : prev))
      } else if (event.type === 'progress') {
        setJob((prev) =>
          prev
            ? {
                ...prev,
                progress: {
                  done: event.done ?? 0,
                  total: event.total ?? 0,
                  elapsed: event.elapsed ?? 0,
                },
              }
            : prev,
        )
      } else if (event.type === 'log' && event.line) {
        setLogs((prev) => [...prev, event.line as string])
      } else if (event.type === 'done') {
        setJob((prev) => (prev ? { ...prev, status: event.status ?? prev.status } : prev))
        source.close()
        reload()          // 拉最终 summary / out_dir
      }
    })
    return () => source.close()
  }, [id, reload])

  const onCancel = async () => {
    try {
      const res = await cancelJob(id)
      message.info(res.cancelled ? '已请求取消' : '任务已结束，无需取消')
    } catch (err) {
      message.error(err instanceof ApiError ? err.message : '取消失败')
    }
  }

  if (missing) return <Alert type="error" message="任务不存在" showIcon />
  if (!job) return <Skeleton active />

  const active = job.status === 'queued' || job.status === 'running'

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Card
        title={
          <Space>
            <span>任务 {job.id}</span>
            <JobStatusTag status={job.status} />
          </Space>
        }
        extra={
          <Popconfirm
            title="确认取消该任务？"
            onConfirm={onCancel}
            disabled={!active}
          >
            <Button danger disabled={!active}>取消任务</Button>
          </Popconfirm>
        }
      >
        <Descriptions column={2} size="small">
          <Descriptions.Item label="视频">
            {job.source.split(/[\\/]/).pop()}
          </Descriptions.Item>
          <Descriptions.Item label="模式">{job.mode}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{job.created_at}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{job.started_at ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="结束时间">{job.finished_at ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="输出目录">{job.out_dir ?? '—'}</Descriptions.Item>
        </Descriptions>

        <div style={{ marginTop: 16 }}>
          <ProgressPanel progress={job.progress} status={job.status} />
        </div>
      </Card>

      {job.status === 'failed' && job.error && (
        <Alert
          type="error"
          showIcon
          message={`执行失败：${job.error.code}`}
          description={<Typography.Text>{job.error.message}</Typography.Text>}
        />
      )}

      <Card title="实时日志">
        <LogViewer lines={logs} />
      </Card>

      {job.status === 'succeeded' && (
        <Card title="结果">
          <ResultView jobId={job.id} />
        </Card>
      )}
    </Space>
  )
}