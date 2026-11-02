import { Tag } from 'antd'

import type { JobStatus } from '../api/types'

const STYLE: Record<JobStatus, { color: string; text: string }> = {
  queued: { color: 'default', text: '排队中' },
  running: { color: 'processing', text: '运行中' },
  succeeded: { color: 'success', text: '已完成' },
  failed: { color: 'error', text: '失败' },
  cancelled: { color: 'warning', text: '已取消' },
}

export default function JobStatusTag({ status }: { status: JobStatus }) {
  const style = STYLE[status] ?? { color: 'default', text: status }
  return <Tag color={style.color}>{style.text}</Tag>
}