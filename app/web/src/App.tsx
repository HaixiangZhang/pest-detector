import { Alert, Layout, Menu, Progress, Space, Tag, Typography } from 'antd'
import { Link, Route, Routes, useLocation } from 'react-router-dom'

import { SystemProvider, useSystem } from './hooks/useSystem'
import Docs from './pages/Docs'
import JobDetail from './pages/JobDetail'
import Jobs from './pages/Jobs'
import NewJob from './pages/NewJob'
import SystemPage from './pages/SystemPage'

const { Header, Content } = Layout

function navKey(pathname: string) {
  if (pathname.startsWith('/jobs')) return 'jobs'
  if (pathname.startsWith('/system')) return 'system'
  if (pathname.startsWith('/docs')) return 'docs'
  return 'new'
}

function Shell() {
  const location = useLocation()
  const { info, download, error } = useSystem()
  const weightsMissing = info != null && !info.weights.valid
  const downloadFailed = download?.status === 'error'

  return (
    <Layout style={{ minHeight: '100vh', background: '#f5f7fa' }}>
      <Header style={{
        display: 'flex', alignItems: 'center', gap: 24,
        background: 'linear-gradient(90deg, #0b3d2e 0%, #15803d 100%)',
        padding: '0 24px', height: 64,
      }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0, whiteSpace: 'nowrap' }}>
          pest_detector
          <Typography.Text style={{ color: 'rgba(255,255,255,.65)', fontSize: 13, marginLeft: 10 }}>
            4K 害虫检测与跨帧去重计数
          </Typography.Text>
        </Typography.Title>

        <Menu
          mode="horizontal"
          theme="dark"
          selectedKeys={[navKey(location.pathname)]}
          style={{ flex: 1, minWidth: 0, background: 'transparent', borderBottom: 'none' }}
          items={[
            { key: 'new', label: <Link to="/">新建任务</Link> },
            { key: 'jobs', label: <Link to="/jobs">任务列表</Link> },
            { key: 'system', label: <Link to="/system">系统环境</Link> },
            { key: 'docs', label: <Link to="/docs">使用文档</Link> },
          ]}
        />

        {/* 打开页面即展示本机加速卡与权重状态（探测结果由 SystemProvider 缓存） */}
        <Space size={8} style={{ whiteSpace: 'nowrap' }}>
          {info && (info.gpu.devices.length
            ? <Tag color="geekblue">{info.gpu.devices[0].name}</Tag>
            : <Tag color="orange">CPU 模式</Tag>)}
          {info && (
            <Tag color={info.weights.valid ? 'green' : 'red'}>
              {info.weights.valid ? '权重就绪' : '权重缺失'}
            </Tag>
          )}
        </Space>
      </Header>

      <Content style={{ padding: '24px' }}>
        <div style={{ maxWidth: 1200, margin: '0 auto' }}>
          {error && (
            <Alert
              type="error"
              showIcon
              style={{ marginBottom: 16 }}
              message="无法获取系统环境"
              description={error}
            />
          )}

          {weightsMissing && !error && (
            <Alert
              type={downloadFailed ? 'error' : 'warning'}
              showIcon
              style={{ marginBottom: 16 }}
              message={
                downloadFailed
                  ? '检测权重未就绪，自动下载失败'
                  : download?.status === 'done'
                    ? '检测权重下载完成'
                    : '首次启动：正在自动下载检测权重…'
              }
              description={
                <Space direction="vertical" size={6} style={{ width: '100%' }}>
                  {download?.status === 'running' && (
                    <Progress percent={download.percent} size="small" style={{ maxWidth: 460 }} />
                  )}
                  <Typography.Text type="secondary">
                    {downloadFailed ? download?.error : info?.weights.reason}
                  </Typography.Text>
                </Space>
              }
              action={<Link to="/system">查看系统环境</Link>}
            />
          )}

          <Routes>
            <Route path="/" element={<NewJob />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
            <Route path="/system" element={<SystemPage />} />
            <Route path="/docs" element={<Docs />} />
          </Routes>
        </div>
      </Content>
    </Layout>
  )
}

export default function App() {
  return (
    <SystemProvider>
      <Shell />
    </SystemProvider>
  )
}
