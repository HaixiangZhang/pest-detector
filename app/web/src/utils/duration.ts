// 耗时显示格式：秒（123.4s）或 时:分:秒（00:02:03）。
// 全局共享 + 持久化：任一处点击切换，所有耗时同步变化；刷新后保持上次选择。
import { useCallback, useSyncExternalStore } from 'react'

export type DurationMode = 'seconds' | 'clock'

const STORAGE_KEY = 'pestdet.duration-mode'
const listeners = new Set<() => void>()

function readStored(): DurationMode {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'clock' ? 'clock' : 'seconds'
  } catch {
    return 'seconds'          // 隐私模式等写入受限时退回默认
  }
}

let current: DurationMode = readStored()

/** 把秒数格式化成当前显示形式。 */
export function formatDuration(
  seconds: number | null | undefined,
  mode: DurationMode,
  precision = 1,
): string {
  const value = typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0 ? seconds : 0
  if (mode === 'seconds') return `${value.toFixed(precision)}s`

  const total = Math.round(value)
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(Math.floor(total / 3600))}:${pad(Math.floor((total % 3600) / 60))}:${pad(total % 60)}`
}

function subscribe(cb: () => void) {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

/** 读取当前显示形式并返回切换函数（切换后全局组件同步更新）。 */
export function useDurationMode(): [DurationMode, () => void] {
  const mode = useSyncExternalStore(subscribe, () => current)
  const toggle = useCallback(() => {
    current = current === 'seconds' ? 'clock' : 'seconds'
    try {
      localStorage.setItem(STORAGE_KEY, current)
    } catch {
      /* 写入失败不影响本次会话内的切换 */
    }
    listeners.forEach((cb) => cb())
  }, [])
  return [mode, toggle]
}