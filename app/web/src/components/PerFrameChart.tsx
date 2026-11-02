import { Empty } from 'antd'

interface Props {
  data: { frame: number; n: number }[]
}

/** 逐帧在线虫数曲线（纯 SVG，避免引入图表库）。 */
export default function PerFrameChart({ data }: Props) {
  if (!data.length) return <Empty description="无逐帧数据" />

  const width = 760
  const height = 180
  const padX = 36
  const padY = 24
  const maxN = Math.max(1, ...data.map((d) => d.n))
  const span = Math.max(1, data.length - 1)

  const px = (index: number) => padX + (index / span) * (width - padX * 2)
  const py = (value: number) => height - padY - (value / maxN) * (height - padY * 2)
  const points = data.map((d, index) => `${px(index)},${py(d.n)}`).join(' ')

  return (
    <svg viewBox={`0 0 ${width} ${height}`} style={{ width: '100%', height: 'auto' }}>
      <line x1={padX} y1={height - padY} x2={width - padX} y2={height - padY}
            stroke="#d9d9d9" />
      <line x1={padX} y1={padY} x2={padX} y2={height - padY} stroke="#d9d9d9" />
      <text x={4} y={padY + 4} fontSize="11" fill="#8c8c8c">{maxN}</text>
      <text x={4} y={height - padY} fontSize="11" fill="#8c8c8c">0</text>
      <polyline points={points} fill="none" stroke="#1677ff" strokeWidth="1.5" />
      <text x={padX} y={height - 6} fontSize="11" fill="#8c8c8c">
        帧 {data[0].frame}
      </text>
      <text x={width - padX} y={height - 6} fontSize="11" fill="#8c8c8c"
            textAnchor="end">
        帧 {data[data.length - 1].frame}
      </text>
    </svg>
  )
}