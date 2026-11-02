import { Button, Card, Space, Table, Typography } from 'antd'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { listJobs } from '../api/client'
import type { Job } from '../api/types'
import JobStatusTag from '../components/JobStatusTag'

export default function Jobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(false)

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await listJobs(100, 0)
      setJobs(res.items)
      setTotal(res.total)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const timer = setInterval(refresh, 5000)   // 轻量自动刷新（列表页）
    return () => clearInterval(timer)
  }, [refresh])

  return (
    <Card
      title={`任务列表（${total}）`}
      extra={<Button onClick={refresh} loading={loading}>刷新</Button>}
    >
      <Table<Job>
        rowKey="id"
        dataSource={jobs}
        loading={loading}
        pagination={false}
        columns={[
          {
            title: '任务 ID',
            dataIndex: 'id',
            render: (id: string) => <Link to={`/jobs/${id}`}>{id}</Link>,
          },
          {
            title: '状态',
            dataIndex: 'status',
            width: 100,
            render: (status: Job['status']) => <JobStatusTag status={status} />,
          },
          { title: '模式', dataIndex: 'mode', width: 90 },
          {
            title: '视频',
            dataIndex: 'source',
            ellipsis: true,
            render: (source: string) => source.split(/[\\/]/).pop(),
          },
          {
            title: '检测结果',
            width: 100,
            render: (_, job) => job.summary?.unique_count ?? '—',
          },
          { title: '创建时间', dataIndex: 'created_at', width: 170 },
          {
            title: '操作',
            width: 100,
            render: (_, job) => (
              <Space>
                <Link to={`/jobs/${job.id}`}>详情</Link>
              </Space>
            ),
          },
        ]}
      />
      {jobs.length === 0 && !loading && (
        <Typography.Text type="secondary">暂无任务，去「新建任务」提交一个。</Typography.Text>
      )}
    </Card>
  )
}