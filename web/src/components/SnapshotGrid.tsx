import { Empty, Image } from 'antd'

import type { FrameItem } from '../api/types'

/** 检出帧快照网格（点击可放大预览）。 */
export default function SnapshotGrid({ frames }: { frames: FrameItem[] }) {
  if (!frames.length) return <Empty description="无检出帧快照" />

  return (
    <Image.PreviewGroup>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))',
          gap: 8,
        }}
      >
        {frames.map((frame) => (
          <div key={frame.name}>
            <Image
              src={frame.url}
              alt={frame.name}
              style={{ objectFit: 'cover', borderRadius: 4 }}
              height={110}
              width="100%"
            />
            <div style={{ fontSize: 11, color: '#8c8c8c', marginTop: 2 }}>
              {frame.name}
            </div>
          </div>
        ))}
      </div>
    </Image.PreviewGroup>
  )
}