import { Alert, Card, Skeleton, Space, Tabs, Typography } from 'antd'
import { useEffect, useState } from 'react'

import { ApiError, getDoc, listDocs } from '../api/client'
import type { DocContent, DocItem } from '../api/types'
import Markdown from '../components/Markdown'

export default function Docs() {
  const [items, setItems] = useState<DocItem[]>([])
  const [active, setActive] = useState('web-guide')
  const [doc, setDoc] = useState<DocContent | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    listDocs()
      .then((res) => {
        setItems(res.items)
        if (!res.items.some((item) => item.name === 'web-guide') && res.items.length) {
          setActive(res.items[0].name)
        }
      })
      .catch(() => setItems([]))
  }, [])

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    getDoc(active)
      .then((res) => { if (!cancelled) setDoc(res) })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : '文档加载失败')
      })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [active])

  return (
    <Card
      title="使用文档"
      extra={<Typography.Text type="secondary">文档直接渲染仓库内的 Markdown，离线可用</Typography.Text>}
    >
      <Tabs
        activeKey={active}
        onChange={setActive}
        items={items.map((item) => ({ key: item.name, label: item.title }))}
      />
      {error && <Alert type="error" showIcon message={error} />}
      {loading && <Skeleton active paragraph={{ rows: 8 }} />}
      {!loading && doc && (
        <Space direction="vertical" size="small" style={{ width: '100%' }}>
          <div style={{ maxHeight: '68vh', overflowY: 'auto', paddingRight: 8 }}>
            <Markdown content={doc.content} />
          </div>
        </Space>
      )}
    </Card>
  )
}
