/**
 * 系统环境自动检测（应用启动时执行一次）。
 *
 * 打开网页 → 探测 CPU / 内存 / GPU / 依赖版本 / 权重状态；
 * 权重缺失或只是 Git LFS 指针文件时，自动启动后台下载并轮询进度。
 * 结果通过 Context 共享给「系统环境」页与顶部状态条。
 */

import type { ReactNode } from 'react'
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { ApiError, getSystemInfo, getWeightDownload, startWeightDownload } from '../api/client'
import type { DownloadState, SystemInfo } from '../api/types'

interface SystemContextValue {
  info: SystemInfo | null
  download: DownloadState | null
  error: string | null
  loading: boolean
  refresh: (force?: boolean) => Promise<SystemInfo | null>
  downloadWeights: () => Promise<void>
}

const SystemContext = createContext<SystemContextValue | null>(null)

function messageOf(err: unknown, fallback: string) {
  return err instanceof ApiError ? err.message : fallback
}

export function SystemProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<SystemInfo | null>(null)
  const [download, setDownload] = useState<DownloadState | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async (force = true) => {
    try {
      setLoading(true)
      const data = await getSystemInfo(force)
      setInfo(data)
      setError(null)
      return data
    } catch (err) {
      setError(messageOf(err, '系统环境检测失败（后端未启动？）'))
      return null
    } finally {
      setLoading(false)
    }
  }, [])

  const downloadWeights = useCallback(async () => {
    try {
      let current = await startWeightDownload()
      setDownload(current)
      let attempts = 0
      while (current.status === 'running' && attempts < 900) {
        await new Promise((resolve) => setTimeout(resolve, 800))
        current = await getWeightDownload()
        setDownload(current)
        attempts += 1
      }
      if (current.status === 'running') {
        setError('权重下载超时，请到「系统环境」页重试或手动放置权重文件')
        return
      }
      await refresh(false)          // 权重状态不缓存，刷新即可（不重新初始化 CUDA）
    } catch (err) {
      setError(messageOf(err, '权重下载失败'))
    }
  }, [refresh])

  useEffect(() => {
    let cancelled = false
    const boot = async () => {
      const data = await refresh(true)
      if (!cancelled && data && !data.weights.valid) await downloadWeights()
    }
    boot()
    return () => { cancelled = true }
  }, [refresh, downloadWeights])

  const value = useMemo(
    () => ({ info, download, error, loading, refresh, downloadWeights }),
    [info, download, error, loading, refresh, downloadWeights],
  )
  return <SystemContext.Provider value={value}>{children}</SystemContext.Provider>
}

export function useSystem(): SystemContextValue {
  const value = useContext(SystemContext)
  if (!value) throw new Error('useSystem 必须在 SystemProvider 内使用')
  return value
}
