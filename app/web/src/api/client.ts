// API 封装：REST + SSE 订阅。开发模式经 vite 代理到 127.0.0.1:8000。

import type {
  DetectMode,
  DocContent,
  DocItem,
  DownloadState,
  FrameItem,
  Job,
  JobEvent,
  PresetItem,
  ResultJson,
  SystemInfo,
  UploadItem,
  VideoItem,
  WeightItem,
} from './types'

const BASE = '/api'

/** 后端结构化错误（含 422 字段级 errors）。 */
export class ApiError extends Error {
  status: number
  errors: string[]

  constructor(status: number, body: unknown) {
    const detail = (body ?? {}) as { message?: string; detail?: string; errors?: string[] }
    super(detail.message || detail.detail || `HTTP ${status}`)
    this.status = status
    this.errors = detail.errors ?? []
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    let body: unknown = null
    try {
      body = await res.json()
    } catch {
      body = null
    }
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

// ---------------------------------------------------------------- 元信息

export const listVideos = () =>
  request<{ root: string; items: VideoItem[] }>('/meta/videos')

export const listWeights = () =>
  request<{ items: WeightItem[] }>('/meta/weights')

export const getConfigSchema = () =>
  request<{ schema: Record<string, unknown>; defaults: Record<string, unknown> }>(
    '/meta/config-schema',
  )

export const listPresets = () =>
  request<{ items: PresetItem[] }>('/meta/presets')

/** 保存推理配置为预设（前端「保存推理配置」按钮）。 */
export const savePreset = (name: string, params: Record<string, unknown>) =>
  request<PresetItem>(`/meta/presets/${encodeURIComponent(name)}`, {
    method: 'PUT',
    body: JSON.stringify({ params }),
  })

// ---------------------------------------------------------------- 内置文档

export const listDocs = () => request<{ items: DocItem[] }>('/meta/docs')

export const getDoc = (name: string) =>
  request<DocContent>(`/meta/docs/${encodeURIComponent(name)}`)

// ---------------------------------------------------------------- 系统环境

export const getSystemInfo = (refresh = false) =>
  request<SystemInfo>(`/system/info?refresh=${refresh}`)

export const getWeightDownload = () =>
  request<DownloadState>('/system/weights/download')

export const startWeightDownload = () =>
  request<DownloadState>('/system/weights/download', { method: 'POST' })

// ---------------------------------------------------------------- 上传（用户数据）

export const listUploads = () =>
  request<{ root: string; items: UploadItem[] }>('/uploads')

export const deleteUpload = (name: string) =>
  request<{ deleted: string }>(`/uploads/${encodeURIComponent(name)}`, { method: 'DELETE' })

export const uploadVideoUrl = (name: string) =>
  `${BASE}/uploads/${encodeURIComponent(name)}/video`

export const uploadDownloadUrl = (name: string) =>
  `${BASE}/uploads/${encodeURIComponent(name)}/download`

/**
 * 上传源视频：以原始请求体直传（非 multipart），走 XHR 以获得进度回调。
 * 服务端流式落盘到 data/uploads/，返回项可直接作为新建任务的 source。
 */
export function uploadVideo(
  file: File,
  onProgress?: (percent: number) => void,
): Promise<UploadItem> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${BASE}/uploads?name=${encodeURIComponent(file.name)}`)
    xhr.setRequestHeader('Content-Type', 'application/octet-stream')
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as UploadItem)
        } catch {
          reject(new ApiError(xhr.status, { detail: '响应解析失败' }))
        }
      } else {
        let message = `HTTP ${xhr.status}`
        try {
          message = (JSON.parse(xhr.responseText) as { detail?: string }).detail ?? message
        } catch {
          /* 非 JSON 错误体，保留默认文案 */
        }
        reject(new ApiError(xhr.status, { detail: message }))
      }
    }
    xhr.onerror = () => reject(new ApiError(0, { detail: '网络错误，上传失败' }))
    xhr.send(file)
  })
}

// ---------------------------------------------------------------- 任务

export interface CreateJobPayload {
  source: string
  mode: DetectMode
  params: Record<string, unknown>
  preset?: string | null
}

export const createJob = (payload: CreateJobPayload) =>
  request<{ job_id: string; job: Job }>('/jobs', {
    method: 'POST',
    body: JSON.stringify(payload),
  })

export const listJobs = (limit = 50, offset = 0) =>
  request<{ total: number; limit: number; offset: number; items: Job[] }>(
    `/jobs?limit=${limit}&offset=${offset}`,
  )

export const getJob = (id: string) => request<Job>(`/jobs/${id}`)

export const cancelJob = (id: string) =>
  request<{ job_id: string; cancelled: boolean }>(`/jobs/${id}/cancel`, { method: 'POST' })

export const listFrames = (id: string) =>
  request<{ count: number; items: FrameItem[] }>(`/jobs/${id}/frames`)

export const getResult = (id: string) => request<ResultJson>(`/jobs/${id}/result`)

export const getLogs = (id: string) =>
  fetch(`${BASE}/jobs/${id}/logs`).then((r) => (r.ok ? r.text() : ''))

export const videoUrl = (id: string) => `${BASE}/jobs/${id}/video`
export const resultUrl = (id: string) => `${BASE}/jobs/${id}/result`

/**
 * 订阅任务事件流（SSE）。
 * 后端会在订阅时回放历史事件，因此晚连接也不会丢进度。
 * 返回 EventSource，调用方负责在组件卸载时 close()。
 */
export function subscribeJobEvents(
  id: string,
  onEvent: (event: JobEvent) => void,
  onError?: () => void,
): EventSource {
  const source = new EventSource(`${BASE}/jobs/${id}/events`)
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as JobEvent)
    } catch {
      /* 忽略无法解析的心跳/空行 */
    }
  }
  if (onError) source.onerror = () => onError()
  return source
}