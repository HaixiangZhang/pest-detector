import { Progress, Space, Statistic } from 'antd'

import type { JobStatus, Progress as ProgressValue } from '../api/types'
import DurationStatistic from './DurationStatistic'

interface Props {
  progress: ProgressValue
  status: JobStatus
}

export default function ProgressPanel({ progress, status }: Props) {
  const { done, total, elapsed } = progress
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  const eta = done > 0 && total > done ? (elapsed / done) * (total - done) : 0

  const barStatus =
    status === 'failed' ? 'exception' : status === 'running' ? 'active' : 'normal'

  return (
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      <Progress percent={percent} status={barStatus} />
      <Space size="large" wrap>
        <Statistic title="已处理帧" value={done} suffix={total ? `/ ${total}` : ''} />
        <DurationStatistic title="已用时间" seconds={elapsed} />
        <DurationStatistic title="预计剩余" seconds={eta} />
      </Space>
    </Space>
  )
}