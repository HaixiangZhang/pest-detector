import { Layout, Menu, Typography } from 'antd'
import { Link, Route, Routes, useLocation } from 'react-router-dom'

import JobDetail from './pages/JobDetail'
import Jobs from './pages/Jobs'
import NewJob from './pages/NewJob'

const { Header, Sider, Content } = Layout

export default function App() {
  const location = useLocation()
  const selected = location.pathname.startsWith('/jobs') ? 'jobs' : 'new'

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header style={{ display: 'flex', alignItems: 'center' }}>
        <Typography.Title level={4} style={{ color: '#fff', margin: 0 }}>
          pest_detector · 害虫检测与跨帧去重计数
        </Typography.Title>
      </Header>
      <Layout>
        <Sider width={200} theme="light">
          <Menu
            mode="inline"
            selectedKeys={[selected]}
            style={{ height: '100%', borderRight: 0 }}
            items={[
              { key: 'new', label: <Link to="/">新建任务</Link> },
              { key: 'jobs', label: <Link to="/jobs">任务列表</Link> },
            ]}
          />
        </Sider>
        <Content style={{ padding: 24, background: '#f5f5f5' }}>
          <Routes>
            <Route path="/" element={<NewJob />} />
            <Route path="/jobs" element={<Jobs />} />
            <Route path="/jobs/:id" element={<JobDetail />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  )
}