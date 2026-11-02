import { Statistic, Tooltip } from 'antd'

import { formatDuration, useDurationMode } from '../utils/duration'

interface Props {
  title: string
  seconds: number | null | undefined
  precision?: number
}

/** 耗时统计：点击可在「秒」与「时:分:秒」两种显示形式间切换。 */
export default function DurationStatistic({ title, seconds, precision = 1 }: Props) {
  const [mode, toggle] = useDurationMode()
  const hint = mode === 'seconds' ? '点击切换为 时:分:秒' : '点击切换为 秒'

  return (
    <Tooltip title={hint}>
      <div
        role="button"
        tabIndex={0}
        onClick={toggle}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            toggle()
          }
        }}
        style={{ cursor: 'pointer', display: 'inline-block' }}
      >
        <Statistic title={title} value={formatDuration(seconds, mode, precision)} />
      </div>
    </Tooltip>
  )
}